"""Unit tests asserting exact metric values on a deterministic fixture repo.

Run with:  cd backend && python3 -m pytest tests -q
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.identity import IdentityResolver, MergeGroup  # noqa: E402
from app.metrics import Query, build_bundle, list_commits  # noqa: E402
from app.parse import parse_repo  # noqa: E402

from tests.make_fixture import build_fixture  # noqa: E402

ALICE = "Alice Smith <alice@example.com>"
BOB = "Bob <bob@example.com>"
CHARLIE = "Charlie <charlie@example.com>"
DAVE = "Dave <dave@example.com>"


@pytest.fixture(scope="session")
def repo_path(tmp_path_factory) -> Path:
    return build_fixture(tmp_path_factory.mktemp("fixture") / "repo")


@pytest.fixture(scope="session")
def parsed(repo_path):
    return parse_repo(repo_path)


@pytest.fixture()
def mailmapped(parsed):
    return IdentityResolver(parsed=parsed, groups=[], apply_mailmap=True)


@pytest.fixture()
def raw(parsed):
    return IdentityResolver(parsed=parsed, groups=[], apply_mailmap=False)


def bundle(parsed, resolver, **kwargs):
    return build_bundle(parsed, resolver, Query(**kwargs))


# --------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------- #

def test_parse_counts(parsed):
    assert len(parsed.commits) == 14          # 13 on master + 1 abandoned
    assert len(parsed.head_reachable) == 14
    assert sum(parsed.head_reachable) == 13   # abandoned branch excluded
    assert parsed.mailmap_present is True
    assert len(parsed.paths) == 12
    assert parsed.branch == "master"
    assert any(r.endswith("abandoned") for r in parsed.refs)


def test_parse_binary_marked(parsed):
    pid = parsed.path_ids["assets/logo.bin"]
    assert pid in parsed.binary_paths


def test_unicode_and_weird_paths(parsed):
    assert "docs/caf\u00e9.md" in parsed.path_ids


# --------------------------------------------------------------------- #
# Repository metrics
# --------------------------------------------------------------------- #

def test_repo_metrics_head_scope(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head")
    m = b["metrics"]
    assert m["commits"] == 13
    assert m["mergeCommits"] == 1
    assert m["authors"] == 3
    assert m["linesAdded"] == 18
    assert m["linesDeleted"] == 5
    assert m["churn"] == 23
    assert m["net"] == 13
    assert m["filesChanged"] == 11
    assert m["binaryFilesChanged"] == 1
    assert m["firstCommit"] == "2020-01-01"
    assert m["lastCommit"] == "2020-03-05"


def test_repo_metrics_all_scope_includes_abandoned(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="all")
    m = b["metrics"]
    assert m["commits"] == 14
    assert m["authors"] == 4                  # Dave joins
    assert m["linesAdded"] == 19
    assert m["filesChanged"] == 12
    assert m["lastCommit"] == "2020-04-01"


def test_exclude_merges(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head", exclude_merges=True)
    assert b["metrics"]["commits"] == 12
    assert b["metrics"]["mergeCommits"] == 0


# --------------------------------------------------------------------- #
# File metrics
# --------------------------------------------------------------------- #

def test_file_metrics_for_single_file(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head", path="src/main.c")
    assert b["metrics"]["commits"] == 3
    assert b["metrics"]["linesAdded"] == 5
    assert b["metrics"]["linesDeleted"] == 2
    assert [f["path"] for f in b["files"]] == ["src/main.c"]
    f = b["files"][0]
    assert f["commits"] == 3
    assert f["authors"] == 1                  # all three are Alice (mailmapped)
    assert f["churn"] == 7
    assert f["binary"] is False


def test_binary_file_metrics(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head", path="assets/logo.bin")
    f = b["files"][0]
    assert f["binary"] is True
    assert f["linesAdded"] == 0 and f["linesDeleted"] == 0
    assert f["commits"] == 1


def test_file_table_is_sorted_by_churn(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head")
    churns = [f["churn"] for f in b["files"]]
    assert churns == sorted(churns, reverse=True)
    by_path = {f["path"]: f for f in b["files"]}
    assert by_path["src/main.c"]["churn"] == 7
    assert by_path["docs/guide.md"]["churn"] == 6
    assert by_path["src/util.c"]["commits"] == 2


# --------------------------------------------------------------------- #
# Directory metrics
# --------------------------------------------------------------------- #

def test_directory_metrics_src(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head", path="src/")
    dirs = {d["path"]: d for d in b["directories"]}
    assert dirs["src/"]["commits"] == 7
    assert dirs["src/"]["files"] == 5
    assert dirs["src/"]["linesAdded"] == 9
    assert dirs["src/"]["linesDeleted"] == 3
    assert dirs["src/"]["authors"] == 2
    assert dirs["src/lib/"]["commits"] == 1
    assert dirs["src/lib/"]["files"] == 2
    assert dirs["src/lib/"]["linesAdded"] == 2
    assert b["metrics"]["commits"] == 7       # commits touching src/
    assert all(f["path"].startswith("src/") for f in b["files"])


def test_directory_metrics_root_equals_repo(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head")
    dirs = {d["path"]: d for d in b["directories"]}
    # The root directory aggregates every file; the merge commit has no file
    # changes, so it does not count towards any directory's commit total.
    assert dirs[""]["commits"] == 12
    assert dirs[""]["linesAdded"] == 18
    assert dirs[""]["files"] == 11
    assert dirs["docs/"]["commits"] == 3
    assert dirs["docs/"]["files"] == 3
    assert dirs["assets/"]["linesAdded"] == 0


# --------------------------------------------------------------------- #
# Author metrics + merging
# --------------------------------------------------------------------- #

def test_author_metrics(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head")
    authors = {a["key"]: a for a in b["authors"]}
    assert set(authors) == {ALICE, BOB, CHARLIE}
    alice = authors[ALICE]
    assert alice["commits"] == 7
    assert alice["mergeCommits"] == 1
    assert alice["linesAdded"] == 10
    assert alice["linesDeleted"] == 3
    assert alice["filesTouched"] == 6
    assert alice["merged"] is True
    assert len(alice["aliases"]) == 2
    assert authors[BOB]["commits"] == 4
    assert authors[CHARLIE]["linesAdded"] == 4


def test_author_filter(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head", authors=[ALICE])
    assert b["metrics"]["commits"] == 7
    assert b["metrics"]["linesAdded"] == 10
    assert b["metrics"]["filesChanged"] == 6
    assert [a["key"] for a in b["authors"]] == [ALICE]


def test_mailmap_off_keeps_identities_separate(parsed, raw):
    b = bundle(parsed, raw, scope="head")
    authors = {a["key"]: a for a in b["authors"]}
    assert set(authors) == {
        "Alice <alice@example.com>", "Alice <alice@work.com>",
        BOB, CHARLIE,
    }
    assert authors["Alice <alice@example.com>"]["commits"] == 5
    assert authors["Alice <alice@work.com>"]["commits"] == 2


def test_manual_author_merge(parsed):
    resolver = IdentityResolver(
        parsed=parsed,
        groups=[MergeGroup(id="g1", label=None, members=[
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Alice", "email": "alice@work.com"},
        ])],
        apply_mailmap=False,
    )
    b = bundle(parsed, resolver, scope="head")
    authors = {a["key"]: a for a in b["authors"]}
    assert len(authors) == 3
    # canonical identity = member with the most commits
    assert "Alice <alice@example.com>" in authors
    assert authors["Alice <alice@example.com>"]["commits"] == 7
    assert len(authors["Alice <alice@example.com>"]["aliases"]) == 2


# --------------------------------------------------------------------- #
# Commit-set metrics
# --------------------------------------------------------------------- #

def test_date_range_filter(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head",
               from_date="2020-02-01", to_date="2020-02-29")
    m = b["metrics"]
    assert m["commits"] == 4                  # helper, binary, docs, side work
    assert m["linesAdded"] == 5
    assert m["linesDeleted"] == 2
    assert m["authors"] == 2                  # Alice + Bob


def test_manual_commit_selection(parsed, mailmapped):
    target = next(c for c in parsed.commits if c.subject == "Add utils")
    b = bundle(parsed, mailmapped, scope="head", commits=[target.hash[:8]])
    assert b["metrics"]["commits"] == 1
    assert b["metrics"]["linesAdded"] == 1
    assert [f["path"] for f in b["files"]] == ["src/util.c"]


def test_manual_selection_with_unknown_hash_is_empty(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head", commits=["deadbeef"])
    assert b["metrics"]["commits"] == 0
    assert b["files"] == []


def test_timeseries_totals_match(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head", authors=[BOB])
    assert sum(p["commits"] for p in b["timeseries"]) == 4
    assert sum(p["linesAdded"] for p in b["timeseries"]) == 4


def test_combined_filters(parsed, mailmapped):
    b = bundle(parsed, mailmapped, scope="head", path="docs/",
               authors=[CHARLIE])
    assert b["metrics"]["commits"] == 2
    assert b["metrics"]["linesAdded"] == 4
    assert sorted(f["path"] for f in b["files"]) == [
        "docs/caf\u00e9.md", "docs/guide.md"]


# --------------------------------------------------------------------- #
# Commit listing
# --------------------------------------------------------------------- #

def test_list_commits_order_and_pagination(parsed, mailmapped):
    page1 = list_commits(parsed, mailmapped, Query(scope="head"),
                         limit=5, offset=0)
    assert page1["total"] == 13
    assert len(page1["commits"]) == 5
    dates = [c["date"] for c in page1["commits"]]
    assert dates == sorted(dates, reverse=True)
    page3 = list_commits(parsed, mailmapped, Query(scope="head"),
                         limit=5, offset=10)
    assert len(page3["commits"]) == 3


def test_list_commits_search_and_path(parsed, mailmapped):
    hits = list_commits(parsed, mailmapped, Query(scope="head"),
                        search="utIl", limit=50)      # case-insensitive
    assert [c["subject"] for c in hits["commits"]] == ["Drop util", "Add utils"]
    by_path = list_commits(parsed, mailmapped, Query(scope="head"),
                           path="src/lib/", limit=50)
    assert by_path["total"] == 1
    assert by_path["commits"][0]["subject"] == "Helper library"
    assert by_path["commits"][0]["filesChanged"] == 2
