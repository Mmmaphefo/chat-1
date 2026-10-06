"""Metric computation for repositories, commit sets, files, directories
and authors.

All metrics are derived from one in-memory model produced by ``parse.py``:

* selecting a commit set is O(#commits);
* aggregating is exactly one pass over the selected commits' file statistics;
* queries with no path/author/date/commit filter hit a pre-computed
  full-history bundle, so the default dashboard view costs O(1).

Definitions (also shown in the UI):

* ``commits``        number of commits in the set
* ``churn``          linesAdded + linesDeleted
* ``net``            linesAdded - linesDeleted
* ``filesChanged``   distinct file paths touched
* file ``commits``   number of commits that touched the file (volatility)
* directory metrics  rolled up over every descendant file
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import date

from .identity import IdentityResolver
from .parse import ParsedRepo, parent_dirs


@dataclass
class Query:
    commits: list[str] | None = None     # hash list / unique prefixes
    from_date: str | None = None         # YYYY-MM-DD inclusive
    to_date: str | None = None           # YYYY-MM-DD inclusive
    authors: list[str] | None = None     # effective identity keys
    path: str | None = None              # file path or directory prefix
    scope: str = "head"                  # "head" | "all"
    mailmap: bool = True
    exclude_merges: bool = False

    @classmethod
    def from_json(cls, data: dict | None) -> "Query":
        data = data or {}
        return cls(
            commits=data.get("commits") or None,
            from_date=data.get("fromDate") or None,
            to_date=data.get("toDate") or None,
            authors=data.get("authors") or None,
            path=(data.get("path") or "").strip() or None,
            scope="all" if data.get("scope") == "all" else "head",
            mailmap=bool(data.get("mailmap", True)),
            exclude_merges=bool(data.get("excludeMerges", False)),
        )

    @property
    def is_unfiltered(self) -> bool:
        return not (self.commits or self.from_date or self.to_date
                    or self.authors or self.path or self.exclude_merges)

    def describe(self) -> dict:
        return {
            "commits": self.commits,
            "fromDate": self.from_date,
            "toDate": self.to_date,
            "authors": self.authors,
            "path": self.path,
            "scope": self.scope,
            "mailmap": self.mailmap,
            "excludeMerges": self.exclude_merges,
            "isUnfiltered": self.is_unfiltered,
        }

    def cache_key(self) -> str:
        return json.dumps(self.describe(), sort_keys=True)


@dataclass
class Selection:
    ids: list[int]
    mask: bytearray
    path_ids: set[int] | None
    scoped_total: int


# --------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------- #

def _resolve_prefixes(parsed: ParsedRepo, prefixes: list[str]) -> tuple[set[int], list[str]]:
    """Resolve hash prefixes; returns (commit ids, unresolved prefixes)."""
    short: dict[str, list[str]] = {}
    for h in parsed.index:
        short.setdefault(h[:8], []).append(h)
    ids: set[int] = set()
    unresolved: list[str] = []
    for raw in prefixes:
        p = raw.strip().lower()
        if not p:
            continue
        if p in parsed.index:                       # full hash
            ids.add(parsed.index[p])
            continue
        candidates = short.get(p[:8], [])
        matches = [h for h in candidates if h.startswith(p)]
        if not matches:
            unresolved.append(raw)
        elif len(matches) == 1:
            ids.add(parsed.index[matches[0]])
        else:
            unresolved.append(raw)                  # ambiguous
    return ids, unresolved


def match_path_ids(parsed: ParsedRepo, path: str) -> set[int]:
    """Path ids matching a filter: exact file and/or directory subtree."""
    exact = parsed.path_ids.get(path)
    prefix = path if path.endswith("/") else path + "/"
    out: set[int] = set()
    if exact is not None:
        out.add(exact)
    for p, pid in parsed.path_ids.items():
        if p.startswith(prefix):
            out.add(pid)
    return out


def select(
    parsed: ParsedRepo,
    resolver: IdentityResolver,
    q: Query,
) -> Selection:
    n = len(parsed.commits)
    if q.scope == "head" and parsed.head:
        mask = bytearray(parsed.head_reachable)
    else:
        mask = bytearray(b"\x01") * n
    scoped_total = sum(mask)

    if q.from_date:
        for i, c in enumerate(parsed.commits):
            if mask[i] and c.date_str < q.from_date:
                mask[i] = 0
    if q.to_date:
        for i, c in enumerate(parsed.commits):
            if mask[i] and c.date_str > q.to_date:
                mask[i] = 0
    if q.exclude_merges:
        for i, c in enumerate(parsed.commits):
            if mask[i] and c.is_merge:
                mask[i] = 0
    if q.authors:
        wanted = set(q.authors)
        for i, c in enumerate(parsed.commits):
            if mask[i] and resolver.key_for_commit(c.name, c.email) not in wanted:
                mask[i] = 0
    if q.commits:
        chosen, _unresolved = _resolve_prefixes(parsed, q.commits)
        keep = bytearray(n)
        for i in chosen:
            keep[i] = 1
        for i in range(n):
            if not keep[i]:
                mask[i] = 0

    path_ids: set[int] | None = None
    if q.path:
        path_ids = match_path_ids(parsed, q.path)
        if not path_ids:
            for i in range(n):
                mask[i] = 0
        else:
            for i, c in enumerate(parsed.commits):
                if not mask[i]:
                    continue
                if all(pid not in path_ids for pid, _a, _d in c.files):
                    mask[i] = 0

    ids = [i for i in range(n) if mask[i]]
    return Selection(ids=ids, mask=mask, path_ids=path_ids,
                     scoped_total=scoped_total)


# --------------------------------------------------------------------- #
# Aggregation (single pass over the selected commit set)
# --------------------------------------------------------------------- #

@dataclass(slots=True)
class PathAgg:
    commits: int = 0
    added: int = 0
    deleted: int = 0
    authors: set = field(default_factory=set)
    first_ts: int = 0
    last_ts: int = 0


@dataclass(slots=True)
class AuthorAgg:
    name: str = ""
    email: str = ""
    commits: int = 0
    merge_commits: int = 0
    added: int = 0
    deleted: int = 0
    files: set = field(default_factory=set)
    first_ts: int = 0
    last_ts: int = 0


@dataclass(slots=True)
class DirAgg:
    commits: int = 0
    added: int = 0
    deleted: int = 0
    files: set = field(default_factory=set)
    authors: set = field(default_factory=set)
    first_ts: int = 0
    last_ts: int = 0


@dataclass
class Aggregates:
    commits: int = 0
    merge_commits: int = 0
    added: int = 0
    deleted: int = 0
    files: set = field(default_factory=set)
    binary_files: set = field(default_factory=set)
    authors: set = field(default_factory=set)
    first_ts: int = 0
    last_ts: int = 0
    first_date: str = ""
    last_date: str = ""
    path_agg: dict[int, PathAgg] = field(default_factory=dict)
    author_agg: dict[str, AuthorAgg] = field(default_factory=dict)
    dir_agg: dict[str, DirAgg] = field(default_factory=dict)
    timeseries: dict[str, list[int]] = field(default_factory=dict)


def aggregate(
    parsed: ParsedRepo,
    resolver: IdentityResolver,
    sel: Selection,
) -> Aggregates:
    agg = Aggregates()
    if not sel.ids:
        agg.dir_agg[""] = DirAgg()
        return agg

    commits = parsed.commits
    paths = parsed.paths
    path_filter = sel.path_ids
    path_agg = agg.path_agg
    author_agg = agg.author_agg
    dir_agg = agg.dir_agg
    ts = agg.timeseries

    for cid in sel.ids:
        c = commits[cid]
        key = resolver.key_for_commit(c.name, c.email)
        author = author_agg.get(key)
        if author is None:
            name, email = resolver.display(key)
            author = AuthorAgg(name=name, email=email)
            author_agg[key] = author
        author.commits += 1
        if c.is_merge:
            author.merge_commits += 1
        if author.first_ts == 0 or (c.ts and c.ts < author.first_ts):
            author.first_ts = c.ts
        if c.ts > author.last_ts:
            author.last_ts = c.ts

        agg.commits += 1
        if c.is_merge:
            agg.merge_commits += 1
        if agg.first_ts == 0 or (c.ts and c.ts < agg.first_ts):
            agg.first_ts = c.ts
            agg.first_date = c.date_str
        if c.ts > agg.last_ts:
            agg.last_ts = c.ts
            agg.last_date = c.date_str
        agg.authors.add(key)

        bucket = ts.get(c.date_str)
        if bucket is None:
            bucket = [0, 0, 0]
            ts[c.date_str] = bucket
        bucket[0] += 1

        dirs_seen: set[str] | None = None
        for pid, a, d in c.files:
            if path_filter is not None and pid not in path_filter:
                continue
            p = path_agg.get(pid)
            if p is None:
                p = PathAgg(first_ts=c.ts, last_ts=c.ts)
                path_agg[pid] = p
            p.commits += 1
            p.added += a
            p.deleted += d
            p.authors.add(key)
            if c.ts and (p.first_ts == 0 or c.ts < p.first_ts):
                p.first_ts = c.ts
            if c.ts > p.last_ts:
                p.last_ts = c.ts

            author.added += a
            author.deleted += d
            author.files.add(pid)

            agg.added += a
            agg.deleted += d
            agg.files.add(pid)
            if pid in parsed.binary_paths:
                agg.binary_files.add(pid)
            bucket[1] += a
            bucket[2] += d

            if dirs_seen is None:
                dirs_seen = set()
            dirs_seen.update(parent_dirs(paths[pid]))

        if dirs_seen:
            for dpath in dirs_seen:
                d = dir_agg.get(dpath)
                if d is None:
                    d = DirAgg()
                    dir_agg[dpath] = d
                d.commits += 1

    # Directory roll-up from the per-path aggregates (exact, no double sums).
    for pid, p in path_agg.items():
        for dpath in parent_dirs(paths[pid]):
            d = dir_agg.get(dpath)
            if d is None:
                d = DirAgg()
                dir_agg[dpath] = d
            d.added += p.added
            d.deleted += p.deleted
            d.files.add(pid)
            d.authors |= p.authors
            if d.first_ts == 0 or (p.first_ts and p.first_ts < d.first_ts):
                d.first_ts = p.first_ts
            if p.last_ts > d.last_ts:
                d.last_ts = p.last_ts
    return agg


# --------------------------------------------------------------------- #
# Serialisation
# --------------------------------------------------------------------- #

def _days_between(first_ts: int, last_ts: int) -> int:
    if not first_ts or not last_ts:
        return 0
    return max(1, (last_ts - first_ts) // 86400 + 1)


def _iso(ts: int) -> str | None:
    if not ts:
        return None
    return date.fromtimestamp(ts).isoformat()


def _repo_metrics(agg: Aggregates, scoped_total: int, selected: int) -> dict:
    days = _days_between(agg.first_ts, agg.last_ts)
    non_merge = max(0, agg.commits - agg.merge_commits)
    return {
        "commits": agg.commits,
        "mergeCommits": agg.merge_commits,
        "authors": len(agg.authors),
        "linesAdded": agg.added,
        "linesDeleted": agg.deleted,
        "churn": agg.added + agg.deleted,
        "net": agg.added - agg.deleted,
        "filesChanged": len(agg.files),
        "binaryFilesChanged": len(agg.binary_files),
        "firstCommit": _iso(agg.first_ts),
        "lastCommit": _iso(agg.last_ts),
        "spanDays": days,
        "commitsPerDay": round(agg.commits / days, 3) if days else 0.0,
        "filesPerCommit": round(len(agg.files) / agg.commits, 3) if agg.commits else 0.0,
        "linesPerCommit": (
            round((agg.added + agg.deleted) / non_merge, 2) if non_merge else 0.0
        ),
        "percentOfScope": (
            round(100.0 * agg.commits / scoped_total, 2) if scoped_total else 0.0
        ),
        "selectedCommits": selected,
    }


def build_bundle(
    parsed: ParsedRepo,
    resolver: IdentityResolver,
    q: Query,
) -> dict:
    sel = select(parsed, resolver, q)
    agg = aggregate(parsed, resolver, sel)
    base_ts = agg.last_ts or 0

    files = []
    for pid, p in agg.path_agg.items():
        path = parsed.paths[pid]
        files.append({
            "path": path,
            "commits": p.commits,
            "linesAdded": p.added,
            "linesDeleted": p.deleted,
            "churn": p.added + p.deleted,
            "net": p.added - p.deleted,
            "authors": len(p.authors),
            "firstChange": _iso(p.first_ts),
            "lastChange": _iso(p.last_ts),
            "daysSinceChange": (
                (base_ts - p.last_ts) // 86400 if base_ts and p.last_ts else None
            ),
            "binary": pid in parsed.binary_paths,
            "name": path.rsplit("/", 1)[-1],
            "dir": parent_dirs(path)[-1] if "/" in path else "",
            "depth": path.count("/"),
        })
    files.sort(key=lambda f: (-f["churn"], -f["commits"], f["path"]))

    directories = [{
        "path": dpath,
        "commits": d.commits,
        "linesAdded": d.added,
        "linesDeleted": d.deleted,
        "churn": d.added + d.deleted,
        "net": d.added - d.deleted,
        "files": len(d.files),
        "authors": len(d.authors),
        "firstChange": _iso(d.first_ts),
        "lastChange": _iso(d.last_ts),
    } for dpath, d in agg.dir_agg.items()]
    directories.sort(key=lambda d: (-d["churn"], d["path"]))

    authors = [{
        "key": key,
        "name": a.name,
        "email": a.email,
        "commits": a.commits,
        "mergeCommits": a.merge_commits,
        "linesAdded": a.added,
        "linesDeleted": a.deleted,
        "churn": a.added + a.deleted,
        "net": a.added - a.deleted,
        "filesTouched": len(a.files),
        "firstCommit": _iso(a.first_ts),
        "lastCommit": _iso(a.last_ts),
        "aliases": resolver.aliases(key),
        "merged": resolver.is_merged(key),
        "commitShare": (
            round(100.0 * a.commits / agg.commits, 2) if agg.commits else 0.0
        ),
    } for key, a in agg.author_agg.items()]
    authors.sort(key=lambda a: (-a["commits"], a["name"]))

    timeseries = [{
        "date": d,
        "commits": v[0],
        "linesAdded": v[1],
        "linesDeleted": v[2],
        "churn": v[1] + v[2],
    } for d, v in sorted(agg.timeseries.items())]

    return {
        "filter": q.describe(),
        "metrics": _repo_metrics(agg, sel.scoped_total, len(sel.ids)),
        "scope": {
            "commitsInScope": sel.scoped_total,
            "commitsAfterFilter": len(sel.ids),
            "head": parsed.head,
            "branch": parsed.branch,
            "refs": parsed.refs,
            "mailmapPresent": parsed.mailmap_present,
            "totalPaths": len(parsed.paths),
            "totalCommitsParsed": len(parsed.commits),
        },
        "files": files,
        "directories": directories,
        "authors": authors,
        "timeseries": timeseries,
    }


# --------------------------------------------------------------------- #
# Commit listing (manual selection UI + commit drill-down)
# --------------------------------------------------------------------- #

def list_commits(
    parsed: ParsedRepo,
    resolver: IdentityResolver,
    q: Query,
    *,
    search: str | None = None,
    author: str | None = None,
    authors: list[str] | None = None,
    path: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    wanted = authors or ([author] if author else None)
    q = replace(q, authors=wanted, path=path or None)
    sel = select(parsed, resolver, q)

    needle = (search or "").strip().lower()
    ids = sel.ids
    if needle:
        ids = [
            i for i in ids
            if needle in parsed.commits[i].subject.lower()
            or parsed.commits[i].hash.startswith(needle)
        ]
    ids = sorted(ids, key=lambda i: parsed.commits[i].ts, reverse=True)
    total = len(ids)
    window = ids[offset: offset + limit]

    items = []
    for i in window:
        c = parsed.commits[i]
        key = resolver.key_for_commit(c.name, c.email)
        name, email = resolver.display(key)
        items.append({
            "hash": c.hash,
            "short": c.hash[:10],
            "authorKey": key,
            "author": name,
            "email": email,
            "date": c.date_iso,
            "subject": c.subject,
            "isMerge": c.is_merge,
            "filesChanged": len(c.files),
            "linesAdded": c.added,
            "linesDeleted": c.deleted,
            "churn": c.added + c.deleted,
        })
    return {"total": total, "offset": offset, "limit": limit, "commits": items}
