import { vuiFlatPanelClass, vuiOpaqueRowClass } from "../design/vuiSurfaceRecipes";

const styles = {
  relationsPanel: `grid min-w-0 [align-content:start] [gap:8px] [padding:10px] ${vuiFlatPanelClass}`,
  panelHeader: "grid min-w-0 [grid-template-columns:minmax(0,1fr)_auto] [align-items:start] [gap:8px] [&_div]:min-w-0 [&_h3]:m-0 [&_h3]:text-[var(--fg-primary)] [&_h3]:[font-size:var(--vui-font-md)] [&_p]:m-0 [&_p]:mt-1 [&_p]:text-[var(--fg-tertiary)] [&_p]:[font-size:var(--vui-font-sm)] [&_p]:leading-[1.45] max-[640px]:[grid-template-columns:1fr]",
  evidenceNote: `min-w-0 [padding:7px_8px] ${vuiOpaqueRowClass} [color:var(--fg-tertiary)] [font-size:var(--vui-font-xs)]`,
  relationList: "grid min-w-0 [gap:6px]",
  relationItem: "grid min-w-0 [grid-template-columns:minmax(0,1fr)_auto] [align-items:start] [gap:8px] [padding:9px] [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] [border-radius:var(--radius-control)] [background:var(--vui-surface-row)] max-[720px]:[grid-template-columns:1fr]",
  relationCopy: "grid min-w-0 [gap:3px] [&_h4]:m-0 [&_h4]:text-[var(--fg-primary)] [&_h4]:[font-size:var(--vui-font-sm)] [&_p]:m-0 [&_p]:text-[var(--fg-tertiary)] [&_p]:[font-size:var(--vui-font-xs)] [&_p]:leading-[1.4]",
  memberList: "flex min-w-0 [flex-wrap:wrap] [gap:5px] [margin:4px_0_0] [padding:0] [list-style:none]",
  member: "inline-grid max-w-full [grid-template-columns:minmax(0,1fr)] [gap:1px] [padding:5px_7px] [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_76%,transparent)] [border-radius:var(--radius-control)] [background:var(--vui-surface-row)] [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:text-[var(--fg-secondary)] [&_strong]:[font-size:var(--vui-font-xs)] [&_small]:min-w-0 [&_small]:truncate [&_small]:text-[var(--fg-tertiary)] [&_small]:[font-size:var(--vui-font-xs)]",
  memberCurrent: "[border-color:color-mix(in_srgb,var(--accent-cool)_30%,transparent)] [background:color-mix(in_srgb,var(--accent-cool)_9%,transparent)] [&_strong]:[color:var(--accent-cool)]",
  openTeam: "self-start",
} as const;

export default styles;
