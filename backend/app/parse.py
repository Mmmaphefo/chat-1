"""Streaming parser that turns a git repository into an in-memory model.

A single `git log` invocation is walked in chunks; every commit is stored
once with its per-file line statistics, so all later metric queries are pure
in-memory scans (no repeated git invocations, no repeated repository access).

Design notes
------------
* ``--use-mailmap`` together with ``%aN``/``%aE`` makes git itself apply the
  repository ``.mailmap``; raw identities are captured with ``%an``/``%ae`` so
  the UI can offer manual merging of the raw aliases.
* ``--no-renames`` keeps the numstat format unambiguous: a rename appears as
  a deletion plus an addition.
* ``-z`` NUL-terminates records so file names containing tabs/newlines are
  parsed correctly.
* Merge commits carry no numstat entries (git default); they are counted as
  commits but contribute no line churn.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .gitio import git_env

# Field separator inside a commit header line.
_US = b"\x1f"
# Record separator: every commit block starts with this byte.
_RS = b"\x1e"

_PRETTY = "%x1e%H%x1f%P%x1f%an%x1f%ae%x1f%aN%x1f%aE%x1f%aI%x1f%s"

_CHUNK = 1 << 22  # 4 MiB


@dataclass(slots=True)
class CommitData:
    hash: str
    parents: tuple[str, ...]
    name: str            # raw author name (%an)
    email: str           # raw author email (%ae)
    mm_name: str         # mailmap-resolved name (%aN)
    mm_email: str        # mailmap-resolved email (%aE)
    date_iso: str        # author date, ISO-8601 with timezone (%aI)
    date_str: str        # author date, YYYY-MM-DD (used for day filters)
    ts: int              # author date as epoch seconds
    subject: str
    is_merge: bool
    added: int           # total lines added (0 for merges)
    deleted: int
    files: list[tuple[int, int, int]]  # (path_id, added, deleted)


@dataclass
class ParsedRepo:
    commits: list[CommitData]
    index: dict[str, int]                 # full hash -> commit position
    paths: list[str]                      # path_id -> repository path
    path_ids: dict[str, int]              # repository path -> path_id
    head: str
    branch: str
    refs: list[str]                       # all ref names (branches/tags/...)
    head_reachable: bytearray             # 1 when commit is an ancestor of HEAD
    binary_paths: set[int]                # path ids that ever changed as binary
    raw_counts: dict[tuple[str, str], int]  # raw identity -> commit count
    mailmap_present: bool
    num_stats: int = 0

    def path_id(self, path: str) -> int | None:
        return self.path_ids.get(path)


def _to_epoch(iso: str) -> tuple[int, str]:
    """Return (epoch seconds, YYYY-MM-DD) for an ISO author date string."""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return 0, "1970-01-01"
    return int(dt.timestamp()), dt.date().isoformat()


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "replace")


class _Builder:
    """Accumulates parsed commits while the git log stream is consumed."""

    def __init__(self) -> None:
        self.commits: list[CommitData] = []
        self.index: dict[str, int] = {}
        self.paths: list[str] = []
        self.path_ids: dict[str, int] = {}
        self.binary_paths: set[int] = set()
        self.raw_counts: dict[tuple[str, str], int] = {}
        self.num_stats = 0

    def path_id(self, path: str) -> int:
        pid = self.path_ids.get(path)
        if pid is None:
            pid = len(self.paths)
            self.path_ids[path] = pid
            self.paths.append(path)
        return pid

    def add_segment(self, seg: bytes) -> None:
        if not seg:
            return
        fields = seg.split(_US, 7)
        if len(fields) != 8:
            return  # not a commit header (should not happen)
        hash_b, parents_b, an, ae, mmn, mme, date_b, tail = fields

        nl = tail.find(b"\n")
        if nl >= 0:
            subject_b, stats_b = tail[:nl], tail[nl + 1:]
        else:
            subject_b, stats_b = tail.rstrip(b"\x00"), b""

        files: list[tuple[int, int, int]] = []
        added = deleted = 0
        if stats_b:
            for token in stats_b.split(b"\x00"):
                if not token:
                    continue
                parts = token.split(b"\t", 2)
                if len(parts) != 3:
                    continue
                a_b, d_b, path_b = parts
                if a_b == b"-":  # binary file
                    pid = self.path_id(_decode(path_b))
                    self.binary_paths.add(pid)
                    a = d = 0
                else:
                    try:
                        a, d = int(a_b), int(d_b)
                    except ValueError:
                        continue
                    pid = self.path_id(_decode(path_b))
                files.append((pid, a, d))
                added += a
                deleted += d
            self.num_stats += len(files)

        iso = _decode(date_b)
        ts, day = _to_epoch(iso)
        name, email = _decode(an), _decode(ae)
        raw = (name, email)
        self.raw_counts[raw] = self.raw_counts.get(raw, 0) + 1

        parents = tuple(_decode(p) for p in parents_b.split(b" ") if p)
        cid = len(self.commits)
        self.commits.append(CommitData(
            hash=_decode(hash_b),
            parents=parents,
            name=name,
            email=email,
            mm_name=_decode(mmn),
            mm_email=_decode(mme),
            date_iso=iso,
            date_str=day,
            ts=ts,
            subject=_decode(subject_b),
            is_merge=len(parents) > 1,
            added=added,
            deleted=deleted,
            files=files,
        ))
        self.index[_decode(hash_b)] = cid


@dataclass
class RepoSignature:
    """Cheap `git` metadata used to validate a persisted parse cache."""
    head: str
    branch: str
    refs: list[str]
    all_count: int
    mailmap_present: bool = False
    mailmap_digest: str = ""

    def cache_token(self) -> str:
        import hashlib
        blob = "|".join(
            [self.head, self.branch, str(self.all_count), self.mailmap_digest,
             *self.refs])
        return hashlib.sha1(blob.encode("utf-8", "replace")).hexdigest()[:16]


def _detect_mailmap(repo_path: str | Path) -> tuple[bool, str]:
    """Return (mailmap present, digest of its contents)."""
    import hashlib
    content: bytes | None = None
    try:
        content = _git_out_bytes(repo_path, "cat-file", "blob", "HEAD:.mailmap")
    except RuntimeError:
        worktree_file = Path(repo_path) / ".mailmap"
        if worktree_file.is_file():
            try:
                content = worktree_file.read_bytes()
            except OSError:
                content = None
    if content is None:
        return False, ""
    return True, hashlib.sha1(content).hexdigest()[:12]


def repo_signature(repo_path: str | Path) -> RepoSignature:
    """Read HEAD, branch, refs and the total commit count (fast)."""
    head = ""
    branch = ""
    refs: list[str] = []
    all_count = 0
    try:
        head = _git_out(repo_path, "rev-parse", "HEAD").strip()
    except RuntimeError:
        pass
    try:
        branch = _git_out(
            repo_path, "symbolic-ref", "--short", "-q", "HEAD").strip()
    except RuntimeError:
        pass
    try:
        for line in _git_out(
                repo_path, "for-each-ref", "--format=%(refname)").splitlines():
            if line.strip():
                refs.append(line.strip())
    except RuntimeError:
        pass
    try:
        count = _git_out(repo_path, "rev-list", "--count", "--all").strip()
        all_count = int(count) if count.isdigit() else 0
    except RuntimeError:
        pass
    mailmap_present, mailmap_digest = _detect_mailmap(repo_path)
    return RepoSignature(head=head, branch=branch, refs=refs,
                         all_count=all_count, mailmap_present=mailmap_present,
                         mailmap_digest=mailmap_digest)


def parse_repo(
    repo_path: str | Path,
    on_progress=None,
    signature: RepoSignature | None = None,
) -> ParsedRepo:
    """Parse the full history reachable from all refs of ``repo_path``."""
    cmd = [
        "git", "-C", str(repo_path),
        "-c", "log.showSignature=false",
        "-c", "i18n.logOutputEncoding=UTF-8",
        "-c", "core.quotepath=false",
        "log", "--all", "--use-mailmap", "--no-renames", "--numstat", "-z",
        f"--pretty=format:{_PRETTY}",
    ]
    builder = _Builder()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=git_env(),
    )
    assert proc.stdout is not None
    tail = b""
    pending = 0
    try:
        while True:
            chunk = proc.stdout.read(_CHUNK)
            if not chunk:
                break
            data = tail + chunk
            segments = data.split(_RS)
            tail = segments.pop()  # may be an incomplete record
            for seg in segments:
                builder.add_segment(seg)
            pending += 1
            if on_progress is not None and pending % 8 == 0:
                on_progress(len(builder.commits))
        builder.add_segment(tail)
    finally:
        stderr = proc.stderr.read() if proc.stderr else b""
        code = proc.wait()
    if code != 0:
        raise RuntimeError(
            "git log failed: " + stderr.decode("utf-8", "replace").strip())

    parsed = _finish(repo_path, builder, signature)
    if on_progress is not None:
        on_progress(len(parsed.commits))
    return parsed


def _finish(
    repo_path: str | Path,
    builder: _Builder,
    signature: RepoSignature | None = None,
) -> ParsedRepo:
    sig = signature or repo_signature(repo_path)
    head = sig.head
    branch = sig.branch
    refs = sig.refs
    mailmap = sig.mailmap_present

    reachable = _reachable_from(builder.index, builder.commits, head)

    return ParsedRepo(
        commits=builder.commits,
        index=builder.index,
        paths=builder.paths,
        path_ids=builder.path_ids,
        head=head,
        branch=branch,
        refs=refs,
        head_reachable=reachable,
        binary_paths=builder.binary_paths,
        raw_counts=builder.raw_counts,
        mailmap_present=mailmap,
        num_stats=builder.num_stats,
    )


def _reachable_from(
    index: dict[str, int], commits: list[CommitData], head: str,
) -> bytearray:
    """Mark every commit that is an ancestor of HEAD (inclusive)."""
    mask = bytearray(len(commits))
    start = index.get(head)
    if start is None:
        # No HEAD (empty repo or unknown) -> treat everything as reachable.
        for i in range(len(commits)):
            mask[i] = 1
        return mask
    stack = [start]
    mask[start] = 1
    while stack:
        cid = stack.pop()
        for parent in commits[cid].parents:
            pid = index.get(parent)
            if pid is not None and not mask[pid]:
                mask[pid] = 1
                stack.append(pid)
    return mask


def _git_out(repo_path: str | Path, *args: str) -> str:
    return _git_out_bytes(repo_path, *args).decode("utf-8", "replace")


def _git_out_bytes(repo_path: str | Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True, timeout=120, env=git_env(),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace").strip())
    return proc.stdout


def build_path_tree(paths: list[str]) -> dict:
    """Build a nested directory tree from every path seen in history."""
    root: dict = {"name": "", "path": "", "type": "dir", "files": 0, "children": {}}
    for p in paths:
        parts = p.split("/")
        node = root
        node["files"] += 1
        for i, part in enumerate(parts):
            is_file = i == len(parts) - 1
            child = node["children"].get(part)
            if child is None:
                child = {
                    "name": part,
                    "path": "/".join(parts[: i + 1]) + ("" if is_file else "/"),
                    "type": "file" if is_file else "dir",
                    "files": 0,
                    "children": {},
                }
                node["children"][part] = child
            child["files"] += 1
            node = child

    def finalize(node: dict) -> dict:
        children = node.pop("children")
        node["children"] = sorted(
            (finalize(c) for c in children.values()),
            key=lambda n: (n["type"] != "dir", -n["files"], n["name"]),
        )
        return node

    return finalize(root)


def parent_dirs(path: str) -> list[str]:
    """All ancestor directory paths ('' is the repository root)."""
    dirs = [""]
    parts = path.split("/")
    for i in range(len(parts) - 1):
        dirs.append("/".join(parts[: i + 1]) + "/")
    return dirs


__all__ = [
    "CommitData",
    "ParsedRepo",
    "RepoSignature",
    "build_path_tree",
    "parent_dirs",
    "parse_repo",
    "repo_signature",
]
