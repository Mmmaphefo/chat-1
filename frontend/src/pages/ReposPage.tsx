import { useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import { errorMessage, useRepos } from "../hooks";
import { compact, day } from "../lib/format";
import type { RepoRecord } from "../types";
import { Card, EmptyState, ErrorNote, Modal, Spinner, StatusBadge } from "../components/ui";

function hostOf(url: string | null): string {
  if (!url) return "remote";
  const match = url.match(/^(?:[a-z+]+:\/\/)?(?:[^@/]+@)?([^:/]+)/i);
  return match?.[1] ?? "remote";
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-ink-700 bg-ink-850/60 px-2 py-1.5">
      <div className="text-sm font-semibold tabular-nums text-slate-100">{value}</div>
      <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}

function RepoCard({
  repo,
  onDelete,
}: {
  repo: RepoRecord;
  onDelete: (repo: RepoRecord) => void;
}) {
  const ready = repo.status === "ready";
  return (
    <div className="card-pad flex flex-col gap-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <Link
            to={`/repos/${repo.id}`}
            className="link block truncate text-base font-semibold"
            title={repo.name}
          >
            {repo.name}
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
            <span className="chip">
              {repo.source === "zip" ? "zip upload" : hostOf(repo.url)}
            </span>
            {repo.branch && <span className="font-mono">{repo.branch}</span>}
            {repo.head && <span className="font-mono">{repo.head.slice(0, 10)}</span>}
          </div>
        </div>
        <StatusBadge status={repo.status} detail={repo.detail} />
      </div>

      {ready ? (
        <>
          <div className="grid grid-cols-3 gap-2 text-center">
            <MiniStat label="commits" value={compact(repo.commit_count ?? 0)} />
            <MiniStat label="authors" value={compact(repo.author_count ?? 0)} />
            <MiniStat label="files" value={compact(repo.file_count ?? 0)} />
          </div>
          <div className="text-[11px] text-slate-500">
            {day(repo.first_commit)} → {day(repo.last_commit)}
            {repo.mailmap_present && <span className="text-accent"> · .mailmap</span>}
            {repo.merges.length > 0 && ` · ${repo.merges.length} merged group(s)`}
            {repo.ref_count ? ` · ${repo.ref_count} refs` : ""}
          </div>
        </>
      ) : repo.status === "error" ? (
        <ErrorNote error={repo.error ?? "Ingestion failed"} />
      ) : (
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <Spinner />
          {repo.detail || "Working…"}
        </div>
      )}

      <div className="mt-auto flex items-center gap-2">
        <Link to={`/repos/${repo.id}`} className={`btn ${ready ? "btn-primary" : ""}`}>
          {ready ? "Open dashboard" : "View progress"}
        </Link>
        <button
          className="btn btn-danger ml-auto px-2 py-1"
          onClick={() => onDelete(repo)}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

export function ReposPage() {
  const { repos, loaded, error, refresh, busy } = useRepos();
  const [mode, setMode] = useState<"clone" | "zip">("clone");
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<RepoRecord | null>(null);
  const [deleting, setDeleting] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      if (mode === "clone") {
        if (!url.trim()) throw new Error("Enter a repository URL");
        await api.cloneRepo(url.trim(), name.trim() || undefined);
      } else {
        if (!file) throw new Error("Choose a .zip archive containing .git");
        await api.uploadRepo(file, name.trim() || undefined);
      }
      setUrl("");
      setName("");
      setFile(null);
      await refresh();
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api.deleteRepo(pendingDelete.id);
      setPendingDelete(null);
      await refresh();
    } catch (err) {
      setFormError(errorMessage(err));
      setPendingDelete(null);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <main className="mx-auto max-w-[1440px] px-4 py-6">
      <div className="mb-4 flex items-center gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Repositories</h1>
          <p className="mt-0.5 text-xs text-slate-500">
            Upload a zip archive of a repository (including its <span className="font-mono">.git</span>)
            or clone a remote URL. Every repository gets its own dashboard.
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {busy && <Spinner />}
          <button className="btn" onClick={() => void refresh()}>
            Refresh
          </button>
        </div>
      </div>

      <Card
        title="Add a repository"
        subtitle={
          mode === "clone"
            ? "Bare-clones every branch and tag, then parses the full history."
            : "Extracts the archive, finds .git, then parses the full history."
        }
        className="mb-5"
      >
        <div className="mb-3 inline-flex overflow-hidden rounded-lg border border-ink-600">
          {(["clone", "zip"] as const).map((value) => (
            <button
              key={value}
              className={`px-3 py-1.5 text-xs font-medium transition ${
                mode === value
                  ? "bg-accent/20 text-accent"
                  : "bg-ink-850 text-slate-400 hover:text-slate-200"
              }`}
              onClick={() => setMode(value)}
            >
              {value === "clone" ? "Clone URL" : "Upload zip"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
          {mode === "clone" ? (
            <input
              className="input w-[420px]"
              placeholder="https://github.com/org/repo.git"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
            />
          ) : (
            <label className="btn cursor-pointer">
              <input
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
              {file ? file.name : "Choose .zip archive…"}
            </label>
          )}
          <input
            className="input w-56"
            placeholder="Display name (optional)"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button className="btn btn-primary" disabled={submitting}>
            {submitting && <Spinner size={12} />}
            {mode === "clone" ? "Clone repository" : "Upload repository"}
          </button>
        </form>
        <div className="mt-2">
          <ErrorNote error={formError} />
        </div>
      </Card>

      {error && <div className="mb-4"><ErrorNote error={error} /></div>}

      {!loaded ? (
        <div className="py-20 text-center">
          <Spinner size={26} />
        </div>
      ) : repos.length === 0 ? (
        <EmptyState message="No repositories yet — clone a URL or upload a zip to get started." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {repos.map((repo) => (
            <RepoCard key={repo.id} repo={repo} onDelete={setPendingDelete} />
          ))}
        </div>
      )}

      <Modal
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title="Delete repository"
      >
        <p className="text-sm text-slate-300">
          Delete <span className="font-semibold">{pendingDelete?.name}</span> and its local
          clone/upload, plus any parsed caches? This cannot be undone.
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <button className="btn" onClick={() => setPendingDelete(null)}>
            Cancel
          </button>
          <button className="btn btn-danger" disabled={deleting} onClick={() => void confirmDelete()}>
            {deleting && <Spinner size={12} />}
            Delete repository
          </button>
        </div>
      </Modal>
    </main>
  );
}
