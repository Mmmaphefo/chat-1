const COMPACT = new Intl.NumberFormat("en", {
  notation: "compact",
  maximumFractionDigits: 1,
});
const INT = new Intl.NumberFormat("en");

export function compact(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  if (Math.abs(n) < 1000) return INT.format(n);
  return COMPACT.format(n);
}

export function int(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return INT.format(n);
}

export function signed(n: number): string {
  return `${n > 0 ? "+" : ""}${compact(n)}`;
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  return iso.slice(0, 10);
}

export function relativeDays(days: number | null | undefined): string {
  if (days === null || days === undefined) return "—";
  if (days <= 0) return "today";
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.round(days / 30.4)}mo ago`;
  return `${(days / 365.25).toFixed(1)}y ago`;
}

export function duration(days: number): string {
  if (days < 90) return `${days} days`;
  if (days < 730) return `${(days / 30.4).toFixed(1)} months`;
  return `${(days / 365.25).toFixed(1)} years`;
}

export function pct(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`;
}

export type TimeseriesGranularity = "day" | "week" | "month";

export function autoGranularity(points: { date: string }[]): TimeseriesGranularity {
  if (points.length < 2) return "day";
  const first = new Date(points[0].date).getTime();
  const last = new Date(points[points.length - 1].date).getTime();
  const spanDays = (last - first) / 86_400_000;
  if (spanDays > 1200) return "month";
  if (spanDays > 180) return "week";
  return "day";
}

export interface Bucket {
  date: string;
  commits: number;
  linesAdded: number;
  linesDeleted: number;
  churn: number;
}

function bucketKey(date: string, granularity: TimeseriesGranularity): string {
  if (granularity === "day") return date;
  const d = new Date(date + "T00:00:00Z");
  if (granularity === "month") {
    return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-01`;
  }
  const dayOfWeek = (d.getUTCDay() + 6) % 7; // ISO: Monday = 0
  d.setUTCDate(d.getUTCDate() - dayOfWeek);
  return d.toISOString().slice(0, 10);
}

export function bucketize(
  points: { date: string; commits: number; linesAdded: number; linesDeleted: number; churn: number }[],
  granularity: TimeseriesGranularity,
): Bucket[] {
  const map = new Map<string, Bucket>();
  for (const p of points) {
    const key = bucketKey(p.date, granularity);
    const bucket = map.get(key) ?? {
      date: key,
      commits: 0,
      linesAdded: 0,
      linesDeleted: 0,
      churn: 0,
    };
    bucket.commits += p.commits;
    bucket.linesAdded += p.linesAdded;
    bucket.linesDeleted += p.linesDeleted;
    bucket.churn += p.churn;
    map.set(key, bucket);
  }
  return [...map.values()].sort((a, b) => a.date.localeCompare(b.date));
}

/** Fills gaps so line charts render continuous time axes. */
export function fillGaps(buckets: Bucket[], granularity: TimeseriesGranularity): Bucket[] {
  if (buckets.length < 2 || granularity === "day") return buckets;
  const out: Bucket[] = [];
  const stepMs = (granularity === "week" ? 7 : 30) * 86_400_000;
  let cursor = new Date(buckets[0].date + "T00:00:00Z").getTime();
  const end = new Date(buckets[buckets.length - 1].date + "T00:00:00Z").getTime();
  let i = 0;
  while (cursor <= end && out.length < 2000) {
    const iso = new Date(cursor).toISOString().slice(0, 10);
    const bucket = i < buckets.length && buckets[i].date === iso
      ? buckets[i++]
      : { date: iso, commits: 0, linesAdded: 0, linesDeleted: 0, churn: 0 };
    out.push(bucket);
    cursor += stepMs;
  }
  return out;
}

export function downloadCsv(filename: string, rows: Record<string, unknown>[]): void {
  if (!rows.length) return;
  const headers = Object.keys(rows[0]);
  const escape = (value: unknown) => {
    const s = value === null || value === undefined ? "" : String(value);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = [
    headers.join(","),
    ...rows.map((row) => headers.map((h) => escape(row[h])).join(",")),
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

