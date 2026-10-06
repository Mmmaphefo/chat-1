import type { ReactNode } from "react";
import { useEffect } from "react";
import type { RepoStatus } from "../types";

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      className="inline-block animate-spin rounded-full border-2 border-ink-600 border-t-accent"
      style={{ width: size, height: size }}
    />
  );
}

const STATUS_STYLES: Record<RepoStatus, string> = {
  ready: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  parsing: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  cloning: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  pending: "border-slate-500/40 bg-slate-500/10 text-slate-300",
  error: "border-rose-500/40 bg-rose-500/10 text-rose-300",
};

export function StatusBadge({ status, detail }: { status: RepoStatus; detail?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLES[status]}`}
      title={detail}
    >
      {(status === "parsing" || status === "cloning") && <Spinner size={10} />}
      {status}
    </span>
  );
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
  bodyClassName = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-ink-700/70 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={`p-4 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-6 backdrop-blur-sm">
      <div
        className={`card mt-10 w-full ${wide ? "max-w-5xl" : "max-w-xl"} shadow-2xl`}
      >
        <header className="flex items-center justify-between border-b border-ink-700/70 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
          <button className="btn px-2 py-1" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="max-h-[70vh] overflow-auto p-4">{children}</div>
      </div>
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null | undefined }) {
  if (!error) return null;
  return (
    <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">
      {error}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-ink-600 px-6 py-10 text-center text-sm text-slate-500">
      {message}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  accent = false,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: boolean;
}) {
  return (
    <div className="card-pad">
      <div className="label">{label}</div>
      <div
        className={`mt-1 text-2xl font-semibold tabular-nums ${
          accent ? "text-accent" : "text-slate-100"
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

/** Horizontal share bar used in tables. */
export function ShareBar({ value, max, tone = "accent" }: { value: number; max: number; tone?: string }) {
  const width = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  const toneClass =
    tone === "rose"
      ? "bg-rose-400/70"
      : tone === "emerald"
        ? "bg-emerald-400/70"
        : "bg-accent/70";
  return (
    <div className="h-1.5 w-full rounded-full bg-ink-700">
      <div className={`h-1.5 rounded-full ${toneClass}`} style={{ width: `${width}%` }} />
    </div>
  );
}
