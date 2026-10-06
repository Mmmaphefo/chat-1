import { useEffect, useMemo, useRef, useState } from "react";
import type { FilterQuery, ScopeInfo } from "../types";

function useOutsideClose(onClose: () => void) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) onClose();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onClose]);
  return ref;
}

function MultiSelect({
  placeholder,
  options,
  selected,
  onChange,
}: {
  placeholder: string;
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useOutsideClose(() => setOpen(false));

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const list = needle
      ? options.filter((option) => option.toLowerCase().includes(needle))
      : options;
    return list.slice(0, 400);
  }, [options, search]);

  const toggle = (option: string) =>
    onChange(
      selected.includes(option)
        ? selected.filter((item) => item !== option)
        : [...selected, option],
    );

  return (
    <div className="relative" ref={ref}>
      <button
        className={`btn justify-between ${selected.length ? "btn-primary" : ""}`}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="max-w-40 truncate">
          {selected.length ? `${placeholder} (${selected.length})` : placeholder}
        </span>
        <span className="text-slate-500">▾</span>
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-80 rounded-lg border border-ink-600 bg-ink-900 p-2 shadow-2xl">
          <input
            autoFocus
            className="input w-full"
            placeholder="Search authors…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <div className="mt-2 max-h-64 overflow-auto">
            {filtered.map((option) => (
              <label
                key={option}
                className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-xs hover:bg-ink-800"
              >
                <input
                  type="checkbox"
                  className="accent-sky-400"
                  checked={selected.includes(option)}
                  onChange={() => toggle(option)}
                />
                <span className="truncate" title={option}>
                  {option}
                </span>
              </label>
            ))}
            {!filtered.length && (
              <div className="px-2 py-3 text-center text-xs text-slate-500">
                No matching authors
              </div>
            )}
          </div>
          {selected.length > 0 && (
            <button className="btn mt-2 w-full justify-center" onClick={() => onChange([])}>
              Clear selection
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function PathPicker({
  paths,
  value,
  onPick,
}: {
  paths: string[];
  value: string | null;
  onPick: (next: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useOutsideClose(() => setOpen(false));

  const suggestions = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const list = needle
      ? paths.filter((path) => path.toLowerCase().includes(needle))
      : paths;
    return list.slice(0, 200);
  }, [paths, search]);

  if (value) {
    return (
      <span className="chip h-[34px] gap-2 border-accent/40 bg-accent/10 px-2.5 text-accent">
        <span className="font-mono">{value}</span>
        <button onClick={() => onPick(null)} title="Clear path filter">
          ✕
        </button>
      </span>
    );
  }

  return (
    <div className="relative" ref={ref}>
      <button className="btn" onClick={() => setOpen((value) => !value)}>
        File or directory ▾
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-96 rounded-lg border border-ink-600 bg-ink-900 p-2 shadow-2xl">
          <input
            autoFocus
            className="input w-full"
            placeholder="Filter paths, e.g. src/ or src/main.c…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <div className="mt-2 max-h-64 overflow-auto">
            {suggestions.map((path) => (
              <button
                key={path}
                className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left font-mono text-xs text-slate-300 hover:bg-ink-800"
                onClick={() => {
                  onPick(path);
                  setOpen(false);
                  setSearch("");
                }}
              >
                {path}
              </button>
            ))}
            {!suggestions.length && (
              <div className="px-2 py-3 text-center text-xs text-slate-500">
                No matching paths
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
  title,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  title?: string;
}) {
  return (
    <label
      className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-400"
      title={title}
    >
      <input
        type="checkbox"
        className="accent-sky-400"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

export function FilterBar({
  query,
  onChange,
  onReset,
  authorOptions,
  pathOptions,
  scope,
  commitCount,
  onOpenCommits,
  onClearCommits,
}: {
  query: FilterQuery;
  onChange: (patch: Partial<FilterQuery>) => void;
  onReset: () => void;
  authorOptions: string[];
  pathOptions: string[];
  scope: ScopeInfo | null;
  commitCount: number;
  onOpenCommits: () => void;
  onClearCommits: () => void;
}) {
  const authors = query.authors ?? [];
  const mailmap = query.mailmap ?? true;
  const excludeMerges = query.excludeMerges ?? false;
  const dirty =
    Boolean(query.path) ||
    Boolean(query.fromDate) ||
    Boolean(query.toDate) ||
    authors.length > 0 ||
    excludeMerges ||
    !mailmap ||
    query.scope === "all" ||
    commitCount > 0;

  return (
    <div className="card mb-4 p-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="inline-flex overflow-hidden rounded-lg border border-ink-600">
          {(["head", "all"] as const).map((value) => (
            <button
              key={value}
              className={`px-3 py-1.5 text-xs font-medium transition ${
                (query.scope ?? "head") === value
                  ? "bg-accent/20 text-accent"
                  : "bg-ink-850 text-slate-400 hover:text-slate-200"
              }`}
              onClick={() => onChange({ scope: value })}
              title={
                value === "head"
                  ? "Only commits reachable from HEAD"
                  : "All commits across every branch and tag"
              }
            >
              {value === "head" ? "HEAD" : "All refs"}
            </button>
          ))}
        </div>

        <MultiSelect
          placeholder="Authors"
          options={authorOptions}
          selected={authors}
          onChange={(next) => onChange({ authors: next.length ? next : null })}
        />

        <PathPicker
          paths={pathOptions}
          value={query.path ?? null}
          onPick={(next) => onChange({ path: next })}
        />

        <div className="flex items-center gap-1.5">
          <input
            type="date"
            className="input"
            title="From date (inclusive)"
            value={query.fromDate ?? ""}
            onChange={(event) => onChange({ fromDate: event.target.value || null })}
          />
          <span className="text-xs text-slate-500">→</span>
          <input
            type="date"
            className="input"
            title="To date (inclusive)"
            value={query.toDate ?? ""}
            onChange={(event) => onChange({ toDate: event.target.value || null })}
          />
        </div>

        <button
          className={`btn ${commitCount ? "btn-primary" : ""}`}
          onClick={onOpenCommits}
          title="Pick an explicit list of commits to analyse"
        >
          Pick commits{commitCount ? ` (${commitCount})` : ""}
        </button>

        <Toggle
          label=".mailmap"
          checked={mailmap}
          onChange={(next) => onChange({ mailmap: next })}
          title="Resolve author identities through the repository's .mailmap"
        />
        <Toggle
          label="Exclude merges"
          checked={excludeMerges}
          onChange={(next) => onChange({ excludeMerges: next })}
          title="Drop merge commits from the commit set"
        />

        <button className="btn ml-auto" onClick={onReset} disabled={!dirty}>
          Reset filters
        </button>
      </div>

      {dirty && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-ink-700/60 pt-2">
          <span className="label">Active</span>
          {query.scope === "all" && (
            <span className="chip">
              all refs
              <button onClick={() => onChange({ scope: "head" })}>✕</button>
            </span>
          )}
          {query.path && (
            <span className="chip font-mono">
              {query.path}
              <button onClick={() => onChange({ path: null })}>✕</button>
            </span>
          )}
          {query.fromDate && (
            <span className="chip">
              from {query.fromDate}
              <button onClick={() => onChange({ fromDate: null })}>✕</button>
            </span>
          )}
          {query.toDate && (
            <span className="chip">
              to {query.toDate}
              <button onClick={() => onChange({ toDate: null })}>✕</button>
            </span>
          )}
          {authors.length > 0 && (
            <span className="chip">
              {authors.length} author{authors.length > 1 ? "s" : ""}
              <button onClick={() => onChange({ authors: null })}>✕</button>
            </span>
          )}
          {commitCount > 0 && (
            <span className="chip">
              {commitCount} selected commit{commitCount > 1 ? "s" : ""}
              <button onClick={onClearCommits}>✕</button>
            </span>
          )}
          {excludeMerges && (
            <span className="chip">
              merge commits excluded
              <button onClick={() => onChange({ excludeMerges: false })}>✕</button>
            </span>
          )}
          {!mailmap && (
            <span className="chip">
              .mailmap off
              <button onClick={() => onChange({ mailmap: true })}>✕</button>
            </span>
          )}
        </div>
      )}

      {scope && (
        <div className="mt-1.5 text-[11px] text-slate-500">
          commit set {scope.commitsAfterFilter.toLocaleString()} of{" "}
          {scope.commitsInScope.toLocaleString()} in scope ·{" "}
          {scope.totalCommitsParsed.toLocaleString()} parsed ·{" "}
          {scope.totalPaths.toLocaleString()} paths
          {scope.branch ? ` · branch ${scope.branch}` : ""}
        </div>
      )}
    </div>
  );
}
