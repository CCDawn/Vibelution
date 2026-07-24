import {
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  thread: "grid min-w-0 gap-2.5",
  message: `grid min-w-0 gap-1.5 ${vuiOpaqueRowClass} px-2.5 py-2 text-[var(--fg-secondary)]`,
  messageAssistant: "border-l-2 border-l-[color-mix(in_srgb,var(--accent-cool)_48%,transparent)]",
  messageUser: "border-l-2 border-l-[color-mix(in_srgb,var(--accent-warm)_42%,transparent)]",
  messageHeader:
    "flex min-w-0 items-center justify-between gap-2 text-[length:var(--vui-font-xs)] leading-[var(--vui-line-tight)] text-[var(--fg-tertiary)]",
  role: "min-w-0 overflow-hidden text-ellipsis whitespace-nowrap font-bold text-[var(--fg-secondary)]",
  time: "flex-none tabular-nums",
  parts: "grid min-w-0 gap-1.5",
  section: "min-w-0",
  processSection: "grid gap-1.5",
  contentSection: "grid gap-1.5",
  contextSection: "flex min-w-0 flex-wrap gap-1.5",
  part: "min-w-0 text-[length:var(--vui-font-sm)] leading-[var(--vui-line-readable)] [overflow-wrap:anywhere]",
  text: "m-0 whitespace-pre-wrap text-[var(--fg-primary)]",
  processPart:
    "grid gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] !bg-[var(--vui-surface-row-hover)] px-2 py-1.5",
  partHeader: "flex min-w-0 items-center gap-1.5 text-[length:var(--vui-font-xs)] leading-[var(--vui-line-tight)]",
  partName: "min-w-0 overflow-hidden text-ellipsis whitespace-nowrap font-bold text-[var(--fg-secondary)]",
  partStatus:
    "flex-none rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-1.5 py-0.5 text-[length:var(--vui-font-xs)] leading-none text-[var(--fg-tertiary)]",
  summary: "m-0 text-[var(--fg-secondary)]",
  preview:
    "m-0 max-h-40 overflow-auto rounded-[var(--radius-control)] bg-[var(--vui-surface-workspace)] px-2 py-1.5 font-mono text-[length:var(--vui-font-xs)] whitespace-pre-wrap text-[var(--fg-primary)]",
  contextPart:
    "flex w-fit max-w-full min-w-0 flex-wrap items-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[length:var(--vui-font-xs)] leading-[var(--vui-line-tight)] text-[var(--fg-secondary)]",
  contextLabel: "min-w-0 max-w-[36ch] overflow-hidden text-ellipsis whitespace-nowrap",
} as const;

export default styles;
