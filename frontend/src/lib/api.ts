import type {
  AuthorsResponse,
  Bundle,
  CommitPage,
  FilterQuery,
  RepoRecord,
  TreeNode,
} from "../types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers:
      init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : undefined,
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : detail;
    } catch {
      /* keep the status text */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  listRepos: () => request<{ repos: RepoRecord[] }>("/api/repos"),

  getRepo: (id: string) => request<{ repo: RepoRecord }>(`/api/repos/${id}`),

  deleteRepo: (id: string) =>
    request<{ deleted: string }>(`/api/repos/${id}`, { method: "DELETE" }),

  cloneRepo: (url: string, name?: string) =>
    request<{ repo: RepoRecord }>("/api/repos/clone", {
      method: "POST",
      body: JSON.stringify({ url, name }),
    }),

  uploadRepo: (file: File, name?: string) => {
    const form = new FormData();
    form.append("file", file);
    if (name) form.append("name", name);
    return request<{ repo: RepoRecord }>("/api/repos/upload", {
      method: "POST",
      body: form,
    });
  },

  metrics: (id: string, query: FilterQuery) =>
    request<Bundle>(`/api/repos/${id}/metrics`, {
      method: "POST",
      body: JSON.stringify(query),
    }),

  authors: (id: string, scope: "head" | "all", mailmap: boolean) =>
    request<AuthorsResponse>(
      `/api/repos/${id}/authors?scope=${scope}&mailmap=${mailmap}`,
    ),

  commits: (
    id: string,
    params: {
      scope?: "head" | "all";
      mailmap?: boolean;
      excludeMerges?: boolean;
      from?: string;
      to?: string;
      authors?: string[];
      path?: string;
      search?: string;
      limit?: number;
      offset?: number;
    },
  ) => {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (key === "authors") {
        (value as string[] | undefined)?.forEach((author) =>
          search.append("author", author),
        );
        return;
      }
      if (value !== undefined && value !== null && value !== "") {
        search.set(key, String(value));
      }
    });
    return request<CommitPage>(`/api/repos/${id}/commits?${search.toString()}`);
  },

  tree: (id: string) => request<{ tree: TreeNode }>(`/api/repos/${id}/tree`),

  createMerge: (
    id: string,
    members: { name: string; email: string }[],
    label?: string,
  ) =>
    request<{ merges: RepoRecord["merges"] }>(`/api/repos/${id}/merges`, {
      method: "POST",
      body: JSON.stringify({ members, label }),
    }),

  deleteMerge: (id: string, groupId: string) =>
    request<{ merges: RepoRecord["merges"] }>(
      `/api/repos/${id}/merges/${groupId}`,
      { method: "DELETE" },
    ),
};
