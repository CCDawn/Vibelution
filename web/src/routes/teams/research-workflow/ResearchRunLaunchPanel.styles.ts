export default {
  root: "flex h-full min-h-0 flex-col gap-3 overflow-auto p-3",
  state: "m-3",
  selectedQuestion: "grid min-w-0 gap-1 border-[var(--vui-border-subtle)]",
  questionTitle: "truncate [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-primary)]",
  questionScope: "line-clamp-2 [font-size:var(--vui-font-2xs)] leading-relaxed text-[var(--fg-secondary)]",
  selectedExperiment: "grid min-w-0 gap-1.5 border-[var(--vui-border-subtle)]",
  experimentHeader: "flex min-w-0 items-center justify-between gap-2",
  experimentTitle: "min-w-0 truncate [font-size:var(--vui-font-xs)] font-semibold text-[var(--fg-primary)]",
  experimentMeta: "flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)]",
  experimentStatus: "[font-size:var(--vui-font-2xs)] font-medium text-[var(--fg-primary)]",
  experimentBlockerText: "[font-size:var(--vui-font-2xs)] leading-relaxed text-[var(--state-warning)]",
  blockers: "grid min-w-0 list-disc gap-0.5 pl-4 [font-size:var(--vui-font-2xs)] leading-relaxed text-[var(--fg-secondary)]",
  checkpoint: "grid min-w-0 gap-1 [font-size:var(--vui-font-2xs)] leading-relaxed text-[var(--fg-secondary)]",
  error: "[font-size:var(--vui-font-xs)] text-[var(--state-error)]",
  techDetails:
    "grid max-w-full gap-1 [font-size:var(--vui-font-2xs)] text-[var(--fg-secondary)] [&>summary]:w-fit [&>summary]:cursor-pointer [&_code]:wrap-anywhere [&_code]:text-[10px]",
  actions:
    "sticky bottom-0 z-10 -mx-3 -mb-3 mt-auto flex flex-wrap items-center justify-end gap-2 border-t border-[var(--vui-border-subtle)] bg-vui-surface-panel px-3 py-3 shadow-[0_-10px_24px_-20px_rgba(15,23,42,0.6)]",
} as const;
