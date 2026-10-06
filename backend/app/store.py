"""Repository registry, background parsing and query caches."""
from __future__ import annotations

import json
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import CACHE_DIR, REGISTRY_FILE, REPOS_DIR, ensure_dirs
from .identity import IdentityResolver, MergeGroup
from .metrics import Query, build_bundle
from .parse import (
    ParsedRepo,
    RepoSignature,
    build_path_tree,
    parse_repo,
    repo_signature,
)


@dataclass
class RepoRecord:
    id: str
    name: str
    source: str                      # "zip" | "clone"
    url: str | None
    path: str
    created_at: float
    status: str = "parsing"          # cloning | parsing | ready | error
    detail: str = ""                 # human readable progress
    error: str | None = None
    head: str | None = None
    branch: str | None = None
    commit_count: int | None = None
    author_count: int | None = None
    file_count: int | None = None
    first_commit: str | None = None
    last_commit: str | None = None
    ref_count: int | None = None
    mailmap_present: bool = False
    merges: list[dict] = field(default_factory=list)
    parsed_at: float | None = None

    def as_json(self, version: int | None = None) -> dict:
        data = asdict(self)
        data["version"] = version or 0
        return data


class _LRU:
    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._data: dict[Any, Any] = {}
        self._lock = threading.Lock()

    def get(self, key: Any) -> Any | None:
        with self._lock:
            value = self._data.get(key)
            if value is not None:
                self._data.pop(key, None)
                self._data[key] = value
            return value

    def put(self, key: Any, value: Any) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._data[key] = value
            while len(self._data) > self.capacity:
                self._data.pop(next(iter(self._data)))

    def invalidate_prefix(self, prefix: Any) -> None:
        with self._lock:
            for key in [k for k in self._data
                        if isinstance(k, tuple) and k and k[0] == prefix]:
                self._data.pop(key, None)


class Store:
    """Owns the repository registry, parsed models and result caches."""

    def __init__(self) -> None:
        ensure_dirs()
        self._lock = threading.RLock()
        self._records: dict[str, RepoRecord] = {}
        self._parsed: dict[str, ParsedRepo] = {}
        self._versions: dict[str, int] = {}
        self._inflight: set[str] = set()
        self._pool = ThreadPoolExecutor(max_workers=2,
                                        thread_name_prefix="rat-parse")
        self._bundles = _LRU(48)
        self._resolvers = _LRU(24)
        self._trees = _LRU(8)
        self._load()

    # ------------------------------------------------------------------ #
    # Registry persistence
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        if not REGISTRY_FILE.exists():
            return
        try:
            raw = json.loads(REGISTRY_FILE.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in raw.get("repos", []):
            try:
                record = RepoRecord(**item)
            except TypeError:
                continue
            if not Path(record.path).exists():
                continue
            # Parsed models are not persisted; they are rebuilt on demand.
            record.status = "pending"
            record.detail = "Waiting to be parsed"
            self._records[record.id] = record

    def _save(self) -> None:
        payload = {"repos": [asdict(r) for r in self._records.values()]}
        tmp = REGISTRY_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), "utf-8")
        tmp.replace(REGISTRY_FILE)

    # ------------------------------------------------------------------ #
    # Repository records
    # ------------------------------------------------------------------ #
    def list_records(self) -> list[RepoRecord]:
        with self._lock:
            records = sorted(
                self._records.values(), key=lambda r: r.created_at, reverse=True)
            return list(records)

    def get_record(self, repo_id: str) -> RepoRecord:
        with self._lock:
            record = self._records.get(repo_id)
        if record is None:
            raise KeyError(repo_id)
        return record

    def add_record(self, record: RepoRecord, start_parse: bool = True) -> None:
        with self._lock:
            self._records[record.id] = record
            self._versions[record.id] = 0
            self._save()
        if start_parse:
            self.ensure_parsed(record.id)

    def update_record(self, repo_id: str, **fields) -> RepoRecord:
        with self._lock:
            record = self._records[repo_id]
            for key, value in fields.items():
                setattr(record, key, value)
            self._save()
            return record

    def delete_record(self, repo_id: str) -> None:
        with self._lock:
            record = self._records.pop(repo_id, None)
            self._parsed.pop(repo_id, None)
            self._versions.pop(repo_id, None)
            self._inflight.discard(repo_id)
            self._save()
        self._bundles.invalidate_prefix(repo_id)
        self._resolvers.invalidate_prefix(repo_id)
        self._trees.invalidate_prefix(repo_id)
        if record is not None:
            root = Path(record.path)
            # Only remove directories we created under data/repos.
            if root.exists() and REPOS_DIR in root.resolve().parents:
                shutil.rmtree(root, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #
    def ensure_parsed(self, repo_id: str) -> None:
        """Kick off a background parse if the repo is not parsed yet."""
        with self._lock:
            record = self._records.get(repo_id)
            if record is None or repo_id in self._parsed:
                return
            if repo_id in self._inflight or record.status == "cloning":
                return
            self._inflight.add(repo_id)
            record.status = "parsing"
            record.detail = "Parsing commit history…"
            record.error = None
        self._pool.submit(self._parse_job, repo_id)

    def _parse_job(self, repo_id: str) -> None:
        started = time.time()

        def progress(count: int) -> None:
            with self._lock:
                rec = self._records.get(repo_id)
                if rec is not None:
                    rec.detail = f"Parsed {count:,} commits…"

        try:
            record = self.get_record(repo_id)
            signature = repo_signature(record.path)
            parsed = self._load_cached(repo_id, signature)
            from_cache = parsed is not None
            if parsed is None:
                parsed = parse_repo(record.path, on_progress=progress,
                                    signature=signature)
                self._save_cache(repo_id, signature, parsed)
            elapsed = time.time() - started

            with self._lock:
                self._parsed[repo_id] = parsed
                self._versions[repo_id] = self._versions.get(repo_id, 0) + 1
                rec = self._records[repo_id]
                rec.status = "ready"
                rec.detail = (
                    f"Loaded from cache ({elapsed:.1f}s)" if from_cache
                    else f"Ready ({elapsed:.1f}s)"
                )
                rec.error = None
                rec.head = parsed.head[:12] if parsed.head else None
                rec.branch = parsed.branch or None
                rec.commit_count = len(parsed.commits)
                rec.file_count = len(parsed.paths)
                rec.ref_count = len(parsed.refs)
                rec.mailmap_present = parsed.mailmap_present
                rec.author_count = len(self._identity_resolver(
                    parsed, self._groups(rec)).key_to_raws)
                rec.parsed_at = time.time()
                if parsed.commits:
                    dates = [c.ts for c in parsed.commits if c.ts]
                    rec.first_commit = (
                        time.strftime("%Y-%m-%d", time.gmtime(min(dates)))
                        if dates else None)
                    rec.last_commit = (
                        time.strftime("%Y-%m-%d", time.gmtime(max(dates)))
                        if dates else None)
                self._save()
            self._bundles.invalidate_prefix(repo_id)
            self._resolvers.invalidate_prefix(repo_id)
            self._trees.invalidate_prefix(repo_id)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            with self._lock:
                rec = self._records.get(repo_id)
                if rec is not None:
                    rec.status = "error"
                    rec.error = str(exc)[:1000]
                    rec.detail = "Parsing failed"
                    self._save()
        finally:
            with self._lock:
                self._inflight.discard(repo_id)

    def parsed_or_none(self, repo_id: str) -> ParsedRepo | None:
        with self._lock:
            return self._parsed.get(repo_id)

    # ------------------------------------------------------------------ #
    # Persisted parse cache (survives server restarts)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _cache_file(repo_id: str, signature: RepoSignature) -> Path:
        return CACHE_DIR / f"{repo_id}-{signature.cache_token()}.pkl"

    def _load_cached(
        self, repo_id: str, signature: RepoSignature,
    ) -> ParsedRepo | None:
        import pickle
        path = self._cache_file(repo_id, signature)
        if not path.is_file():
            return None
        try:
            with path.open("rb") as fh:
                parsed = pickle.load(fh)
        except Exception:  # noqa: BLE001 - corrupted cache must never crash us
            path.unlink(missing_ok=True)
            return None
        return parsed if isinstance(parsed, ParsedRepo) else None

    def _save_cache(
        self, repo_id: str, signature: RepoSignature, parsed: ParsedRepo,
    ) -> None:
        import pickle
        path = self._cache_file(repo_id, signature)
        tmp = path.with_suffix(".pkl.tmp")
        try:
            with tmp.open("wb") as fh:
                pickle.dump(parsed, fh, protocol=pickle.HIGHEST_PROTOCOL)
            tmp.replace(path)
        except Exception:  # noqa: BLE001 - caching is best effort
            tmp.unlink(missing_ok=True)
            return
        for stale in CACHE_DIR.glob(f"{repo_id}-*.pkl"):
            if stale != path:
                stale.unlink(missing_ok=True)

    def ensure_all_parsed(self) -> None:
        """Re-parse every repository known from the registry file."""
        for record in self.list_records():
            self.ensure_parsed(record.id)

    def require_parsed(self, repo_id: str) -> ParsedRepo:
        parsed = self.parsed_or_none(repo_id)
        if parsed is None:
            raise RuntimeError("Repository is still parsing")
        return parsed

    def version(self, repo_id: str) -> int:
        with self._lock:
            return self._versions.get(repo_id, 0)

    # ------------------------------------------------------------------ #
    # Identity resolver + metric bundles (cached)
    # ------------------------------------------------------------------ #
    def resolver(self, repo_id: str, mailmap: bool) -> IdentityResolver:
        parsed = self.require_parsed(repo_id)
        record = self.get_record(repo_id)
        merges_sig = json.dumps(record.merges, sort_keys=True)
        key = (repo_id, self.version(repo_id), mailmap, merges_sig)
        cached = self._resolvers.get(key)
        if cached is None:
            cached = IdentityResolver(
                parsed=parsed, groups=self._groups(record), apply_mailmap=mailmap)
            self._resolvers.put(key, cached)
        return cached

    @staticmethod
    def _groups(record: RepoRecord) -> list[MergeGroup]:
        return [
            MergeGroup(id=g["id"], label=g.get("label"), members=g["members"])
            for g in record.merges
        ]

    @staticmethod
    def _identity_resolver(
        parsed: ParsedRepo, groups: list[MergeGroup],
    ) -> IdentityResolver:
        return IdentityResolver(parsed=parsed, groups=groups, apply_mailmap=True)

    def recount_authors(self, repo_id: str) -> None:
        """Keep the record's author count in sync after merge changes."""
        with self._lock:
            parsed = self._parsed.get(repo_id)
            record = self._records.get(repo_id)
            if parsed is None or record is None:
                return
            count = len(self._identity_resolver(
                parsed, self._groups(record)).key_to_raws)
            if record.author_count != count:
                self.update_record(repo_id, author_count=count)

    def bundle(self, repo_id: str, mailmap: bool, q: Query) -> dict:
        parsed = self.require_parsed(repo_id)
        resolver = self.resolver(repo_id, mailmap)
        key = (repo_id, self.version(repo_id), mailmap,
               json.dumps(self.get_record(repo_id).merges, sort_keys=True),
               q.cache_key())
        cached = self._bundles.get(key)
        if cached is None:
            cached = build_bundle(parsed, resolver, q)
            self._bundles.put(key, cached)
        return cached

    def path_tree(self, repo_id: str) -> dict:
        parsed = self.require_parsed(repo_id)
        key = (repo_id, self.version(repo_id))
        cached = self._trees.get(key)
        if cached is None:
            cached = build_path_tree(parsed.paths)
            self._trees.put(key, cached)
        return cached


store = Store()
