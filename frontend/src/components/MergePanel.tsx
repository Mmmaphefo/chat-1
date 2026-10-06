import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { errorMessage } from "../hooks";
import { int } from "../lib/format";
import type { Alias, AuthorsResponse } from "../types";
import { ErrorNote, Modal, Spinner } from "./ui";

interface Member {
  name: string;
  email: string;
  commits?: number;
}

function MemberChips({ members }: { members: Member[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {members.map((member) => (
        <span
          key={`${member.name}\u0000${member.email}`}
          className="chip font-mono"
          title={member.email}
        >
          {member.name} &lt;{member.email}&gt;
          {member.commits !== undefined && (
            <span className="text-slate-500">· {int(member.commits)}</span>
          )}
        </span>
      ))}
    </div>
  );
}

const REASONS: Record<string, string> = {
  name: "same name",
  email: "same email",
  "local-part": "same email local-part",
};

export function MergePanel({
  repoId,
  data,
  onClose,
  onChanged,
}: {
  repoId: string;
  data: AuthorsResponse;
  onClose: () => void;
  onChanged: () => void | Promise<void>;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [search, setSearch] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const rawIdentities = useMemo(() => {
    const map = new Map<string, Alias>();
    for (const author of data.authors) {
      for (const alias of author.aliases) {
        const key = `${alias.name}\u0000${alias.email}`;
        const existing = map.get(key);
        if (!existing || alias.commits > existing.commits) map.set(key, alias);
      }
    }
    return [...map.values()].sort((a, b) => b.commits - a.commits);
  }, [data]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const list = needle
      ? rawIdentities.filter((raw) =>
          `${raw.name} <${raw.email}>`.toLowerCase().includes(needle),
        )
      : rawIdentities;
    return list.slice(0, 250);
  }, [rawIdentities, search]);

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const mergeMembers = (members: Member[], groupLabel?: string) =>
    run(() =>
      api.createMerge(
        repoId,
        members.map((member) => ({ name: member.name, email: member.email })),
        groupLabel,
      ),
    );

  const toggle = (raw: Alias) => {
    const key = `${raw.name}\u0000${raw.email}`;
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
  };

  const selectedMembers = rawIdentities.filter((raw) =>
    selected.has(`${raw.name}\u0000${raw.email}`),
  );

  return (
    <Modal open onClose={onClose} title="Author identities" wide>
      <div className="space-y-5">
        <div className="rounded-lg border border-ink-600 bg-ink-850 px-3 py-2 text-xs text-slate-400">
          {data.mailmapPresent ? (
            <>
              This repository ships a <span className="font-mono">.mailmap</span> — identities
              are resolved through it automatically while the{" "}
              <span className="font-mono">.mailmap</span> toggle is on. Any merge created here
              takes precedence over the mailmap.
            </>
          ) : (
            <>
              No <span className="font-mono">.mailmap</span> found in this repository. Use the
              suggestions or merge identities manually below.
            </>
          )}{" "}
          <span className="text-slate-500">
            {int(data.rawIdentities)} raw identities · {int(data.authors.length)} effective
            authors
          </span>
        </div>

        <ErrorNote error={error} />

        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-200">
            Merged identities ({data.merges.length})
          </h3>
          {data.merges.length === 0 ? (
            <p className="text-xs text-slate-500">
              No manual merges yet — identities map 1:1 through the mailmap.
            </p>
          ) : (
            <ul className="space-y-2">
              {data.merges.map((group) => (
                <li
                  key={group.id}
                  className="flex items-start justify-between gap-3 rounded-lg border border-ink-700 bg-ink-850/60 p-2.5"
                >
                  <div className="min-w-0">
                    <div className="mb-1 text-xs font-medium text-slate-300">
                      {group.label ?? `Group ${group.id}`}
                    </div>
                    <MemberChips members={group.members} />
                  </div>
                  <button
                    className="btn btn-danger shrink-0 px-2 py-1"
                    disabled={busy}
                    onClick={() => run(() => api.deleteMerge(repoId, group.id))}
                  >
                    Unmerge
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-200">
            Suggested merges ({data.suggestions.length})
          </h3>
          {data.suggestions.length === 0 ? (
            <p className="text-xs text-slate-500">
              Nothing looks suspicious — no duplicated names or email local-parts.
            </p>
          ) : (
            <ul className="space-y-2">
              {data.suggestions.map((suggestion) => (
                <li
                  key={`${suggestion.reason}:${suggestion.detail}`}
                  className="flex items-start justify-between gap-3 rounded-lg border border-ink-700 bg-ink-850/60 p-2.5"
                >
                  <div className="min-w-0">
                    <div className="mb-1 flex items-center gap-2">
                      <span className="chip border-amber-500/40 text-amber-300">
                        {REASONS[suggestion.reason] ?? suggestion.reason}
                      </span>
                      <span className="truncate font-mono text-[11px] text-slate-500">
                        {suggestion.detail}
                      </span>
                    </div>
                    <MemberChips members={suggestion.members} />
                  </div>
                  <button
                    className="btn shrink-0 px-2 py-1"
                    disabled={busy}
                    onClick={() => mergeMembers(suggestion.members)}
                  >
                    Merge
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h3 className="mb-2 text-sm font-semibold text-slate-200">Merge manually</h3>
          <div className="flex flex-wrap items-center gap-2">
            <input
              className="input w-64"
              placeholder="Search raw identities…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <input
              className="input w-52"
              placeholder="Optional label (e.g. real name)"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
            <button
              className="btn btn-primary"
              disabled={busy || selectedMembers.length < 2}
              onClick={() =>
                mergeMembers(selectedMembers, label.trim() || undefined).then(() => {
                  setSelected(new Set());
                  setLabel("");
                })
              }
            >
              {busy && <Spinner size={12} />}
              Merge {selectedMembers.length || ""} selected
            </button>
            {selected.size > 0 && (
              <button className="btn" onClick={() => setSelected(new Set())}>
                Clear
              </button>
            )}
          </div>
          <div className="mt-2 max-h-64 overflow-auto rounded-lg border border-ink-700">
            {filtered.map((raw) => {
              const key = `${raw.name}\u0000${raw.email}`;
              return (
                <label
                  key={key}
                  className="flex cursor-pointer items-center gap-2 border-b border-ink-800/60 px-2.5 py-1.5 text-xs hover:bg-ink-800/50"
                >
                  <input
                    type="checkbox"
                    className="accent-sky-400"
                    checked={selected.has(key)}
                    onChange={() => toggle(raw)}
                  />
                  <span className="font-mono text-slate-300">
                    {raw.name} &lt;{raw.email}&gt;
                  </span>
                  <span className="ml-auto tabular-nums text-slate-500">
                    {int(raw.commits)} commits
                  </span>
                </label>
              );
            })}
            {!filtered.length && (
              <div className="px-2 py-4 text-center text-xs text-slate-500">
                No identities match
              </div>
            )}
          </div>
          <p className="mt-1.5 text-[11px] text-slate-500">
            The identity with the most commits becomes the canonical author of the group.
          </p>
        </section>
      </div>
    </Modal>
  );
}
