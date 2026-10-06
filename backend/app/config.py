"""Central configuration for the RAT backend."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("RAT_DATA_DIR", str(BASE_DIR / "data")))

REPOS_DIR = DATA_DIR / "repos"
UPLOADS_DIR = DATA_DIR / "uploads"
CACHE_DIR = DATA_DIR / "cache"
REGISTRY_FILE = DATA_DIR / "registry.json"

# Ingestion limits (defensive guards for zip bombs / giant uploads).
MAX_UPLOAD_BYTES = 2 * 1024**3        # 2 GiB zip file
MAX_EXTRACTED_BYTES = 6 * 1024**3     # 6 GiB uncompressed
MAX_ZIP_ENTRIES = 300_000
CLONE_TIMEOUT_S = 3600                # deep clone of very large repos

# Frontend build output served in "production" mode.
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"


def ensure_dirs() -> None:
    for d in (DATA_DIR, REPOS_DIR, UPLOADS_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
