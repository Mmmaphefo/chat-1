"""Thin wrappers around the git CLI.

All repository introspection goes through these helpers so that every git
invocation uses the same hardened environment (no prompting, no pager,
UTF-8 output, disabled signature display).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

_GIT_ENV_OVERRIDES = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "GIT_OPTIONAL_LOCKS": "0",
}

_BASE_CONFIG = [
    "-c", "log.showSignature=false",
    "-c", "i18n.logOutputEncoding=UTF-8",
    "-c", "core.quotepath=false",
]


def git_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(_GIT_ENV_OVERRIDES)
    return env


def run_git(
    repo: str | Path,
    *args: str,
    timeout: float | None = 120,
    check: bool = True,
) -> str:
    """Run `git -C <repo> <args>` and return decoded stdout."""
    cmd = ["git", "-C", str(repo), *_BASE_CONFIG, *args]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        env=git_env(),
    )
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {err}")
    return proc.stdout.decode("utf-8", "replace")


def git_version() -> str:
    return run_git(".", "--version", check=False).strip()
