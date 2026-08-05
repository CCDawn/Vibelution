import { vuiStateSelectedRowFillClass } from "../design/vuiSurfaceRecipes";

const styles = {
  agentDirectory:
    "vui-routes-agentconversationdirectory grid min-w-0 gap-1.5 border-b border-[var(--vui-border-subtle)] pb-2",
  agentDirectoryHeader:
    "vui-routes-agentconversationdirectory agentDirectoryHeader flex min-w-0 items-center justify-between px-2.5 pt-1 [font-size:var(--vui-font-xs)] font-semibold uppercase tracking-[0.08em] [color:var(--fg-tertiary)]",
  agentDirectoryCount:
    "vui-routes-agentconversationdirectory agentDirectoryCount tabular-nums [color:var(--fg-secondary)]",
  agentSection:
    "vui-routes-agentconversationdirectory agentSection grid min-w-0 gap-1.5",
  agentDirectoryList:
    "vui-routes-agentconversationdirectory agentDirectoryList grid min-w-0 gap-1.5 pl-1",
  // surface-role: hover-fill — fixed status slot (col 3) so light aligns to card mid-line.
  agentRow:
    "vui-routes-agentconversationdirectory agentRow !grid !h-auto !min-h-[3.25rem] !w-full min-w-0 max-w-full grid-cols-[32px_minmax(0,1fr)_0.875rem] items-center justify-start gap-x-2.5 gap-y-0 rounded-[var(--radius-control)] !border-0 [border:0] !bg-transparent px-2.5 py-2 text-left font-normal shadow-none transition-[background-color] hover:!border-transparent hover:!bg-vui-surface-card focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)]",
  agentRowActive:
    `vui-routes-agentconversationdirectory agentRowActive !border-0 [border:0] ${vuiStateSelectedRowFillClass} !text-[var(--accent-cool)] shadow-none`,
  agentAvatar:
    "vui-routes-agentconversationdirectory agentAvatar grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_9%,transparent)] [font-size:var(--vui-font-xs)] font-semibold [color:var(--accent-cool)]",
  agentAvatarImage:
    "vui-routes-agentconversationdirectory agentAvatarImage h-full w-full object-cover",
  agentCopy:
    "vui-routes-agentconversationdirectory agentCopy grid min-w-0 gap-0.5 overflow-hidden text-left",
  agentTitleRow:
    "vui-routes-agentconversationdirectory agentTitleRow flex min-w-0 items-center",
  agentTitle:
    "vui-routes-agentconversationdirectory agentTitle min-w-0 truncate [font-size:var(--vui-font-sm)] font-semibold leading-tight [color:var(--fg-primary)]",
  // Always-on status column; keeps list geometry stable with/without activity.
  agentStatusSlot:
    "vui-routes-agentconversationdirectory agentStatusSlot inline-grid h-3.5 w-3.5 shrink-0 place-items-center self-center",
  agentActivity:
    "vui-routes-agentconversationdirectory agentActivity inline-grid h-2.5 w-2.5 shrink-0 place-items-center",
  agentActivitySpinner:
    "vui-routes-agentconversationdirectory agentActivitySpinner animate-spin",
  agentActivityRunning:
    "vui-routes-agentconversationdirectory agentActivityRunning h-3 w-3 text-[var(--state-success)]",
  agentActivityApproval:
    "vui-routes-agentconversationdirectory agentActivityApproval h-3 w-3 text-[var(--state-warning)]",
  agentActivityError:
    "vui-routes-agentconversationdirectory agentActivityError h-2.5 w-2.5 rounded-full bg-[var(--state-error)]",
  agentActivityCompleted:
    "vui-routes-agentconversationdirectory agentActivityCompleted h-2.5 w-2.5 rounded-full bg-[var(--accent-cool)]",
  agentMeta:
    "vui-routes-agentconversationdirectory agentMeta flex min-w-0 items-center gap-1.5 overflow-hidden [font-size:var(--vui-font-xs)] leading-tight [color:var(--fg-secondary)]",
  agentMetaItem:
    "vui-routes-agentconversationdirectory agentMetaItem min-w-0 truncate",
  agentMetaCount:
    "vui-routes-agentconversationdirectory agentMetaCount shrink-0 [color:var(--fg-tertiary)]",
  agentEmpty:
    "vui-routes-agentconversationdirectory agentEmpty rounded-[var(--radius-control)] border border-dashed border-[var(--vui-border-subtle)] px-2.5 py-3 [font-size:var(--vui-font-sm)] [color:var(--fg-secondary)]",
} as const;

export default styles;
