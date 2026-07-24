import {
  vuiFlatPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  root: "relative min-w-0 w-full",
  trigger: "flex w-full min-h-8 min-w-0 items-center justify-between gap-2 rounded-md border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1.5 text-left [font-size:var(--vui-font-sm)] text-[var(--fg-primary)] shadow-none hover:border-[color-mix(in_srgb,var(--accent-cool)_40%,var(--vui-border-subtle))] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--vui-accent-cool)] disabled:cursor-not-allowed disabled:opacity-55",
  triggerMuted: "text-[var(--fg-tertiary)]",
  triggerText: "min-w-0 flex-1 truncate",
  list: `absolute left-0 right-0 top-[calc(100%+4px)] z-[40] m-0 max-h-[240px] list-none overflow-y-auto rounded-md border border-[var(--vui-border-subtle)] ${vuiFlatPanelClass} p-1 shadow-[var(--vui-shadow-floating)]`,
  option: "grid w-full min-w-0 gap-0.5 rounded-[calc(var(--radius-control)-2px)] px-2 py-1.5 text-left [font-size:var(--vui-font-xs)] text-[var(--fg-primary)] hover:bg-[color-mix(in_srgb,var(--accent-cool)_10%,transparent)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--vui-accent-cool)] disabled:cursor-not-allowed disabled:opacity-55 [&>small]:text-[var(--fg-tertiary)] [&>small]:leading-snug",
  optionSelected: "bg-[color-mix(in_srgb,var(--accent-cool)_14%,transparent)] font-semibold",
  optionDisabled: "text-[var(--fg-tertiary)]",
} as const;

export default styles;
