import { vuiFlatPanelClass, vuiOpaqueRowClass } from "../design/vuiSurfaceRecipes";

const styles = {
  configurationPanel: `grid min-w-0 [align-content:start] [gap:8px] [padding:10px] ${vuiFlatPanelClass}`,
  panelHeader: "grid min-w-0 [grid-template-columns:minmax(0,1fr)_auto] [align-items:start] [gap:8px] [&_div]:min-w-0 [&_h3]:m-0 [&_h3]:text-[var(--fg-primary)] [&_h3]:[font-size:var(--vui-font-md)] [&_p]:m-0 [&_p]:mt-1 [&_p]:text-[var(--fg-tertiary)] [&_p]:[font-size:var(--vui-font-sm)] [&_p]:leading-[1.45] max-[640px]:[grid-template-columns:1fr]",
  sourceSummary: `grid min-w-0 [grid-template-columns:auto_minmax(0,1fr)] [align-items:center] [gap:7px] [padding:7px_8px] ${vuiOpaqueRowClass} [&_span]:min-w-0 [&_span]:truncate [&_span]:text-[var(--fg-secondary)] [&_span]:[font-size:var(--vui-font-xs)]`,
  sourceSummaryLabel: "inline-flex [align-items:center] [justify-content:center] [min-height:20px] [padding:0_6px] [border-radius:999px] [background:color-mix(in_srgb,var(--accent-cool)_10%,transparent)] [color:var(--accent-cool)] [font-size:var(--vui-font-xs)] [font-weight:760]",
  configurationTable: "grid min-w-0 overflow-hidden [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] [border-radius:var(--radius-control)] [background:var(--vui-surface-row)] max-[860px]:[overflow:visible]",
  tableHeader: "grid min-w-0 [grid-template-columns:minmax(132px,1.1fr)_minmax(0,1.2fr)_minmax(112px,.8fr)_auto] [gap:8px] [padding:7px_9px] [border-bottom:1px_solid_var(--vui-border-hairline)] [background:var(--vui-surface-toolbar)] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [font-weight:760] max-[860px]:hidden",
  configurationRow: "grid w-full min-w-0 [grid-template-columns:minmax(132px,1.1fr)_minmax(0,1.2fr)_minmax(112px,.8fr)_auto] [align-items:center] [gap:8px] [padding:8px_9px] [border:0] [border-bottom:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] [background:transparent] [text-align:left] hover:[background:var(--vui-surface-row-hover)] focus-visible:[outline:2px_solid_var(--accent-cool)] focus-visible:[outline-offset:-2px] [&:last-child]:[border-bottom:0] max-[860px]:[grid-template-columns:minmax(0,1fr)_auto] max-[860px]:[gap:4px_8px]",
  configurationRowSelected: "[background:color-mix(in_srgb,var(--accent-cool)_8%,transparent)]",
  fieldIdentity: "grid min-w-0 [gap:2px] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-sm)] [&_small]:min-w-0 [&_small]:truncate [&_small]:text-[var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  fieldValue: "grid min-w-0 [gap:2px] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--fg-secondary)] [&_strong]:[font-family:var(--font-mono)] [&_strong]:[font-size:var(--vui-font-sm)] [&_small]:min-w-0 [&_small]:truncate [&_small]:text-[var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)] max-[860px]:[grid-column:1]",
  sourceCell: "inline-flex min-w-0 [align-items:center] [justify-content:flex-start] [gap:5px] max-[860px]:[grid-column:2] max-[860px]:[grid-row:1_/_span_2]",
  sourceChip: "inline-flex max-w-full [align-items:center] [min-height:20px] [padding:0_6px] [border:1px_solid_color-mix(in_srgb,var(--accent-cool)_22%,transparent)] [border-radius:999px] [background:color-mix(in_srgb,var(--accent-cool)_8%,transparent)] [color:var(--accent-cool)] [font-size:var(--vui-font-xs)] [font-weight:720] [white-space:nowrap]",
  sourceChipAgent: "[border-color:color-mix(in_srgb,var(--accent-warm)_28%,transparent)] [background:color-mix(in_srgb,var(--accent-warm)_10%,transparent)] [color:var(--accent-warm-2)]",
  sourceChipSystem: "[border-color:color-mix(in_srgb,var(--fg-tertiary)_28%,transparent)] [background:color-mix(in_srgb,var(--fg-tertiary)_8%,transparent)] [color:var(--fg-secondary)]",
  sourceChipGlobal: "[border-color:color-mix(in_srgb,var(--accent-violet)_25%,transparent)] [background:color-mix(in_srgb,var(--accent-violet)_9%,transparent)] [color:var(--accent-violet)]",
  statusCell: "inline-flex [align-items:center] [justify-content:flex-end] [gap:4px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] max-[860px]:[grid-column:1]",
  statusReady: "[color:var(--accent-success)]",
  statusWarning: "[color:var(--accent-warm-2)]",
  statusBlocked: "[color:var(--accent-danger)]",
  inspectorSection: "grid min-w-0 [gap:6px] [padding:10px] [&_h4]:m-0 [&_h4]:text-[var(--fg-primary)] [&_h4]:[font-size:var(--vui-font-sm)]",
  inspectorLabel: "[color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [font-weight:760]",
  inspectorValue: "min-w-0 [padding:8px] [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] [border-radius:var(--radius-control)] [background:var(--vui-surface-row)] [color:var(--fg-primary)] [font-family:var(--font-mono)] [font-size:var(--vui-font-sm)] [overflow-wrap:anywhere]",
  inheritanceList: "grid min-w-0 [gap:0] [list-style:none] [margin:0] [padding:0] [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] [border-radius:var(--radius-control)] [background:var(--vui-surface-row)]",
  inheritanceItem: "grid min-w-0 [grid-template-columns:auto_minmax(0,1fr)] [gap:7px] [padding:8px] [border-bottom:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_68%,transparent)] [&:last-child]:[border-bottom:0]",
  inheritanceIndex: "inline-grid [place-items:center] [width:20px] [height:20px] [border-radius:999px] [background:color-mix(in_srgb,var(--fg-tertiary)_12%,transparent)] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [font-weight:760]",
  inheritanceCopy: "grid min-w-0 [gap:2px] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--fg-secondary)] [&_strong]:[font-size:var(--vui-font-sm)] [&_small]:min-w-0 [&_small]:truncate [&_small]:text-[var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  inheritanceCurrent: "[background:color-mix(in_srgb,var(--accent-cool)_8%,transparent)] [&_span]:[background:color-mix(in_srgb,var(--accent-cool)_16%,transparent)] [&_span]:[color:var(--accent-cool)]",
  inspectorAction: "w-full",
} as const;

export default styles;
