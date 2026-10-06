import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../lib/api";
import { errorMessage, useDebouncedValue, useRepo } from "../hooks";
import { compact, day, duration, int, pct, signed } from "../lib/format";
import type {
  AuthorsResponse,
  Bundle,
  CommitItem,
  CommitPage,
  FilterDescription,
  FilterQuery,
  TreeNode,
} from "../types";
import {
  ActivityChart,
  DirTreemap,
  LinesChart,
  RankBarChart,
  topAuthors,
  topFiles,
} from "../components/charts";
import { FilterBar } from "../components/FilterBar";
import { MergePanel } from "../components/MergePanel";
import { AuthorTable, CommitTable, DirTable, FileTable } from "../components/tables";
import {
  Card,
  EmptyState,
  ErrorNote,
  ShareBar,
  Spinner,
  Stat,
  StatusBadge,
} from "../components/ui";

type Tab = "overview" | "files" | "directories" | "authors" | "commits";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "files", label: "Files" },
  { id: "directories", label: "Directories" },
  { id: "authors", label: "Authors" },
  { id: "commits", label: "Commits" },
];

const PAGE_SIZE = 50;

function flattenTree(node: TreeNode, out: string[]) {
  for (const child of node.children) {
    // Directory paths already end with "/"; file paths do not.
    out.push(child.path);
    if (child.type === "dir") flattenTree(child, out);
  }
}

function queryFromParams(params: URLSearchParams): FilterQuery {
  const authors = params.getAll("author");
  return {
    scope: params.get("scope") === "all" ? "all" : "head",
    mailmap: params.get("mailmap") !== "0",
    excludeMerges: params.get("merges") === "0",
    path: params.get("path"),
    fromDate: params.get("from"),
    toDate: params.get("to"),
    authors: authors.length ? authors : null,
  };
}

function paramsFromQuery(query: FilterQuery, tab: Tab): URLSearchParams {
  const params = new URLSearchParams();
  if (query.scope === "all") params.set("scope", "all");
  if (query.mailmap === false) params.set("mailmap", "0");
  if (query.excludeMerges) params.set("merges", "0");
  if (query.path) params.set("path", query.path);
  if (query.fromDate) params.set("from", query.fromDate);
  if (query.toDate) params.set("to", query.toDate);
  (query.authors ?? []).forEach((author) => params.append("author", author));
  if (tab !== "overview") params.set("tab", tab);
  return params;
}

function describeFilter(filter: FilterDescription): string {
  const parts: string[] = [];
  if (filter.path) parts.push(`path ${filter.path}`);
  if (filter.authors?.length) {
    parts.push(`${filter.authors.length} author${filter.authors.length > 1 ? "s" : ""}`);
  }
  if (filter.fromDate || filter.toDate) {
    parts.push(`${filter.fromDate ?? "start"} → ${filter.toDate ?? "today"}`);
  }
  if (filter.commits?.length) {
    parts.push(`${filter.commits.length} selected commit${filter.commits.length > 1 ? "s" : ""}`);
  }
  if (filter.excludeMerges) parts.push("merges excluded");
  parts.push(filter.scope === "head" ? "HEAD scope" : "all refs");
  return parts.join(" · ");
}

function ComparisonTable({ base, current }: { base: Bundle | null; current: Bundle }) {
  if (!base) {
    return (
      <div className="py-10 text-center">
        <Spinner />
      </div>
    );
  }
  const rows: [string, number, number][] = [
    ["Commits", base.metrics.commits, current.metrics.commits],
    ["Authors", base.metrics.authors, current.metrics.authors],
    ["Lines added", base.metrics.linesAdded, current.metrics.linesAdded],
    ["Lines deleted", base.metrics.linesDeleted, current.metrics.linesDeleted],
    ["Churn", base.metrics.churn, current.metrics.churn],
    ["Files touched", base.metrics.filesChanged, current.metrics.filesChanged],
  ];
  return (
    <div>
      <table className="w-full">
        <thead>
          <tr className="border-b border-ink-700">
            <th className="th cursor-default">Metric</th>
            <th className="th cursor-default text-right">Repository</th>
            <th className="th cursor-default text-right">Commit set</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, all, part]) => (
            <tr key={label} className="border-b border-ink-800/60">
              <td className="td">{label}</td>
              <td className="td text-right tabular-nums text-slate-400">{compact(all)}</td>
              <td className="td text-right font-medium tabular-nums text-slate-100">
                {compact(part)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
          <span>commit-set share of the repository</span>
          <span className="tabular-nums text-slate-300">{pct(current.metrics.percentOfScope)}</span>
        </div>
        <ShareBar value={current.metrics.percentOfScope} max={100} />
      </div>
    </div>
  );
}

function Overview({
  bundle,
  base,
  onReset,
}: {
  bundle: Bundle;
  base: Bundle | null;
  onReset: () => void;
}) {
  const metrics = bundle.metrics;
  if (!metrics.commits) {
    return (
      <Card title="No commits selected">
        <EmptyState message="No commits match the current filters." />
        <div className="mt-3 text-center">
          <button className="btn" onClick={onReset}>
            Reset filters
          </button>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        <Stat
          label="Commits"
          value={compact(metrics.commits)}
          sub={metrics.mergeCommits ? `${int(metrics.mergeCommits)} merge commits` : "no merges"}
          accent
        />
        <Stat
          label="Authors"
          value={compact(metrics.authors)}
          sub={`${pct(metrics.percentOfScope)} of in-scope commits`}
        />
        <Stat
          label="Lines added"
          value={compact(metrics.linesAdded)}
          sub={metrics.linesPerCommit ? `${compact(metrics.linesPerCommit)} per commit` : ""}
        />
        <Stat
          label="Lines deleted"
          value={compact(metrics.linesDeleted)}
          sub={`net ${signed(metrics.net)}`}
        />
        <Stat
          label="Files touched"
          value={compact(metrics.filesChanged)}
          sub={metrics.binaryFilesChanged ? `${int(metrics.binaryFilesChanged)} binary` : "text only"}
        />
        <Stat
          label="Timespan"
          value={metrics.spanDays ? duration(metrics.spanDays) : "—"}
          sub={`${day(metrics.firstCommit)} → ${day(metrics.lastCommit)}`}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Activity" subtitle={describeFilter(bundle.filter)} className="xl:col-span-2">
          <ActivityChart points={bundle.timeseries} />
        </Card>
        <Card title="Repository vs commit set" subtitle="Same scope, full history vs current filter">
          <ComparisonTable base={base} current={bundle} />
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Lines added / deleted" subtitle="per time bucket">
          <LinesChart points={bundle.timeseries} />
        </Card>
        <Card title="Most volatile directories" subtitle="area = churn (added + deleted lines)">
          <DirTreemap directories={bundle.directories} />
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Top authors" subtitle="by commit count">
          <RankBarChart
            rows={topAuthors(bundle.authors, "commits", 10)}
            metric="commits"
            yLabel="commits"
          />
        </Card>
        <Card title="Hottest files" subtitle="by churn — open the Files tab to drill down">
          <RankBarChart rows={topFiles(bundle.files, "churn", 10)} metric="churn" yLabel="churn" />
        </Card>
      </div>

      <Card title="Commit set metrics" subtitle="Averages and pace for the current selection">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="Files per commit" value={metrics.filesPerCommit.toFixed(2)} />
          <Stat label="Lines per commit" value={compact(metrics.linesPerCommit)} />
          <Stat label="Commits per day" value={metrics.commitsPerDay.toFixed(2)} />
          <Stat
            label="Churn"
            value={compact(metrics.churn)}
            sub={`${pct(
              base && base.metrics.churn ? (metrics.churn / base.metrics.churn) * 100 : 100,
            )} of repository`}
          />
        </div>
      </Card>
    </div>
  );
}

export function RepoPage({ id }: { id: string }) {
  const { repo, error: repoError, refresh: refreshRepo } = useRepo(id);
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState<FilterQuery>(() => queryFromParams(params));
  const [tab, setTab] = useState<Tab>(() => {
    const value = params.get("tab");
    return TABS.some((item) => item.id === value) ? (value as Tab) : "overview";
  });

  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [baseBundle, setBaseBundle] = useState<Bundle | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authorsData, setAuthorsData] = useState<AuthorsResponse | null>(null);
  const [paths, setPaths] = useState<string[]>([]);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [selected, setSelected] = useState<Map<string, CommitItem>>(new Map());
  const [commitSearch, setCommitSearch] = useState("");
  const [commitOffset, setCommitOffset] = useState(0);
  const [commitPage, setCommitPage] = useState<CommitPage | null>(null);
  const [commitLoading, setCommitLoading] = useState(false);
  const debouncedSearch = useDebouncedValue(commitSearch, 300);

  const ready = repo?.status === "ready";
  const version = repo?.version ?? 0;

  // Keep the URL in sync so filters survive refreshes and can be shared.
  useEffect(() => {
    setParams(paramsFromQuery(query, tab), { replace: true });
  }, [query, tab, setParams]);

  const effectiveQuery = useMemo<FilterQuery>(
    () => ({ ...query, commits: selected.size ? [...selected.keys()] : null }),
    [query, selected],
  );
  const queryKey = JSON.stringify(effectiveQuery);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    setLoading(true);
    api
      .metrics(id, effectiveQuery)
      .then((data) => {
        if (cancelled) return;
        setBundle(data);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, ready, queryKey, version]);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    api
      .metrics(id, { scope: query.scope ?? "head", mailmap: query.mailmap ?? true })
      .then((data) => {
        if (!cancelled) setBaseBundle(data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [id, ready, query.scope, query.mailmap, version]);

  const refreshAuthors = useCallback(async () => {
    try {
      setAuthorsData(await api.authors(id, query.scope ?? "head", query.mailmap ?? true));
    } catch {
      /* surfaced through the metrics error banner */
    }
  }, [id, query.scope, query.mailmap]);

  useEffect(() => {
    if (ready) void refreshAuthors();
  }, [ready, refreshAuthors, version]);

  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    api
      .tree(id)
      .then(({ tree }) => {
        if (cancelled) return;
        const out: string[] = [];
        flattenTree(tree, out);
        setPaths(out);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [id, ready, version]);

  useEffect(() => {
    setCommitOffset(0);
  }, [
    debouncedSearch,
    tab,
    query.scope,
    query.mailmap,
    query.excludeMerges,
    query.fromDate,
    query.toDate,
    query.authors,
    query.path,
  ]);

  useEffect(() => {
    if (!ready || tab !== "commits") return;
    let cancelled = false;
    setCommitLoading(true);
    api
      .commits(id, {
        scope: query.scope ?? "head",
        mailmap: query.mailmap ?? true,
        excludeMerges: query.excludeMerges ?? false,
        from: query.fromDate ?? undefined,
        to: query.toDate ?? undefined,
        authors: query.authors ?? undefined,
        path: query.path ?? undefined,
        search: debouncedSearch || undefined,
        limit: PAGE_SIZE,
        offset: commitOffset,
      })
      .then((data) => {
        if (!cancelled) setCommitPage(data);
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err));
      })
      .finally(() => {
        if (!cancelled) setCommitLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    id,
    ready,
    tab,
    query.scope,
    query.mailmap,
    query.excludeMerges,
    query.fromDate,
    query.toDate,
    query.authors,
    query.path,
    debouncedSearch,
    commitOffset,
  ]);

  const patchQuery = (patch: Partial<FilterQuery>) =>
    setQuery((current) => ({ ...current, ...patch }));

  const resetQuery = () => {
    setQuery({ scope: "head", mailmap: true, excludeMerges: false });
    setSelected(new Map());
  };

  const toggleCommit = (item: CommitItem) => {
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(item.hash)) next.delete(item.hash);
      else next.set(item.hash, item);
      return next;
    });
  };

  const toggleMany = (items: CommitItem[], on: boolean) => {
    setSelected((current) => {
      const next = new Map(current);
      for (const item of items) {
        if (on) next.set(item.hash, item);
        else next.delete(item.hash);
      }
      return next;
    });
  };

  if (!repo) {
    return (
      <main className="mx-auto max-w-3xl px-4 py-20 text-center">
        {repoError ? <ErrorNote error={repoError} /> : <Spinner size={28} />}
      </main>
    );
  }

  if (!ready) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-16">
        <Card title={repo.name} subtitle="Ingestion in progress">
          {repo.status === "error" ? (
            <ErrorNote error={repo.error ?? "Ingestion failed"} />
          ) : (
            <div className="flex items-center gap-3 text-sm text-slate-400">
              <Spinner />
              <span>
                {repo.status} — {repo.detail || "working…"} this page refreshes automatically.
              </span>
            </div>
          )}
          <div className="mt-4 flex gap-2">
            <Link className="btn" to="/">
              ← All repositories
            </Link>
            <button className="btn" onClick={() => void refreshRepo()}>
              Refresh
            </button>
          </div>
        </Card>
      </main>
    );
  }

  const authorOptions = authorsData?.authors.map((author) => author.key) ?? [];

  return (
    <main className="mx-auto max-w-[1440px] px-4 py-5">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/" className="text-xs text-slate-500 hover:text-slate-300">
              Repositories
            </Link>
            <span className="text-xs text-slate-600">/</span>
            <h1 className="truncate text-lg font-semibold text-slate-100">{repo.name}</h1>
            <StatusBadge status={repo.status} detail={repo.detail} />
            {repo.mailmap_present && (
              <span className="chip border-accent/40 text-accent" title="Repository ships a .mailmap">
                .mailmap
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-slate-500">
            {repo.source === "clone" ? (
              <>
                cloned from <span className="font-mono">{repo.url}</span>
              </>
            ) : (
              "uploaded as a zip archive"
            )}
            {repo.branch && (
              <>
                {" "}
                · branch <span className="font-mono">{repo.branch}</span>
              </>
            )}
            {repo.head && (
              <>
                {" "}
                · head <span className="font-mono">{repo.head.slice(0, 10)}</span>
              </>
            )}
            {repo.parsed_at ? ` · parsed ${new Date(repo.parsed_at * 1000).toLocaleString()}` : ""}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            className="btn btn-primary"
            onClick={() => setMergeOpen(true)}
            disabled={!authorsData}
            title="Merge author identities (mailmap shown, manual merges applied)"
          >
            Merge authors
          </button>
          <button className="btn" onClick={() => void refreshRepo()}>
            Refresh
          </button>
        </div>
      </div>

      <FilterBar
        query={query}
        onChange={patchQuery}
        onReset={resetQuery}
        authorOptions={authorOptions}
        pathOptions={paths}
        scope={bundle?.scope ?? null}
        commitCount={selected.size}
        onOpenCommits={() => setTab("commits")}
        onClearCommits={() => setSelected(new Map())}
      />

      {error && (
        <div className="mb-4">
          <ErrorNote error={error} />
        </div>
      )}

      <div className="mb-4 flex items-center gap-1 border-b border-ink-700">
        {TABS.map((item) => (
          <button
            key={item.id}
            className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm transition ${
              tab === item.id
                ? "border-accent text-accent"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
            {item.id === "commits" && selected.size > 0 && (
              <span className="chip border-accent/40 text-accent">{selected.size}</span>
            )}
          </button>
        ))}
        {loading && (
          <span className="ml-2">
            <Spinner />
          </span>
        )}
      </div>

      {tab === "overview" &&
        (bundle ? (
          <Overview bundle={bundle} base={baseBundle} onReset={resetQuery} />
        ) : (
          <div className="py-20 text-center">
            <Spinner size={26} />
          </div>
        ))}

      {tab === "files" && bundle && (
        <Card
          title={`File metrics (${int(bundle.files.length)})`}
          subtitle="commits = volatility · click a path to filter every metric by it"
        >
          <FileTable files={bundle.files} onPickPath={(path) => patchQuery({ path })} />
        </Card>
      )}

      {tab === "directories" && bundle && (
        <Card
          title={`Directory metrics (${int(bundle.directories.length)})`}
          subtitle="line counts roll up the whole subtree · click a directory to filter"
        >
          <DirTable
            directories={bundle.directories}
            onPickPath={(path) => patchQuery({ path })}
          />
        </Card>
      )}

      {tab === "authors" && bundle && (
        <Card
          title={`Author metrics (${int(bundle.authors.length)})`}
          subtitle="click an author to filter · aliases shown as merged chips"
          actions={
            <button className="btn" onClick={() => setMergeOpen(true)} disabled={!authorsData}>
              Merge authors
            </button>
          }
        >
          <AuthorTable
            authors={bundle.authors}
            onPickAuthor={(key) => patchQuery({ authors: [key] })}
          />
        </Card>
      )}

      {tab === "commits" && (
        <Card
          title="Commits"
          subtitle="tick commits to restrict every metric to that manual selection"
          actions={
            selected.size > 0 ? (
              <button className="btn" onClick={() => setSelected(new Map())}>
                Clear selection ({selected.size})
              </button>
            ) : undefined
          }
        >
          <CommitTable
            page={commitPage}
            loading={commitLoading}
            selected={new Set(selected.keys())}
            onToggle={toggleCommit}
            onToggleMany={toggleMany}
            search={commitSearch}
            onSearch={setCommitSearch}
            offset={commitOffset}
            onOffset={setCommitOffset}
          />
        </Card>
      )}

      {mergeOpen && authorsData && (
        <MergePanel
          repoId={id}
          data={authorsData}
          onClose={() => setMergeOpen(false)}
          onChanged={async () => {
            await refreshAuthors();
            await refreshRepo();
          }}
        />
      )}
    </main>
  );
}
