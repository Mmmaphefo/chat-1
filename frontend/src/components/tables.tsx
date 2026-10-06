import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import type {
  AuthorMetric,
  CommitItem,
  CommitPage,
  DirMetric,
  FileMetric,
} from "../types";
import { compact, day, downloadCsv, int, pct, relativeDays, signed } from "../lib/format";
import { EmptyState, ShareBar, Spinner } from "./ui";

export interface Column<T> {
  key: string;
  label: string;
  align?: "left" | "right";
  sortValue?: (row: T) => number | string;
  render: (row: T) => ReactNode;
}

function DataTable<T>({
  columns,
  rows,
  initialSort,
  initialAsc = false,
  emptyText = "No data",
  csvName,
  csvRow,
  pageSize = 60,
}: {
  columns: Column<T>[];
  rows: T[];
  initialSort?: string;
  initialAsc?: boolean;
  emptyText?: string;
  csvName?: string;
  csvRow?: (row: T) => Record<string, unknown>;
  pageSize?: number;
}) {
  const [sortKey, setSortKey] = useState(initialSort ?? columns[0]?.key ?? "");
  const [asc, setAsc] = useState(initialAsc);
  const [limit, setLimit] = useState(pageSize);

  const sorted = useMemo(() => {
    const column = columns.find((item) => item.key === sortKey);
    if (!column?.sortValue) return rows;
    const factor = asc ? 1 : -1;
    return [...rows].sort((a, b) => {
      const left = column.sortValue!(a);
      const right = column.sortValue!(b);
      if (typeof left === "number" && typeof right === "number") {
        return (left - right) * factor;
      }
      return String(left).localeCompare(String(right)) * factor;
    });
  }, [rows, columns, sortKey, asc]);

  const toggleSort = (key: string) => {
    if (key === sortKey) {
      setAsc(!asc);
    } else {
      setSortKey(key);
      setAsc(false);
    }
  };

  if (!rows.length) {
    return <EmptyState message={emptyText} />;
  }

  const visible = sorted.slice(0, limit);

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-ink-700">
              {columns.map((column) => (
                <th
                  key={column.key}
                  className={`th ${column.align === "right" ? "text-right" : ""} ${
                    column.sortValue ? "" : "cursor-default"
                  }`}
                  onClick={() => column.sortValue && toggleSort(column.key)}
                >
                  {column.label}
                  {sortKey === column.key && (
                    <span className="ml-1 text-accent">{asc ? "↑" : "↓"}</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, index) => (
              <tr key={index} className="border-b border-ink-800/60 hover:bg-ink-800/40">
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={`td ${column.align === "right" ? "text-right" : ""}`}
                  >
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
        <span>
          showing {int(visible.length)} of {int(sorted.length)}
        </span>
        {visible.length < sorted.length && (
          <button className="btn px-2 py-1" onClick={() => setLimit(limit + pageSize * 2)}>
            Show more
          </button>
        )}
        {csvName && csvRow && (
          <button
            className="btn ml-auto px-2 py-1"
            onClick={() => downloadCsv(csvName, sorted.map(csvRow))}
            title="Download the full sorted table as CSV"
          >
            Export CSV
          </button>
        )}
      </div>
    </div>
  );
}

const added_ = (value: number) => (
  <span className="tabular-nums text-emerald-300">{compact(value)}</span>
);
const deleted_ = (value: number) => (
  <span className="tabular-nums text-rose-300">{compact(value)}</span>
);
const net_ = (value: number) => (
  <span className={`tabular-nums ${value >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
    {signed(value)}
  </span>
);

export function FileTable({
  files,
  onPickPath,
}: {
  files: FileMetric[];
  onPickPath: (path: string) => void;
}) {
  const columns: Column<FileMetric>[] = [
    {
      key: "path",
      label: "File",
      sortValue: (file) => file.path,
      render: (file) => (
        <div className="flex items-center gap-2">
          <button
            className="link max-w-[420px] truncate font-mono text-xs"
            onClick={() => onPickPath(file.path)}
            title={`Filter by ${file.path}`}
          >
            {file.path}
          </button>
          {file.binary && <span className="chip">binary</span>}
        </div>
      ),
    },
    {
      key: "commits",
      label: "Commits",
      align: "right",
      sortValue: (file) => file.commits,
      render: (file) => <span className="tabular-nums">{int(file.commits)}</span>,
    },
    {
      key: "linesAdded",
      label: "Added",
      align: "right",
      sortValue: (file) => file.linesAdded,
      render: (file) => added_(file.linesAdded),
    },
    {
      key: "linesDeleted",
      label: "Deleted",
      align: "right",
      sortValue: (file) => file.linesDeleted,
      render: (file) => deleted_(file.linesDeleted),
    },
    {
      key: "churn",
      label: "Churn",
      align: "right",
      sortValue: (file) => file.churn,
      render: (file) => <span className="tabular-nums">{int(file.churn)}</span>,
    },
    {
      key: "net",
      label: "Net",
      align: "right",
      sortValue: (file) => file.net,
      render: (file) => net_(file.net),
    },
    {
      key: "authors",
      label: "Authors",
      align: "right",
      sortValue: (file) => file.authors,
      render: (file) => int(file.authors),
    },
    {
      key: "lastChange",
      label: "Last change",
      align: "right",
      sortValue: (file) => file.lastChange ?? "",
      render: (file) => (
        <span title={day(file.lastChange)}>{relativeDays(file.daysSinceChange)}</span>
      ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      rows={files}
      initialSort="churn"
      emptyText="No file changes match the current filters"
      csvName="rat-files.csv"
      csvRow={(file) => ({
        path: file.path,
        commits: file.commits,
        linesAdded: file.linesAdded,
        linesDeleted: file.linesDeleted,
        churn: file.churn,
        net: file.net,
        authors: file.authors,
        binary: file.binary,
        firstChange: file.firstChange,
        lastChange: file.lastChange,
      })}
    />
  );
}

export function DirTable({
  directories,
  onPickPath,
}: {
  directories: DirMetric[];
  onPickPath: (path: string) => void;
}) {
  const columns: Column<DirMetric>[] = [
    {
      key: "path",
      label: "Directory",
      sortValue: (dir) => dir.path,
      render: (dir) =>
        dir.path ? (
          <button
            className="link font-mono text-xs"
            onClick={() => onPickPath(dir.path)}
            title={`Filter by ${dir.path}`}
          >
            {dir.path}
          </button>
        ) : (
          <span className="font-mono text-xs text-slate-400">(repository root)</span>
        ),
    },
    {
      key: "commits",
      label: "Commits",
      align: "right",
      sortValue: (dir) => dir.commits,
      render: (dir) => <span className="tabular-nums">{int(dir.commits)}</span>,
    },
    {
      key: "files",
      label: "Files",
      align: "right",
      sortValue: (dir) => dir.files,
      render: (dir) => int(dir.files),
    },
    {
      key: "linesAdded",
      label: "Added",
      align: "right",
      sortValue: (dir) => dir.linesAdded,
      render: (dir) => added_(dir.linesAdded),
    },
    {
      key: "linesDeleted",
      label: "Deleted",
      align: "right",
      sortValue: (dir) => dir.linesDeleted,
      render: (dir) => deleted_(dir.linesDeleted),
    },
    {
      key: "churn",
      label: "Churn",
      align: "right",
      sortValue: (dir) => dir.churn,
      render: (dir) => <span className="tabular-nums">{int(dir.churn)}</span>,
    },
    {
      key: "authors",
      label: "Authors",
      align: "right",
      sortValue: (dir) => dir.authors,
      render: (dir) => int(dir.authors),
    },
    {
      key: "lastChange",
      label: "Last change",
      align: "right",
      sortValue: (dir) => dir.lastChange ?? "",
      render: (dir) => <span title={day(dir.lastChange)}>{day(dir.lastChange)}</span>,
    },
  ];
  return (
    <DataTable
      columns={columns}
      rows={directories}
      initialSort="churn"
      emptyText="No directory changes match the current filters"
      csvName="rat-directories.csv"
      csvRow={(dir) => ({
        path: dir.path || "(root)",
        commits: dir.commits,
        files: dir.files,
        linesAdded: dir.linesAdded,
        linesDeleted: dir.linesDeleted,
        churn: dir.churn,
        net: dir.net,
        authors: dir.authors,
        firstChange: dir.firstChange,
        lastChange: dir.lastChange,
      })}
    />
  );
}

export function AuthorTable({
  authors,
  onPickAuthor,
}: {
  authors: AuthorMetric[];
  onPickAuthor: (key: string) => void;
}) {
  const maxCommits = useMemo(
    () => authors.reduce((max, author) => Math.max(max, author.commits), 0),
    [authors],
  );
  const columns: Column<AuthorMetric>[] = [
    {
      key: "name",
      label: "Author",
      sortValue: (author) => author.name.toLowerCase(),
      render: (author) => (
        <div className="flex items-center gap-2">
          <button
            className="link max-w-[220px] truncate"
            onClick={() => onPickAuthor(author.key)}
            title={`Filter by ${author.key}`}
          >
            {author.name}
          </button>
          {author.merged && (
            <span
              className="chip border-accent/40 text-accent"
              title={author.aliases
                .map((alias) => `${alias.name} <${alias.email}> · ${alias.commits}`)
                .join("\n")}
            >
              merged ×{author.aliases.length}
            </span>
          )}
        </div>
      ),
    },
    {
      key: "email",
      label: "Email",
      sortValue: (author) => author.email,
      render: (author) => (
        <span className="text-xs text-slate-400">{author.email || "—"}</span>
      ),
    },
    {
      key: "commits",
      label: "Commits",
      align: "right",
      sortValue: (author) => author.commits,
      render: (author) => (
        <div className="ml-auto w-28">
          <div className="flex items-baseline justify-between gap-2">
            <span className="tabular-nums">{int(author.commits)}</span>
            <span className="text-[10px] text-slate-500">{pct(author.commitShare)}</span>
          </div>
          <ShareBar value={author.commits} max={maxCommits} />
        </div>
      ),
    },
    {
      key: "linesAdded",
      label: "Added",
      align: "right",
      sortValue: (author) => author.linesAdded,
      render: (author) => added_(author.linesAdded),
    },
    {
      key: "linesDeleted",
      label: "Deleted",
      align: "right",
      sortValue: (author) => author.linesDeleted,
      render: (author) => deleted_(author.linesDeleted),
    },
    {
      key: "churn",
      label: "Churn",
      align: "right",
      sortValue: (author) => author.churn,
      render: (author) => <span className="tabular-nums">{int(author.churn)}</span>,
    },
    {
      key: "filesTouched",
      label: "Files",
      align: "right",
      sortValue: (author) => author.filesTouched,
      render: (author) => int(author.filesTouched),
    },
    {
      key: "first",
      label: "Active",
      align: "right",
      sortValue: (author) => author.firstCommit ?? "",
      render: (author) => (
        <span className="text-xs text-slate-400">
          {day(author.firstCommit)} → {day(author.lastCommit)}
        </span>
      ),
    },
  ];
  return (
    <DataTable
      columns={columns}
      rows={authors}
      initialSort="commits"
      emptyText="No authors match the current filters"
      csvName="rat-authors.csv"
      csvRow={(author) => ({
        name: author.name,
        email: author.email,
        commits: author.commits,
        mergeCommits: author.mergeCommits,
        linesAdded: author.linesAdded,
        linesDeleted: author.linesDeleted,
        churn: author.churn,
        net: author.net,
        filesTouched: author.filesTouched,
        commitShare: author.commitShare,
        merged: author.merged,
        aliases: author.aliases
          .map((alias) => `${alias.name} <${alias.email}>`)
          .join(" | "),
        firstCommit: author.firstCommit,
        lastCommit: author.lastCommit,
      })}
    />
  );
}

export function CommitTable({
  page,
  loading,
  selected,
  onToggle,
  onToggleMany,
  search,
  onSearch,
  offset,
  onOffset,
}: {
  page: CommitPage | null;
  loading: boolean;
  selected: Set<string>;
  onToggle: (item: CommitItem) => void;
  onToggleMany: (items: CommitItem[], on: boolean) => void;
  search: string;
  onSearch: (next: string) => void;
  offset: number;
  onOffset: (next: number) => void;
}) {
  const items = page?.commits ?? [];
  const limit = page?.limit ?? 50;
  const allOnPage = items.length > 0 && items.every((item) => selected.has(item.hash));

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <input
          className="input w-72"
          placeholder="Search subject or hash prefix…"
          value={search}
          onChange={(event) => onSearch(event.target.value)}
        />
        {loading && <Spinner />}
        <span className="text-xs text-slate-500">
          {page ? `${int(page.total)} commits` : ""}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            className="btn px-2 py-1"
            disabled={offset === 0 || loading}
            onClick={() => onOffset(Math.max(0, offset - limit))}
          >
            ← Newer
          </button>
          <button
            className="btn px-2 py-1"
            disabled={!page || offset + limit >= page.total || loading}
            onClick={() => onOffset(offset + limit)}
          >
            Older →
          </button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-ink-700">
              <th className="th w-8 cursor-default">
                <input
                  type="checkbox"
                  className="accent-sky-400"
                  checked={allOnPage}
                  onChange={() => onToggleMany(items, !allOnPage)}
                  title="Select every commit on this page"
                />
              </th>
              <th className="th cursor-default">Commit</th>
              <th className="th cursor-default">Date</th>
              <th className="th cursor-default">Author</th>
              <th className="th cursor-default">Subject</th>
              <th className="th cursor-default text-right">Files</th>
              <th className="th cursor-default text-right">+ / −</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.hash}
                className={`border-b border-ink-800/60 hover:bg-ink-800/40 ${
                  selected.has(item.hash) ? "bg-accent/10" : ""
                }`}
              >
                <td className="td">
                  <input
                    type="checkbox"
                    className="accent-sky-400"
                    checked={selected.has(item.hash)}
                    onChange={() => onToggle(item)}
                  />
                </td>
                <td className="td">
                  <span className="font-mono text-xs text-slate-400" title={item.hash}>
                    {item.short}
                  </span>
                  {item.isMerge && (
                    <span className="chip ml-2" title="Merge commit (no line stats)">
                      merge
                    </span>
                  )}
                </td>
                <td className="td text-xs">{day(item.date)}</td>
                <td className="td max-w-[180px] truncate" title={item.email}>
                  {item.author}
                </td>
                <td className="td max-w-[420px] truncate" title={item.subject}>
                  {item.subject}
                </td>
                <td className="td text-right tabular-nums">{int(item.filesChanged)}</td>
                <td className="td text-right text-xs tabular-nums">
                  <span className="text-emerald-300">+{compact(item.linesAdded)}</span>
                  {" / "}
                  <span className="text-rose-300">−{compact(item.linesDeleted)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!loading && !items.length && (
        <EmptyState message="No commits match the current filters" />
      )}

      <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
        <span>
          {page && page.total > 0
            ? `showing ${int(offset + 1)}–${int(Math.min(offset + limit, page.total))} of ${int(page.total)}`
            : ""}
        </span>
        {selected.size > 0 && (
          <span className="ml-auto text-accent">
            {int(selected.size)} commit{selected.size > 1 ? "s" : ""} selected — metrics follow the
            selection
          </span>
        )}
      </div>
    </div>
  );
}

