import {
  vuiOpaqueRowClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  runtimeFocusPanel: "grid [gap:8px] min-w-0 [padding:10px] [border:1px_solid_color-mix(in_srgb,_var(--accent-cool)_28%,_var(--vui-border-subtle))] [border-radius:var(--radius-panel)] [background:color-mix(in_srgb,_var(--accent-cool)_6%,_var(--vui-surface-panel))] [box-shadow:none]",
  runtimeFocusHeader: "grid [grid-template-columns:minmax(0,_1fr)_auto] [gap:10px] [align-items:center] min-w-0",
  panelEyebrow: "[margin:0_0_1px] [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)] [letter-spacing:0.07em] [text-transform:uppercase]",
  runtimePill: "inline-flex [align-items:center] [justify-content:center] [min-height:26px] [padding:0_7px] [border:1px_solid_var(--vui-border-subtle)] [border-radius:999px] [font-size:var(--vui-font-xs)] [font-weight:700] [white-space:nowrap]",
  runtime_archived: "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_24%,_transparent)] [background:color-mix(in_srgb,_var(--fg-tertiary)_8%,_transparent)] [color:var(--fg-secondary)]",
  runtime_blocked: "[border-color:color-mix(in_srgb,_var(--state-error)_34%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_10%,_transparent)] [color:var(--state-error)]",
  runtime_failed: "[border-color:color-mix(in_srgb,_var(--state-error)_34%,_transparent)] [background:color-mix(in_srgb,_var(--state-error)_10%,_transparent)] [color:var(--state-error)]",
  runtime_idle: "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_24%,_transparent)] [background:color-mix(in_srgb,_var(--fg-tertiary)_8%,_transparent)] [color:var(--fg-secondary)]",
  runtime_running: "[border-color:color-mix(in_srgb,_var(--accent-cool)_34%,_transparent)] [background:color-mix(in_srgb,_var(--accent-cool)_10%,_transparent)] [color:var(--accent-cool)]",
  runtime_stopped: "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_24%,_transparent)] [background:color-mix(in_srgb,_var(--fg-tertiary)_8%,_transparent)] [color:var(--fg-secondary)]",
  runtime_unknown: "[border-color:color-mix(in_srgb,_var(--fg-tertiary)_24%,_transparent)] [background:color-mix(in_srgb,_var(--fg-tertiary)_8%,_transparent)] [color:var(--fg-secondary)]",
  runtimeMetaTooltip: "grid [gap:4px] [&_span]:[overflow-wrap:anywhere]",
  runtimeMetaTrigger: "[border-radius:6px] focus-visible:[outline:2px_solid_var(--accent-cool)] focus-visible:[outline-offset:2px]",
  runtimeNextStep: `min-w-0 [padding:8px_10px] ${vuiOpaqueRowClass}`,
  runtimeNextStepTrigger: "block min-w-0 [overflow:hidden] [color:var(--fg-primary)] [font-size:var(--vui-font-sm)] [font-weight:700] [text-overflow:ellipsis] [white-space:nowrap] [border-radius:6px] focus-visible:[outline:2px_solid_var(--accent-cool)] focus-visible:[outline-offset:2px]",
  timelineActions: "flex [flex-wrap:wrap] [gap:5px] min-w-0 [&_[data-vui=\\\"button\\\"]]:[max-width:100%] [&_[data-vui=\\\"button\\\"]]:[white-space:nowrap]",
} as const;

export default styles;
