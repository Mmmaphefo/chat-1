"""FastAPI application exposing the Repo Analysis Tool backend."""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, File, Form, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import ingest
from .config import FRONTEND_DIST, REPOS_DIR, ensure_dirs
from .identity import suggest_merges
from .ingest import IngestError
from .metrics import Query as FilterQuery, list_commits
from .store import RepoRecord, store


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_dirs()
    store.ensure_all_parsed()
    yield


app = FastAPI(title="Repo Analysis Tool", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------- #

@app.exception_handler(KeyError)
async def _not_found(_request, exc: KeyError):
    return JSONResponse(status_code=404,
                        content={"detail": f"Repository {exc.args[0]!r} not found"})


@app.exception_handler(RuntimeError)
async def _conflict(_request, exc: RuntimeError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(IngestError)
async def _bad_ingest(_request, exc: IngestError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def _bad_value(_request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# --------------------------------------------------------------------- #
# Repositories
# --------------------------------------------------------------------- #

@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/repos")
def list_repos() -> dict:
    records = store.list_records()
    for record in records:
        if record.status == "pending":
            store.ensure_parsed(record.id)
    return {"repos": [r.as_json(store.version(r.id)) for r in records]}


@app.get("/api/repos/{repo_id}")
def get_repo(repo_id: str) -> dict:
    record = store.get_record(repo_id)
    store.ensure_parsed(repo_id)
    return {"repo": record.as_json(store.version(repo_id))}


@app.post("/api/repos/upload")
def upload_repo(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
) -> dict:
    filename = file.filename or "upload.zip"
    display_name = (name or "").strip() or ingest.repo_name_from(filename)
    repo_id = ingest.new_repo_id(display_name)
    root = ingest.extract_zip(file.file, filename, repo_id)
    record = RepoRecord(
        id=repo_id,
        name=display_name,
        source="zip",
        url=None,
        path=str(root),
        created_at=time.time(),
        status="parsing",
        detail="Archive extracted, parsing…",
    )
    store.add_record(record)
    return {"repo": record.as_json(store.version(repo_id))}


@app.post("/api/repos/clone")
def clone_repo(payload: dict = Body(...)) -> dict:
    url = ingest.validate_clone_url(str(payload.get("url", "")))
    display_name = (str(payload.get("name") or "").strip()
                    or ingest.repo_name_from(url))
    repo_id = ingest.new_repo_id(display_name)
    record = RepoRecord(
        id=repo_id,
        name=display_name,
        source="clone",
        url=url,
        path=str(REPOS_DIR / repo_id),
        created_at=time.time(),
        status="cloning",
        detail="Cloning repository…",
    )
    store.add_record(record, start_parse=False)

    threading.Thread(
        target=_clone_job, args=(repo_id, url), daemon=True,
        name=f"rat-clone-{repo_id}",
    ).start()
    return {"repo": record.as_json(0)}


def _clone_job(repo_id: str, url: str) -> None:
    try:
        def progress(message: str) -> None:
            store.update_record(repo_id, detail=message)

        root = ingest.clone_repository(url, repo_id, on_progress=progress)
        store.update_record(repo_id, path=str(root), status="pending",
                            detail="Clone finished, parsing…")
        store.ensure_parsed(repo_id)
    except Exception as exc:  # noqa: BLE001
        store.update_record(repo_id, status="error",
                            error=str(exc)[:1000], detail="Clone failed")


@app.delete("/api/repos/{repo_id}")
def delete_repo(repo_id: str) -> dict:
    store.get_record(repo_id)
    store.delete_record(repo_id)
    return {"deleted": repo_id}


# --------------------------------------------------------------------- #
# Authors & merging
# --------------------------------------------------------------------- #

def _scope_query(scope: str, mailmap: bool) -> FilterQuery:
    return FilterQuery(scope="all" if scope == "all" else "head", mailmap=mailmap)


@app.get("/api/repos/{repo_id}/authors")
def get_authors(
    repo_id: str,
    scope: str = Query(default="head"),
    mailmap: bool = Query(default=True),
) -> dict:
    store.get_record(repo_id)
    store.ensure_parsed(repo_id)
    bundle = store.bundle(repo_id, mailmap, _scope_query(scope, mailmap))
    resolver = store.resolver(repo_id, mailmap)
    parsed = store.require_parsed(repo_id)
    record = store.get_record(repo_id)
    return {
        "authors": bundle["authors"],
        "suggestions": suggest_merges(parsed, resolver),
        "merges": [g for g in record.merges],
        "mailmapPresent": parsed.mailmap_present,
        "rawIdentities": len(parsed.raw_counts),
    }


@app.post("/api/repos/{repo_id}/merges")
def create_merge(
    repo_id: str,
    payload: dict = Body(...),
) -> dict:
    record = store.get_record(repo_id)
    parsed = store.require_parsed(repo_id)
    members = payload.get("members") or []
    if not isinstance(members, list) or len(members) < 2:
        raise ValueError("A merge group needs at least two identities")

    cleaned: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for member in members:
        name = str(member.get("name", ""))
        email = str(member.get("email", ""))
        key = (name, email)
        if key in seen:
            continue
        if key not in parsed.raw_counts:
            raise ValueError(f"Unknown identity: {name} <{email}>")
        seen.add(key)
        cleaned.append({"name": name, "email": email})
    if len(cleaned) < 2:
        raise ValueError("A merge group needs at least two distinct identities")

    already = {
        (m["name"], m["email"])
        for group in record.merges for m in group["members"]
    }
    overlap = [c for c in cleaned if (c["name"], c["email"]) in already]
    if overlap:
        raise ValueError(
            "Identities already merged: "
            + ", ".join(f"{m['name']} <{m['email']}>" for m in overlap)
        )

    group = {
        "id": uuid.uuid4().hex[:8],
        "label": (str(payload.get("label") or "").strip() or None),
        "members": cleaned,
    }
    store.update_record(repo_id, merges=[*record.merges, group])
    store.recount_authors(repo_id)
    return {"merge": group, "merges": store.get_record(repo_id).merges}


@app.delete("/api/repos/{repo_id}/merges/{group_id}")
def delete_merge(repo_id: str, group_id: str) -> dict:
    record = store.get_record(repo_id)
    remaining = [g for g in record.merges if g["id"] != group_id]
    if len(remaining) == len(record.merges):
        raise ValueError(f"Merge group {group_id} does not exist")
    store.update_record(repo_id, merges=remaining)
    store.recount_authors(repo_id)
    return {"merges": remaining}


# --------------------------------------------------------------------- #
# Metrics / commits / tree
# --------------------------------------------------------------------- #

@app.post("/api/repos/{repo_id}/metrics")
def metrics(repo_id: str, payload: dict | None = Body(default=None)) -> dict:
    store.get_record(repo_id)
    store.ensure_parsed(repo_id)
    q = FilterQuery.from_json(payload or {})
    return store.bundle(repo_id, q.mailmap, q)


@app.get("/api/repos/{repo_id}/commits")
def commits(
    repo_id: str,
    scope: str = Query(default="head"),
    mailmap: bool = Query(default=True),
    exclude_merges: bool = Query(default=False, alias="excludeMerges"),
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    authors: list[str] = Query(default=[], alias="author"),
    path: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    store.get_record(repo_id)
    store.ensure_parsed(repo_id)
    parsed = store.require_parsed(repo_id)
    resolver = store.resolver(repo_id, mailmap)
    base = FilterQuery(
        scope="all" if scope == "all" else "head",
        mailmap=mailmap,
        exclude_merges=exclude_merges,
        from_date=from_date,
        to_date=to_date,
    )
    result = list_commits(
        parsed, resolver, base, search=search, authors=authors or None, path=path,
        limit=limit, offset=offset,
    )
    return result | {"head": parsed.head, "branch": parsed.branch}


@app.get("/api/repos/{repo_id}/tree")
def tree(repo_id: str) -> dict:
    store.get_record(repo_id)
    store.ensure_parsed(repo_id)
    return {"tree": store.path_tree(repo_id)}


# --------------------------------------------------------------------- #
# Static frontend (production build)
# --------------------------------------------------------------------- #

if FRONTEND_DIST.is_dir():
    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = (FRONTEND_DIST / full_path).resolve()
        if (full_path
                and candidate.is_file()
                and FRONTEND_DIST.resolve() in candidate.parents):
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")


__all__ = ["app"]
