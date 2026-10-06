# RAT- Repo Analysis Tool

A web dashboard that measures how a git repository evolved: who had the most impact
where, and which parts of the project are the most volatile.

It accepts repositories as **zip archives** (containing `.git`) or by **cloning a
remote URL**, supports **multiple repositories**, resolves author identities through
**`.mailmap`** and lets you **merge authors manually**, and reports metrics for

- the **repository** as a whole,
- every **author**,
- every **file**,
- every **directory** (subtree roll-up), and
- any **commit set** (time period, manual commit selection, author/path filters).

## Quick start

```bash
./run.sh              # installs deps, builds the frontend, serves everything on :8000
```

Then open <http://127.0.0.1:8000> and either paste a clone URL
(e.g. `https://github.com/DaveGamble/cJSON.git`) or upload a zip of a repo.

Development mode (two processes, hot reload):

```bash
# terminal 1 — API on :8000
cd backend && python3 -m uvicorn app.main:app --reload

# terminal 2 — Vite dev server on :5173 (proxies /api to :8000)
cd frontend && npm install && npm run dev
```

Tests and the metric cross-check harness:

```bash
cd backend
python3 -m pytest tests/test_metrics.py -q          # 22 deterministic fixture tests
python3 tests/verify_against_git.py <repo-path> [path-filter]   # diff vs raw git
```

## Metric definitions

All metrics are computed over a **commit set** — the intersection of the active
filters (scope, date range, authors, path, explicit commit list, merge toggle).

| Metric | Definition |
| --- | --- |
| `commits` | commits in the set (merge commits included unless excluded) |
| `mergeCommits` | of those, commits with ≥ 2 parents |
| `authors` | distinct effective author identities in the set |
| `linesAdded` / `linesDeleted` | sum over file stats of the set |
| `churn` | `linesAdded + linesDeleted` — the volatility measure |
| `net` | `linesAdded − linesDeleted` |
| `filesChanged` | distinct files touched (binaries counted, with no line stats) |
| `spanDays`, `commitsPerDay` | time span of the set and pace |
| `filesPerCommit`, `linesPerCommit` | averages per commit |
| `percentOfScope` | share of the scope's commits that are in the set |

**Per file:** commit count (= *volatility*), added/deleted/churn/net lines, distinct
authors, first/last change, days since last change, binary flag.
**Per directory:** all of the above rolled up over the whole subtree, plus file count.
**Per author:** commits (merge commits tracked separately), added/deleted/churn/net,
distinct files touched, first/last commit, alias list, share of the set's commits.
**Timeseries:** commits and line counts bucketed by author-local date.

### Semantics worth knowing

- **Merge commits** count as commits but contribute no file/line stats (git prints
  no `--numstat` for them). Consequently a directory's commit count covers
  file-touching commits only, while the repository's covers merges too.
- **Path filter** selects *every commit that touched the path* and restricts line
  stats to that path — equivalent to
  `git log --full-history --no-merges --numstat -- <path>`. Git's default
  `git log -- <path>` applies history simplification and hides commits, so it is
  deliberately *not* the reference definition.
- **Directory** filters use a trailing slash (`src/` = subtree); a bare file path
  matches the file exactly (plus the same-named subtree union).
- **Scope**: `HEAD` walks only commits reachable from HEAD (`git log HEAD`);
  `All refs` includes every branch and tag (`git log --all`).
- **Author identity resolution order**: manual merge group (canonical member = the
  one with the most commits) → mailmap (`%aN`/`%aE`, applied by git itself) → raw
  `%an`/`%ae`. Turning the `.mailmap` toggle off exposes the raw identities so they
  can still be merged manually.
- **Manual commit selection** restricts the set to exactly the ticked commits
  (intersected with the other filters).

## Architecture

```
backend/
  app/
    config.py     paths, limits, env overrides
    gitio.py      hardened git CLI wrappers (no prompts, stable encoding)
    parse.py      one streaming `git log --all --use-mailmap --numstat -z` pass
    identity.py   identity resolution, merge groups, merge suggestions
    metrics.py    selection (bitmask) + single-pass aggregation + bundling
    ingest.py     zip extraction (zip-slip safe), clone, repo probing
    store.py      registry, background parsing, LRU + persisted parse cache
    main.py       FastAPI routes + static frontend
frontend/
  src/            React + TypeScript + Tailwind + Recharts dashboard
```

**Efficiency.** Ingestion runs one `git log` walk and parses its NUL-separated
stream in ~0.2 s of Python overhead on top of git's own diff time. A query is a
`bytearray` mask over commits plus one O(#commits) aggregation pass — no diffs are
recomputed per query. Parsed repos are cached to
`data/cache/<repo-id>-<token>.pkl` (validated by a signature over HEAD, refs and
mailmap) and reload in milliseconds, so restarts are instant; bundles, resolvers
and path trees live in LRU caches. Cloning and parsing happen in background
threads, and the UI polls status while they run.

Measured on this machine: redis (13 319 HEAD commits, 20 937 with all refs) parses
in ~12.6 s (git alone: ~12.4 s), the pickle cache loads in 0.06 s, an unfiltered
bundle computes in 0.06 s and filtered queries in 0.01–0.02 s.

**Correctness.** 22 fixture tests pin the expected numbers of a purpose-built repo.
`tests/verify_against_git.py` recomputes the headline metrics from plain
`git log` text (a fully independent code path) and diffs them:
cJSON passes all checks (1 113 commits, +46 932/−11 766, 109 authors, 250 files),
redis passes all checks both unfiltered and filtered to `src/`.

## API

| Method & path | Purpose |
| --- | --- |
| `GET /api/repos` | list repositories (status, counts, merges) |
| `GET /api/repos/{id}` | single repository record |
| `POST /api/repos/upload` | multipart zip upload (`file`, optional `name`) |
| `POST /api/repos/clone` | JSON `{url, name?}` → bare clone of all refs |
| `DELETE /api/repos/{id}` | remove a repository and its data |
| `POST /api/repos/{id}/metrics` | filter query → full metrics bundle |
| `GET /api/repos/{id}/commits` | paginated/searchable commit list (filters too) |
| `GET /api/repos/{id}/authors` | effective authors, merge suggestions, groups |
| `POST /api/repos/{id}/merges` | create a manual merge group |
| `DELETE /api/repos/{id}/merges/{gid}` | dissolve a merge group |
| `GET /api/repos/{id}/tree` | repo path tree (for the path picker) |

## Notes

- Data lives in `data/` (override with `RAT_DATA_DIR`); delete a repo from the UI
  to reclaim space.
- Zip uploads are guarded against path traversal and oversized archives.
- Clone URLs must be `http(s)`, `git`, `ssh` or scp-like; local paths are refused.
