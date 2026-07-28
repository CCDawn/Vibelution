const styles: Record<string, string> = {
  root:
    "min-w-0 rounded-[10px] border border-[var(--line)] bg-[var(--panel)] p-3.5 shadow-[var(--shadow)]",
  header:
    "mb-3 flex items-start justify-between gap-4 [&>div>span]:text-[10px] [&>div>span]:font-bold [&>div>span]:uppercase [&>div>span]:tracking-[0.08em] [&>div>span]:text-[var(--text-muted)] [&_h3]:mt-1 [&_h3]:text-sm [&_h3]:font-bold [&_h3]:text-[var(--text)]",
  count:
    "shrink-0 rounded-full border border-[var(--line)] bg-[var(--panel-subtle)] px-2 py-1 text-[10px] text-[var(--text-secondary)]",
  projectWarning:
    "mb-3 flex items-center gap-2 rounded-lg border border-[color-mix(in_srgb,var(--warning)_35%,var(--line))] bg-[var(--warning-soft)] px-2.5 py-2 text-[11px] text-[var(--warning)]",
  error:
    "mb-3 rounded-lg border border-[color-mix(in_srgb,var(--danger)_35%,var(--line))] bg-[var(--danger-soft)] px-2.5 py-2 text-[11px] text-[var(--danger)]",
  grid: "grid grid-cols-2 gap-2.5",
  card:
    "min-w-0 rounded-lg border border-[var(--line)] bg-[var(--panel-subtle)] p-2.5",
  cardHeader: "flex items-center justify-between gap-2",
  role:
    "inline-flex min-w-0 items-center gap-1.5 text-xs font-bold text-[var(--text)]",
  status: "shrink-0 px-2 py-0.5",
  description:
    "mt-2 text-[10px] leading-relaxed text-[var(--text-secondary)]",
  session:
    "mt-2.5 min-w-0 rounded-md border border-[var(--line)] bg-[var(--panel)] px-2.5 py-2 [&>strong]:block [&>strong]:truncate [&>strong]:text-[10px] [&>strong]:text-[var(--text)] [&>span]:mt-1 [&>span]:block [&>span]:truncate [&>span]:text-[10px] [&>span]:text-[var(--text-muted)]",
  actions: "mt-2.5 flex flex-wrap items-center gap-2",
};

export default styles;
