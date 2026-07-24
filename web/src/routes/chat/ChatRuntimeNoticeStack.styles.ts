import {
  vuiFlatPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  stack:
    "min-w-0 rounded-none border-0 bg-transparent p-0 shadow-none",
  list:
    "min-w-0 grid content-start gap-1.5",
  summaryItem: "min-w-0",
  notice: `min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} px-2 py-1.5 shadow-none !grid grid-cols-[16px_minmax(0,1fr)] items-start gap-[7px]`,
  body:
    "min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  label:
    "block [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  message:
    "block min-w-0 break-words [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [overflow-wrap:anywhere]",
  toneError:
    "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  toneInfo:
    "border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  toneMuted: `${vuiFlatPanelClass} text-[var(--fg-tertiary)]`,
  toneSuccess:
    "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  toneTool:
    "border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  toneWarning:
    "border-[color-mix(in_srgb,var(--state-warning)_42%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_12%,transparent)] text-[var(--state-warning)]",
} as const;

export default styles;
