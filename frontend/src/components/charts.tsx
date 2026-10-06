import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
} from "recharts";
import type {
  AuthorMetric,
  DirMetric,
  FileMetric,
  TimeseriesPoint,
} from "../types";
import {
  autoGranularity,
  bucketize,
  compact,
  day,
  fillGaps,
} from "../lib/format";

export const PALETTE = [
  "#38bdf8", "#a78bfa", "#f472b6", "#34d399", "#fbbf24",
  "#f87171", "#22d3ee", "#c084fc", "#4ade80", "#fb923c",
];

const AXIS = { fill: "#64748b", fontSize: 11 };
const GRID = "#1f2b39";

function ChartTooltip({ active, payload, label, unit = "" }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-900/95 px-3 py-2 text-xs shadow-xl">
      <div className="mb-1 font-medium text-slate-200">{label}</div>
      {payload.map((entry: any) => (
        <div key={entry.dataKey} className="flex items-center gap-2 text-slate-400">
          <span
            className="inline-block h-2 w-2 rounded-sm"
            style={{ background: entry.color ?? entry.fill }}
          />
          <span>{entry.name}</span>
          <span className="ml-auto font-mono text-slate-200">
            {compact(entry.value)}
            {unit}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Commits over time (bars) with churn (line) on a twin axis. */
export function ActivityChart({ points }: { points: TimeseriesPoint[] }) {
  const granularity = autoGranularity(points);
  const data = fillGaps(bucketize(points, granularity), granularity);
  if (!data.length) {
    return <div className="py-16 text-center text-sm text-slate-500">No commits in this selection</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="churnFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f472b6" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#f472b6" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis
          dataKey="date"
          tick={AXIS}
          tickLine={false}
          axisLine={{ stroke: GRID }}
          minTickGap={28}
          tickFormatter={(value: string) =>
            granularity === "day" ? value.slice(2) : value.slice(0, 7)
          }
        />
        <YAxis yAxisId="left" tick={AXIS} tickLine={false} axisLine={false} width={44}
               tickFormatter={(v: number) => compact(v)} />
        <YAxis yAxisId="right" orientation="right" tick={AXIS} tickLine={false}
               axisLine={false} width={48} tickFormatter={(v: number) => compact(v)} />
        <Tooltip content={<ChartTooltip />} />
        <Bar yAxisId="left" dataKey="commits" name="Commits" fill="#38bdf8"
             fillOpacity={0.75} radius={[3, 3, 0, 0]} maxBarSize={26} />
        <Line yAxisId="right" type="monotone" dataKey="churn" name="Churn (lines)"
              stroke="#f472b6" strokeWidth={2} dot={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

export function LinesChart({ points }: { points: TimeseriesPoint[] }) {
  const granularity = autoGranularity(points);
  const data = fillGaps(bucketize(points, granularity), granularity);
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="addedFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#34d399" stopOpacity={0.5} />
            <stop offset="100%" stopColor="#34d399" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="deletedFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f87171" stopOpacity={0.5} />
            <stop offset="100%" stopColor="#f87171" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }}
               minTickGap={28}
               tickFormatter={(value: string) =>
                 granularity === "day" ? value.slice(2) : value.slice(0, 7)} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44}
               tickFormatter={(v: number) => compact(v)} />
        <Tooltip content={<ChartTooltip />} />
        <Area type="monotone" dataKey="linesAdded" name="Lines added" stroke="#34d399"
              fill="url(#addedFill)" strokeWidth={1.5} />
        <Area type="monotone" dataKey="linesDeleted" name="Lines deleted" stroke="#f87171"
              fill="url(#deletedFill)" strokeWidth={1.5} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** Horizontal ranking bars (authors / files). */
export function RankBarChart({
  rows,
  metric,
  yLabel,
}: {
  rows: { label: string; commits: number; churn: number; linesAdded: number; linesDeleted: number }[];
  metric: "commits" | "churn";
  yLabel: string;
}) {
  if (!rows.length) {
    return <div className="py-16 text-center text-sm text-slate-500">No data</div>;
  }
  const data = [...rows].sort((a, b) => b[metric] - a[metric]);
  const height = Math.max(180, data.length * 26 + 30);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 0 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" tick={AXIS} tickLine={false} axisLine={{ stroke: GRID }}
               tickFormatter={(v: number) => compact(v)} />
        <YAxis type="category" dataKey="label" tick={{ ...AXIS, fontSize: 11 }}
               tickLine={false} axisLine={false} width={190}
               tickFormatter={(value: string) =>
                 value.length > 26 ? `${value.slice(0, 25)}…` : value}
               label={{ value: yLabel, angle: -90, position: "insideLeft", fill: "#475569", fontSize: 10 }} />
        <Tooltip content={<ChartTooltip />} />
        <Bar dataKey={metric}
             name={metric === "commits" ? "Commits" : "Churn (lines)"}
             radius={[0, 3, 3, 0]} maxBarSize={16}>
          {data.map((_, index) => (
            <Cell key={index} fill={PALETTE[index % PALETTE.length]} fillOpacity={0.85} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function TreemapCell(props: any) {
  const { x, y, width, height, name, churn, depth, index } = props;
  if (width < 2 || height < 2) return null;
  const fill = PALETTE[index % PALETTE.length];
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} rx={4}
            style={{
              fill,
              fillOpacity: depth === 1 ? 0.32 : 0.55,
              stroke: "#0b0f14",
              strokeWidth: 1.5,
            }} />
      {width > 72 && height > 26 && (
        <text x={x + 8} y={y + 18} fill="#e2e8f0" fontSize={11} fontFamily="monospace">
          {String(name).length > Math.floor(width / 7)
            ? `${String(name).slice(0, Math.max(4, Math.floor(width / 7)))}…`
            : name}
        </text>
      )}
      {width > 72 && height > 42 && (
        <text x={x + 8} y={y + 33} fill="#94a3b8" fontSize={10}>
          {compact(churn)} lines
        </text>
      )}
    </g>
  );
}

/** Directory treemap: area = churn. Shallow paths aggregate nested dirs. */
export function DirTreemap({ directories }: { directories: DirMetric[] }) {
  const DEPTH = 2; // aggregate to the first two path segments for a readable map
  const grouped = new Map<string, { name: string; churn: number; commits: number; files: number }>();
  for (const dir of directories) {
    if (!dir.path) continue;
    const segments = dir.path.split("/").filter(Boolean);
    const key = segments.slice(0, DEPTH).join("/") + (segments.length > DEPTH ? "/" : "/");
    // Only leaf-level rows contribute (their parents would double count).
    if (segments.length > DEPTH) continue;
    const existing = grouped.get(key) ?? { name: key, churn: 0, commits: 0, files: 0 };
    existing.churn += dir.churn;
    existing.commits += dir.commits;
    existing.files += dir.files;
    grouped.set(key, existing);
  }
  const data = [...grouped.values()].sort((a, b) => b.churn - a.churn).slice(0, 40);
  if (!data.length) {
    return <div className="py-16 text-center text-sm text-slate-500">No directories</div>;
  }
  return (
    <ResponsiveContainer width="100%" height={300}>
      <Treemap data={data} dataKey="churn" nameKey="name" aspectRatio={4 / 3}
               content={<TreemapCell />} animationDuration={250}>
        <Tooltip
          content={({ active, payload }: any) => {
            if (!active || !payload?.length) return null;
            const item = payload[0]?.payload;
            return (
              <div className="rounded-lg border border-ink-600 bg-ink-900/95 px-3 py-2 text-xs shadow-xl">
                <div className="font-mono text-slate-200">{item?.name}</div>
                <div className="mt-1 text-slate-400">
                  churn <span className="font-mono text-slate-200">{compact(item?.churn)}</span>
                  {" · "}commits <span className="font-mono text-slate-200">{compact(item?.commits)}</span>
                  {" · "}files <span className="font-mono text-slate-200">{compact(item?.files)}</span>
                </div>
              </div>
            );
          }}
        />
      </Treemap>
    </ResponsiveContainer>
  );
}

export function topFiles(rows: FileMetric[], metric: "commits" | "churn", limit = 12) {
  return [...rows]
    .sort((a, b) => b[metric] - a[metric])
    .slice(0, limit)
    .map((f) => ({
      label: f.path,
      commits: f.commits,
      churn: f.churn,
      linesAdded: f.linesAdded,
      linesDeleted: f.linesDeleted,
    }));
}

export function topAuthors(rows: AuthorMetric[], metric: "commits" | "churn", limit = 12) {
  return [...rows]
    .sort((a, b) => b[metric] - a[metric])
    .slice(0, limit)
    .map((a) => ({
      label: a.name,
      commits: a.commits,
      churn: a.churn,
      linesAdded: a.linesAdded,
      linesDeleted: a.linesDeleted,
    }));
}

export { day };

