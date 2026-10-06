"""Builds a deterministic fixture git repository used by unit tests.

The repository has a completely known history so every metric can be
asserted exactly.  Run it as a script to materialise the repo on disk:

    python3 backend/tests/make_fixture.py /tmp/rat-fixture
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# (date, author, email, message, {path: content-or-None-to-delete})
COMMITS: list[tuple[str, str, str, str, dict[str, str | None]]] = [
    ("2020-01-01T10:00:00+00:00", "Alice", "alice@example.com", "Initial import", {
        "README.md": "fixture\n",
        "src/main.c": "int main() { return 0; }\n",
    }),
    ("2020-01-02T11:30:00+00:00", "Bob", "bob@example.com", "Add utils", {
        "src/util.c": "int util(void) { return 1; }\n",
    }),
    ("2020-01-03T09:15:00+00:00", "Alice", "alice@work.com", "Extend main", {
        "src/main.c": "int main() {\n  return 1;\n}\n",  # +2/-1
    }),
    ("2020-01-05T16:45:00+00:00", "Charlie", "charlie@example.com", "Docs", {
        "docs/guide.md": "guide line 1\nguide line 2\nguide line 3\n",
    }),
    ("2020-02-01T08:00:00+00:00", "Alice", "alice@example.com", "Helper library", {
        "src/lib/helper.c": "int helper(void) { return 42; }\n",
        "src/lib/helper.h": "int helper(void);\n",
    }),
    ("2020-02-02T08:00:00+00:00", "Bob", "bob@example.com", "Binary asset", {
        "assets/logo.bin": "\x00\x01\x02binary\x00payload\x00",
    }),
    ("2020-02-03T08:00:00+00:00", "Bob", "bob@example.com", "Rewrite docs", {
        "docs/guide.md": "guide line 1\nrewritten\n",  # +1/-2
        "docs/faq.md": "faq\n",
    }),
    ("2020-03-01T12:00:00+00:00", "Alice", "alice@work.com", "Drop util", {
        "src/util.c": None,  # deleted, -1
    }),
    ("2020-03-02T12:00:00+00:00", "Charlie", "charlie@example.com", "Unicode file", {
        "docs/caf\u00e9.md": "caf\u00e9\n",
    }),
    ("2020-03-03T12:00:00+00:00", "Alice", "alice@example.com", "Merge prep on main", {
        "src/main.c": "int main() {\n  return 2;\n}\n",  # +1/-1
    }),
]

# A side branch merged back into master (adds one merge commit).
BRANCH_COMMIT = ("2020-02-15T10:00:00+00:00", "Bob", "bob@example.com", "Side work", {
    "src/side.c": "int side(void) { return 7; }\n",
})

MAILMAP = """\
Alice Smith <alice@example.com> <alice@work.com>
Alice Smith <alice@example.com>
"""


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True, env=full_env,
    )
    return out.stdout


def build_fixture(root: str | Path) -> Path:
    repo = Path(root)
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.com")
    _git(repo, "config", "commit.gpgsign", "false")

    # Side branch from commit #2, merged later (commit #11 = merge).
    side_created = False
    for i, (date, name, email, message, changes) in enumerate(COMMITS):
        env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date,
               "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email}
        if i == 7 and not side_created:
            _git(repo, "checkout", "-q", "-b", "side", "HEAD~4")
            _commit(repo, BRANCH_COMMIT, {
                "GIT_AUTHOR_DATE": BRANCH_COMMIT[0],
                "GIT_COMMITTER_DATE": BRANCH_COMMIT[0],
                "GIT_AUTHOR_NAME": BRANCH_COMMIT[1],
                "GIT_AUTHOR_EMAIL": BRANCH_COMMIT[2],
            })
            _git(repo, "checkout", "-q", "master")
            side_created = True
        _commit(repo, (date, name, email, message, changes), env)

    merge_env = {
        "GIT_AUTHOR_DATE": "2020-03-04T12:00:00+00:00",
        "GIT_COMMITTER_DATE": "2020-03-04T12:00:00+00:00",
        "GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": "alice@example.com",
    }
    full_env = os.environ.copy()
    full_env.update(merge_env)
    subprocess.run(
        ["git", "-C", str(repo), "merge", "-q", "--no-ff", "-m", "Merge side", "side"],
        check=True, capture_output=True, text=True, env=full_env,
    )

    (repo / ".mailmap").write_text(MAILMAP, encoding="utf-8")
    _git(repo, "add", ".mailmap")
    mm_env = {
        "GIT_AUTHOR_DATE": "2020-03-05T12:00:00+00:00",
        "GIT_COMMITTER_DATE": "2020-03-05T12:00:00+00:00",
        "GIT_AUTHOR_NAME": "Alice", "GIT_AUTHOR_EMAIL": "alice@example.com",
    }
    full_env = os.environ.copy()
    full_env.update(mm_env)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "Add mailmap"],
        check=True, capture_output=True, text=True, env=full_env,
    )

    # An abandoned branch that is NOT an ancestor of HEAD (scope "all" only).
    first_commit = _git(repo, "rev-list", "--max-parents=0", "HEAD").strip()
    _git(repo, "checkout", "-q", "-b", "abandoned", first_commit)
    _commit(repo, (
        "2020-04-01T10:00:00+00:00", "Dave", "dave@example.com",
        "Experimental spike", {"experimental/x.c": "int x(void) { return 9; }\n"},
    ), {
        "GIT_AUTHOR_DATE": "2020-04-01T10:00:00+00:00",
        "GIT_COMMITTER_DATE": "2020-04-01T10:00:00+00:00",
        "GIT_AUTHOR_NAME": "Dave", "GIT_AUTHOR_EMAIL": "dave@example.com",
    })
    _git(repo, "checkout", "-q", "master")
    return repo


def _commit(repo: Path, spec: tuple, env: dict[str, str]) -> None:
    _, _, _, message, changes = spec
    for path, content in changes.items():
        target = repo / path
        if content is None:
            if target.exists():
                _git(repo, "rm", "-q", "--", path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
        _git(repo, "add", "--", path)
    _git(repo, "commit", "-q", "-m", message, env=env)


if __name__ == "__main__":
    dest = build_fixture(sys.argv[1] if len(sys.argv) > 1 else "/tmp/rat-fixture")
    print(f"fixture repo created at {dest}")
