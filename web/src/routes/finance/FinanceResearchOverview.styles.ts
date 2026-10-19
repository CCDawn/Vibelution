const styles = {
  body: "grid min-w-0 max-w-5xl content-start gap-5 p-4 sm:p-6",
  start: "grid min-w-0 justify-items-start gap-3 rounded-lg border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-5",
  startTitle: "m-0 text-lg font-semibold",
  identity: "grid min-w-0 gap-0.5",
  eyebrow: "text-[11px] text-[var(--fg-tertiary)]",
  name: "m-0 break-words text-xl font-semibold tracking-tight",
  meta: "m-0 truncate text-xs text-[var(--fg-tertiary)]",
  section: "grid min-w-0 gap-2 border-t border-[var(--vui-border-subtle)] pt-3",
  sectionTitle: "m-0 text-xs font-medium text-[var(--fg-secondary)]",
  statusRow: "flex min-w-0 items-center gap-2 text-xs",
  statusDot: "h-2 w-2 shrink-0 rounded-full bg-[var(--fg-tertiary)]",
  statusRunning: "animate-pulse bg-[var(--accent-cool)] motion-reduce:animate-none",
  statusDone: "bg-[var(--state-success)]",
  statusAttention: "bg-[var(--state-warning)]",
  statusFailed: "bg-[var(--state-error)]",
  statusText: "min-w-0 flex-1 truncate font-medium",
  counts: "flex flex-wrap gap-1.5",
  count: "!min-h-7 !h-7 !px-2 text-xs",
  actions: "grid min-w-0 gap-1.5",
  action: "!min-h-8 !h-8 !px-2 text-xs",
  references: "grid min-w-0 gap-1",
  reference: "w-full min-w-0 justify-start !h-auto !min-h-8 !px-2 !py-1 text-left text-xs",
  referenceText: "block min-w-0 truncate",
  empty: "m-0 text-xs leading-5 text-[var(--fg-tertiary)]",
} as const;

export function researchStatusDotClass(state: string, hasAttention: boolean) {
  if (state === "running" || state === "stopping") return styles.statusRunning;
  if (state === "completed") return styles.statusDone;
  if (state === "failed") return styles.statusFailed;
  if (state === "approval" || state === "needs_continue" || hasAttention) return styles.statusAttention;
  return "";
}

export default styles;
