import { vuiFlatPanelClass, vuiToolbarFillClass } from "../design/vuiSurfaceRecipes";

const styles = {
  panel: `block min-w-0 overflow-hidden ${vuiFlatPanelClass} px-2 py-1.5`,
  summary:
    "flex min-w-0 cursor-pointer list-none items-center justify-between gap-2 [&::-webkit-details-marker]:hidden [&::-webkit-details-marker]:[display:none]",
  title: "m-0 shrink-0 [font-size:var(--vui-font-xs)] uppercase tracking-[0.08em] text-vui-fg-tertiary",
  hint: "min-w-0 text-right [font-size:var(--vui-font-2xs)] text-vui-fg-tertiary",
  body: "mt-2 grid min-w-0 gap-2",
  fields: "grid min-w-0 grid-cols-[repeat(3,minmax(0,1fr))] items-end gap-1.5 max-[860px]:grid-cols-[minmax(0,1fr)]",
  field:
    "grid min-w-0 gap-[3px] [&>span]:[font-size:var(--vui-font-xs)] [&>span]:uppercase [&>span]:tracking-[0.06em] [&>span]:text-[var(--fg-tertiary)] [&>small]:min-w-0 [&>small]:truncate [&>small]:[font-size:var(--vui-font-xs)] [&>small]:text-[var(--fg-secondary)] [&_input]:min-h-7 [&_input]:w-full [&_input]:min-w-0 [&_input]:rounded-[var(--radius-control)] [&_input]:border [&_input]:border-[var(--border-soft)] [&_input]:bg-[var(--vui-surface-row)] [&_input]:px-[7px] [&_input]:py-[3px] [&_input]:[font-size:var(--vui-font-xs)] [&_input]:text-[var(--fg-primary)]",
  actions: "flex min-w-0 justify-end",
  save: `inline-flex min-h-7 w-fit items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-primary)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-primary)_12%,var(--vui-control-muted))] px-2 py-[3px] [font-size:var(--vui-font-xs)] text-vui-fg-primary hover:border-[color-mix(in_srgb,var(--accent-primary)_44%,transparent)] hover:bg-[color-mix(in_srgb,var(--accent-primary)_18%,var(--vui-control-muted))] disabled:cursor-default disabled:opacity-55 [&[data-vui]]:min-w-0 ${vuiToolbarFillClass}`,
  error: "[font-size:var(--vui-font-xs)] text-[var(--state-error)]",
  spin: "animate-spin",
} as const;

export default styles;
