import {
  vuiStateCoolInfoClass,
  vuiStateDangerSoftClass,
  vuiStateSuccessSoftClass,
  vuiStateWarmSoftClass,
  vuiWorkspaceFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  detailHeaderFrame: `grid min-w-0 grid-rows-[auto_auto] border-b border-[var(--vui-border-subtle)] ${vuiWorkspaceFillClass}`,
  detailHeader:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-0 pb-3 [&_h2]:m-0 [&_h2]:min-w-0 [&_h2]:truncate [&_h2]:text-lg [&_h2]:font-semibold max-[680px]:grid-cols-1 max-[680px]:gap-2",
  detailIdentity: "flex min-w-0 items-center gap-3",
  detailIdentityCopy:
    "grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-0.5 [&_h2]:col-start-1 [&_h2]:row-start-2",
  panelEyebrow:
    "col-span-full m-0 truncate [font-size:var(--vui-font-xs)] uppercase tracking-[0.07em] text-[var(--fg-tertiary)]",
  detailHeaderActions:
    "flex min-w-0 flex-wrap items-center justify-end gap-2 max-[680px]:justify-start [&_[data-vui=button]]:w-fit",
  detailHealthStatus: "col-start-2 row-start-2 inline-flex min-w-0 justify-self-end",
  issuePill:
    "inline-flex min-h-[22px] max-w-full items-center justify-center truncate rounded-full border border-[var(--vui-border-subtle)] px-2 py-0.5 [font-size:var(--vui-font-xs)] font-semibold",
  issue_blocking:
    `${vuiStateDangerSoftClass}`,
  issue_info:
    `${vuiStateCoolInfoClass}`,
  issue_ok:
    `${vuiStateSuccessSoftClass}`,
  issue_warning:
    `${vuiStateWarmSoftClass}`,
  detailTabs: `flex min-w-0 items-end gap-6 overflow-x-auto [border:1px_solid_color-mix(in_srgb,var(--vui-border-subtle)_72%,transparent)] [border-left:0] [border-right:0] [border-top:0] ${vuiWorkspaceFillClass} px-0`,
  detailTab:
    "inline-flex min-h-10 w-fit min-w-max items-center justify-center gap-1.5 border-x-0 border-t-0 border-b-2 border-transparent bg-transparent px-0.5 [font-size:var(--vui-font-sm)] font-semibold text-[var(--fg-tertiary)] hover:border-[color-mix(in_srgb,var(--accent-cool)_36%,transparent)] hover:text-[var(--fg-primary)] [&_strong]:[font-size:var(--vui-font-xs)]",
  detailTabActive:
    "inline-flex min-h-10 w-fit min-w-max items-center justify-center gap-1.5 border-x-0 border-t-0 border-b-2 border-[var(--accent-cool)] bg-transparent px-0.5 [font-size:var(--vui-font-sm)] font-semibold text-[var(--accent-cool)] [&_strong]:[font-size:var(--vui-font-xs)]",
  // Legacy contract aliases retained for downstream style-source checks.
  agentRoleTag: "inline-flex",
  agentRoleTag_chat: "text-[var(--accent-warm-2)]",
  agentRoleTag_general: "text-[var(--fg-secondary)]",
  agentRoleTag_memory: "text-[var(--fg-secondary)]",
  agentRoleTag_research: "text-[var(--accent-cool-2)]",
  agentRoleTag_self: "text-[var(--state-success)]",
  agentRoleTag_supervised: "text-[var(--state-warning)]",
  agentRoleTag_tool: "text-[var(--fg-secondary)]",
} as const;

export default styles;
