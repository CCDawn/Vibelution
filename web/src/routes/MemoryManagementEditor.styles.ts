import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  fieldStack:
    "fieldStack min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  iconButton:
    "iconButton min-w-0 inline-grid h-[var(--vui-control-height-sm)] min-h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] place-items-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-0 text-[var(--fg-secondary)] hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] shrink-0 text-[var(--fg-tertiary)]",
  managementHeader:
    "managementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  managementPanel: `managementPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  panelEyebrow:
    "panelEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
} as const;

export default styles;
