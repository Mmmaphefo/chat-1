"""HTTP-level smoke tests over the real FastAPI app.

These catch wiring bugs that pure metric unit tests cannot see: route
serialisation, background-parse bookkeeping (status must end up ``ready``),
the path-tree cache and the author merge/unmerge flow.

Run with:  cd backend && python3 -m pytest tests -q
"""
from __future__ import annotations

import io
import sys
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import CACHE_DIR  # noqa: E402
from app.main import app  # noqa: E402

from tests.make_fixture import build_fixture  # noqa: E402

# Raw identities as authored in the fixture (the .mailmap maps them to "Alice Smith").
ALICE_EXAMPLE = {"name": "Alice", "email": "alice@example.com"}
ALICE_WORK = {"name": "Alice", "email": "alice@work.com"}


def _zip_repo(repo_dir: Path) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(repo_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(repo_dir.parent))
    buffer.seek(0)
    return buffer


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:   # triggers the lifespan startup
        yield test_client


@pytest.fixture(scope="module")
def repo_id(client, tmp_path_factory):
    """Upload the fixture zip, wait for parsing, clean up afterwards."""
    repo_dir = build_fixture(tmp_path_factory.mktemp("api-fixture") / "repo")
    response = client.post(
        "/api/repos/upload",
        files={"file": ("fixture.zip", _zip_repo(repo_dir), "application/zip")},
        data={"name": "api-smoke"},
    )
    assert response.status_code == 200, response.text
    rid = response.json()["repo"]["id"]

    record: dict = {}
    deadline = time.time() + 60
    while time.time() < deadline:
        record = client.get(f"/api/repos/{rid}").json()["repo"]
        if record["status"] in ("ready", "error"):
            break
        time.sleep(0.25)
    assert record["status"] == "ready", record

    yield rid

    client.delete(f"/api/repos/{rid}")
    for stale in CACHE_DIR.glob(f"{rid}-*.pkl"):
        stale.unlink(missing_ok=True)


def test_record_counts(client, repo_id):
    record = client.get(f"/api/repos/{repo_id}").json()["repo"]
    assert record["commit_count"] == 14          # 13 on master + 1 abandoned branch
    assert record["author_count"] == 4           # Alice merged by .mailmap + Bob/Charlie/Dave
    assert record["file_count"] == 12
    assert record["ref_count"] >= 3
    assert record["mailmap_present"] is True
    assert record["branch"] == "master"


def test_metrics_bundle_and_path_filter(client, repo_id):
    bundle = client.post(f"/api/repos/{repo_id}/metrics", json={}).json()
    metrics = bundle["metrics"]
    assert metrics["commits"] == 13
    assert metrics["mergeCommits"] == 1
    assert (metrics["linesAdded"], metrics["linesDeleted"]) == (18, 5)
    assert (metrics["churn"], metrics["filesChanged"]) == (23, 11)
    assert metrics["binaryFilesChanged"] == 1
    assert len(bundle["files"]) == 11
    assert len(bundle["directories"]) == 5
    assert len(bundle["timeseries"]) == 13

    filtered = client.post(
        f"/api/repos/{repo_id}/metrics", json={"path": "src/"}
    ).json()["metrics"]
    assert filtered["commits"] == 7
    assert (filtered["linesAdded"], filtered["linesDeleted"]) == (9, 3)


def test_scope_all_and_raw_identities(client, repo_id):
    bundle = client.post(
        f"/api/repos/{repo_id}/metrics", json={"scope": "all", "mailmap": False}
    ).json()
    assert bundle["metrics"]["commits"] == 14
    assert bundle["metrics"]["authors"] == 5     # Alice's two raw emails stay apart

    head = client.post(
        f"/api/repos/{repo_id}/metrics", json={"scope": "head", "mailmap": False}
    ).json()
    assert head["metrics"]["authors"] == 4


def test_tree_and_commit_listing(client, repo_id):
    tree = client.get(f"/api/repos/{repo_id}/tree").json()["tree"]
    assert {"src", "docs", "assets"} <= {child["name"] for child in tree["children"]}

    page = client.get(f"/api/repos/{repo_id}/commits", params={"limit": 5}).json()
    assert page["total"] == 13
    assert len(page["commits"]) == 5
    assert page["branch"] == "master"

    rest = client.get(
        f"/api/repos/{repo_id}/commits", params={"limit": 50, "offset": 5}
    ).json()
    assert len(rest["commits"]) == 8

    found = client.get(
        f"/api/repos/{repo_id}/commits", params={"search": "util"}
    ).json()
    assert found["total"] == 2
    assert all("util" in item["subject"].lower() for item in found["commits"])


def test_author_merge_flow(client, repo_id):
    authors = client.get(
        f"/api/repos/{repo_id}/authors", params={"mailmap": False}
    ).json()
    keys = {author["key"] for author in authors["authors"]}
    assert {"Alice <alice@example.com>", "Alice <alice@work.com>",
            "Bob <bob@example.com>"} <= keys
    assert authors["mailmapPresent"] is True

    before = client.post(
        f"/api/repos/{repo_id}/metrics", json={"mailmap": False}
    ).json()["metrics"]["authors"]

    created = client.post(
        f"/api/repos/{repo_id}/merges",
        json={"members": [ALICE_EXAMPLE, ALICE_WORK], "label": "Alice"},
    ).json()
    merge_id = created["merge"]["id"]
    assert len(created["merges"]) == 1

    after = client.post(
        f"/api/repos/{repo_id}/metrics", json={"mailmap": False}
    ).json()["metrics"]["authors"]
    assert after == before - 1

    record = client.get(f"/api/repos/{repo_id}").json()["repo"]
    assert record["author_count"] == 4           # unchanged: mailmap already merged her

    # The same identities cannot be merged twice.
    duplicate = client.post(
        f"/api/repos/{repo_id}/merges",
        json={"members": [ALICE_EXAMPLE, ALICE_WORK]},
    )
    assert duplicate.status_code == 400

    removed = client.delete(f"/api/repos/{repo_id}/merges/{merge_id}").json()
    assert removed["merges"] == []
    restored = client.post(
        f"/api/repos/{repo_id}/metrics", json={"mailmap": False}
    ).json()["metrics"]["authors"]
    assert restored == before


def test_error_handling(client, repo_id):
    assert client.get("/api/repos/nope").status_code == 404
    bad_identity = client.post(
        f"/api/repos/{repo_id}/merges",
        json={"members": [{"name": "ghost", "email": "ghost@nowhere"}]},
    )
    assert bad_identity.status_code == 400
    assert client.delete(f"/api/repos/{repo_id}/merges/missing").status_code == 400
