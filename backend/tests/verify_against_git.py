"""Cross-checks RAT metrics against independent raw `git` invocations.

This is the "trust but verify" harness used during development: it recomputes
the headline metrics a second time from plain `git log` text output (a
completely separate code path from the streaming parser) and diffs the two.

Usage:
    python3 tests/verify_against_git.py <path-to-repo> [<path-filter>]
"""
from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.identity import IdentityResolver  # noqa: E402
from app.metrics import Query, build_bundle  # noqa: E402
from app.parse import parse_repo  # noqa: E402


def raw_git_stats(repo: Path, path_filter: str | None = None):
    """Independent recomputation straight from `git log` text output.

    For a path filter we ask for `--full-history --no-merges`: the default
    `git log -- <path>` mode applies history simplification, which drops
    entire branches when a merge is TREESAME for the path. RAT instead
    reports every commit that actually touched the path, so the equivalent
    reference is the full history with merge commits (which carry no
    attributable line stats) excluded, exactly like RAT's path selection.
    """
    args = [
        "git", "-C", str(repo), "log", "HEAD", "--use-mailmap",
        "--no-renames", "--numstat", "--format=%x01%H%x02%aN%x02%aE",
    ]
    if path_filter:
        args += ["--full-history", "--no-merges", "--", path_filter]
    out = subprocess.run(args, capture_output=True, check=True).stdout
    text = out.decode("utf-8", "replace")

    commits = 0
    added = deleted = 0
    authors: set[tuple[str, str]] = set()
    files: set[str] = set()
    per_file: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    per_author: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    current: tuple[str, str] | None = None

    for line in text.splitlines():
        if line.startswith("\x01"):
            commits += 1
            parts = line[1:].split("\x02")
            current = (parts[1], parts[2]) if len(parts) >= 3 else ("", "")
            authors.add(current)
            per_author[current][0] += 1
        elif line and "\t" in line:
            a_s, d_s, path = line.split("\t", 2)
            if a_s == "-":
                a = d = 0
            else:
                a, d = int(a_s), int(d_s)
            added += a
            deleted += d
            files.add(path)
            per_file[path][0] += 1
            per_file[path][1] += a
            per_file[path][2] += d
            if current is not None:
                per_author[current][1] += a
                per_author[current][2] += d

    return {
        "commits": commits,
        "linesAdded": added,
        "linesDeleted": deleted,
        "authors": len(authors),
        "filesChanged": len(files),
        "per_file": per_file,
        "per_author": per_author,
    }


def main() -> int:
    repo = Path(sys.argv[1]).resolve()
    path_filter = sys.argv[2] if len(sys.argv) > 2 else None

    parsed = parse_repo(repo)
    resolver = IdentityResolver(parsed=parsed, groups=[], apply_mailmap=True)
    bundle = build_bundle(parsed, resolver, Query(scope="head", path=path_filter))
    got = bundle["metrics"]
    want = raw_git_stats(repo, path_filter)

    failures = 0

    def check(label: str, ours, theirs) -> None:
        nonlocal failures
        ok = ours == theirs
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'} {label}: rat={ours} git={theirs}")

    print(f"repo={repo.name} path={path_filter or '(all)'} "
          f"commits_parsed={len(parsed.commits)}")
    check("commits", got["commits"], want["commits"])
    check("linesAdded", got["linesAdded"], want["linesAdded"])
    check("linesDeleted", got["linesDeleted"], want["linesDeleted"])
    check("authors", got["authors"], want["authors"])
    check("filesChanged", got["filesChanged"], want["filesChanged"])

    # Per-file spot checks on the five most-churned files.
    ours_files = {f["path"]: f for f in bundle["files"]}
    top = sorted(want["per_file"].items(), key=lambda kv: -(kv[1][1] + kv[1][2]))[:5]
    for path, (n, a, d) in top:
        mine = ours_files.get(path)
        theirs = {"commits": n, "added": a, "deleted": d}
        got_row = ({"commits": mine["commits"], "added": mine["linesAdded"],
                    "deleted": mine["linesDeleted"]} if mine else None)
        ok = got_row == theirs
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'} file {path}: rat={got_row} git={theirs}")

    # Per-author spot checks on the five busiest authors.
    ours_authors = {a["key"]: a for a in bundle["authors"]}
    top_a = sorted(want["per_author"].items(), key=lambda kv: -kv[1][0])[:5]
    for (name, email), (n, a, d) in top_a:
        key = f"{name} <{email}>"
        mine = ours_authors.get(key)
        theirs = {"commits": n, "added": a, "deleted": d}
        got_row = ({"commits": mine["commits"], "added": mine["linesAdded"],
                    "deleted": mine["linesDeleted"]} if mine else None)
        ok = got_row == theirs
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'} author {key}: rat={got_row} git={theirs}")

    print(f"\n{'ALL CHECKS PASSED' if not failures else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
