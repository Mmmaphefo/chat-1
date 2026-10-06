"""Repository ingestion: zip archives and remote clones."""
from __future__ import annotations

import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

from .config import (
    CLONE_TIMEOUT_S,
    MAX_EXTRACTED_BYTES,
    MAX_UPLOAD_BYTES,
    MAX_ZIP_ENTRIES,
    REPOS_DIR,
)
from .gitio import git_env

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")

_ALLOWED_URL_PREFIXES = ("https://", "http://", "git://", "ssh://")
_SCP_LIKE_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:")


class IngestError(Exception):
    """Raised when a repository cannot be ingested."""


def new_repo_id(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip()).strip("-.").lower() or "repo"
    return f"{slug[:48]}-{uuid.uuid4().hex[:6]}"


def repo_name_from(filename_or_url: str) -> str:
    base = filename_or_url.rstrip("/").rsplit("/", 1)[-1]
    for suffix in (".zip", ".tar", ".git"):
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
    return base or "repository"


def validate_clone_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise IngestError("Clone URL must not be empty")
    if url.startswith(_ALLOWED_URL_PREFIXES) or _SCP_LIKE_RE.match(url):
        return url
    raise IngestError(
        "Only remote URLs are accepted (https://, http://, git://, ssh://, "
        "or user@host:path)"
    )


# --------------------------------------------------------------------- #
# Zip ingestion
# --------------------------------------------------------------------- #

def _safe_zip_path(member: str, dest: Path) -> Path | None:
    """Return a safe extraction target, or None for unsafe members."""
    name = member.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or not parts:
        return None
    return dest.joinpath(*parts)


def extract_zip(file_obj, filename: str, repo_id: str) -> Path:
    """Extract an uploaded zip and return the repository root."""
    if not filename.lower().endswith(".zip"):
        raise IngestError("Only .zip archives are supported for upload")
    file_obj.seek(0)
    if not zipfile.is_zipfile(file_obj):
        raise IngestError("Uploaded file is not a valid zip archive")
    file_obj.seek(0)

    dest = REPOS_DIR / repo_id
    dest.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with zipfile.ZipFile(file_obj) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise IngestError(f"Archive has too many entries ({len(infos)})")
            for info in infos:
                target = _safe_zip_path(info.filename, dest)
                if target is None:
                    continue
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                total += info.file_size
                if total > MAX_EXTRACTED_BYTES:
                    raise IngestError("Archive exceeds the extraction size limit")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, length=1 << 20)
    except zipfile.BadZipFile as exc:
        raise IngestError(f"Corrupt zip archive: {exc}") from exc

    root = find_repo_root(dest)
    probe_repository(root)
    return root


def find_repo_root(base: Path, max_depth: int = 8) -> Path:
    """Locate the repository inside an extracted archive."""
    # 1. A `.git` entry (directory or file) directly at the top level.
    direct = _repo_root_from_git_entry(base)
    if direct is not None:
        return direct

    # 2. Search breadth-first for the shallowest `.git` entry.
    candidates: list[Path] = [base]
    for _depth in range(max_depth):
        next_level: list[Path] = []
        for parent in candidates:
            for child in sorted(parent.iterdir()):
                if not child.is_dir() or child.name == ".git":
                    continue
                found = _repo_root_from_git_entry(child)
                if found is not None:
                    return found
                next_level.append(child)
        if not next_level:
            break
        candidates = next_level

    # 3. A bare repository (HEAD + objects + refs) extracted at the top level.
    if (base / "HEAD").is_file() and (base / "objects").is_dir():
        return base

    raise IngestError(
        "No .git directory or file found in the archive — the upload must "
        "contain the repository including its git metadata"
    )


def _repo_root_from_git_entry(candidate: Path) -> Path | None:
    git_entry = candidate / ".git"
    if git_entry.is_dir():
        return candidate
    if git_entry.is_file():
        # A `.git` file points at the real git dir (worktrees/submodules).
        try:
            content = git_entry.read_text("utf-8", "replace").strip()
        except OSError:
            return None
        if content.lower().startswith("gitdir:"):
            target = content.split(":", 1)[1].strip()
            resolved = (candidate / target).resolve()
            if resolved.is_dir():
                return candidate
            # The pointer may be dangling after extraction; the git dir does
            # not exist inside the archive, so the repo cannot be opened.
            raise IngestError(
                "The .git file points to '" + target + "' which is not part "
                "of the uploaded archive; upload a full clone instead of a "
                "worktree checkout"
            )
    return None


# --------------------------------------------------------------------- #
# Clone ingestion
# --------------------------------------------------------------------- #

def clone_repository(url: str, repo_id: str, on_progress=None) -> Path:
    """Deep (full history) bare clone of a remote repository."""
    validate_clone_url(url)
    dest = REPOS_DIR / repo_id
    if dest.exists():
        raise IngestError(f"Destination {dest} already exists")
    dest.mkdir(parents=True)
    if on_progress is not None:
        on_progress(f"Cloning {url} …")
    cmd = [
        "git", "clone", "--bare", "--quiet", url, str(dest),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, env=git_env(),
        timeout=CLONE_TIMEOUT_S,
    )
    if proc.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise IngestError(
            "git clone failed: " + (proc.stderr or proc.stdout).strip()[:500]
        )
    probe_repository(dest)
    return dest


def probe_repository(root: Path) -> None:
    """Verify that a directory is a usable git repository with history."""
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, env=git_env(), timeout=120,
        )

    check = git("rev-parse", "--git-dir")
    if check.returncode != 0:
        raise IngestError(
            "Directory is not a git repository: "
            + (check.stderr or "").strip()[:300]
        )
    count = git("rev-list", "--count", "--all")
    raw = (count.stdout or "").strip()
    if count.returncode != 0 or not raw.isdigit() or int(raw) == 0:
        raise IngestError("Repository contains no commits to analyse")


__all__ = [
    "IngestError",
    "MAX_UPLOAD_BYTES",
    "clone_repository",
    "extract_zip",
    "find_repo_root",
    "new_repo_id",
    "probe_repository",
    "repo_name_from",
    "validate_clone_url",
]
