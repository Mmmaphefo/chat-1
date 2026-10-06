export type RepoStatus = "cloning" | "parsing" | "pending" | "ready" | "error";

export interface RepoRecord {
  id: string;
  name: string;
  source: "zip" | "clone";
  url: string | null;
  path: string;
  status: RepoStatus;
  detail: string;
  error: string | null;
  head: string | null;
  branch: string | null;
  commit_count: number | null;
  author_count: number | null;
  file_count: number | null;
  first_commit: string | null;
  last_commit: string | null;
  ref_count: number | null;
  mailmap_present: boolean;
  merges: MergeGroup[];
  parsed_at: number | null;
  version: number;
}

export interface RepoMetrics {
  commits: number;
  mergeCommits: number;
  authors: number;
  linesAdded: number;
  linesDeleted: number;
  churn: number;
  net: number;
  filesChanged: number;
  binaryFilesChanged: number;
  firstCommit: string | null;
  lastCommit: string | null;
  spanDays: number;
  commitsPerDay: number;
  filesPerCommit: number;
  linesPerCommit: number;
  percentOfScope: number;
  selectedCommits: number;
}

export interface FileMetric {
  path: string;
  name: string;
  dir: string;
  depth: number;
  commits: number;
  linesAdded: number;
  linesDeleted: number;
  churn: number;
  net: number;
  authors: number;
  firstChange: string | null;
  lastChange: string | null;
  daysSinceChange: number | null;
  binary: boolean;
}

export interface DirMetric {
  path: string;
  commits: number;
  linesAdded: number;
  linesDeleted: number;
  churn: number;
  net: number;
  files: number;
  authors: number;
  firstChange: string | null;
  lastChange: string | null;
}

export interface Alias {
  name: string;
  email: string;
  commits: number;
}

export interface AuthorMetric {
  key: string;
  name: string;
  email: string;
  commits: number;
  mergeCommits: number;
  linesAdded: number;
  linesDeleted: number;
  churn: number;
  net: number;
  filesTouched: number;
  firstCommit: string | null;
  lastCommit: string | null;
  aliases: Alias[];
  merged: boolean;
  commitShare: number;
}

export interface TimeseriesPoint {
  date: string;
  commits: number;
  linesAdded: number;
  linesDeleted: number;
  churn: number;
}

export interface ScopeInfo {
  commitsInScope: number;
  commitsAfterFilter: number;
  head: string;
  branch: string;
  refs: string[];
  mailmapPresent: boolean;
  totalPaths: number;
  totalCommitsParsed: number;
}

export interface FilterDescription {
  commits: string[] | null;
  fromDate: string | null;
  toDate: string | null;
  authors: string[] | null;
  path: string | null;
  scope: "head" | "all";
  mailmap: boolean;
  excludeMerges: boolean;
  isUnfiltered: boolean;
}

export interface Bundle {
  filter: FilterDescription;
  metrics: RepoMetrics;
  scope: ScopeInfo;
  files: FileMetric[];
  directories: DirMetric[];
  authors: AuthorMetric[];
  timeseries: TimeseriesPoint[];
}

export interface FilterQuery {
  commits?: string[] | null;
  fromDate?: string | null;
  toDate?: string | null;
  authors?: string[] | null;
  path?: string | null;
  scope?: "head" | "all";
  mailmap?: boolean;
  excludeMerges?: boolean;
}

export interface CommitItem {
  hash: string;
  short: string;
  authorKey: string;
  author: string;
  email: string;
  date: string;
  subject: string;
  isMerge: boolean;
  filesChanged: number;
  linesAdded: number;
  linesDeleted: number;
  churn: number;
}

export interface CommitPage {
  total: number;
  offset: number;
  limit: number;
  commits: CommitItem[];
  head: string;
  branch: string;
}

export interface TreeNode {
  name: string;
  path: string;
  type: "dir" | "file";
  files: number;
  children: TreeNode[];
}

export interface MergeGroup {
  id: string;
  label: string | null;
  members: { name: string; email: string }[];
}

export interface MergeSuggestion {
  reason: "name" | "email" | "local-part";
  detail: string;
  members: Alias[];
}

export interface AuthorsResponse {
  authors: AuthorMetric[];
  suggestions: MergeSuggestion[];
  merges: MergeGroup[];
  mailmapPresent: boolean;
  rawIdentities: number;
}

