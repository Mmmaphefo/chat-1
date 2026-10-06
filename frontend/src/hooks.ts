import { useCallback, useEffect, useState } from "react";
import { api } from "./lib/api";
import type { RepoRecord, RepoStatus } from "./types";

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

const TRANSIENT: RepoStatus[] = ["cloning", "parsing", "pending"];
const POLL_MS = 2000;

/** Lists repositories, polling automatically while one is being ingested. */
export function useRepos() {
  const [repos, setRepos] = useState<RepoRecord[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.listRepos();
      setRepos(data.repos);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const busy = repos.some((repo) => TRANSIENT.includes(repo.status));
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy, refresh]);

  return { repos, loaded, error, refresh, busy };
}

/** Fetches a single repo record, polling while it is still being ingested. */
export function useRepo(id: string) {
  const [repo, setRepo] = useState<RepoRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.getRepo(id);
      setRepo(data.repo);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [id]);

  useEffect(() => {
    setRepo(null);
    void refresh();
  }, [refresh]);

  const busy = repo !== null && TRANSIENT.includes(repo.status);
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy, refresh]);

  return { repo, error, refresh };
}
