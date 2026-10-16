import { vuiStateSelectedOpaqueRowClass } from "../design/vuiSurfaceRecipes";

const styles = {
  // Keep the route marker on the root only: base.css treats every marker as a primary-color surface.
  agentDirectory:
    "vui-routes-agentconversationdirectory grid min-w-0 gap-1 border-0 bg-transparent pb-0",
  agentSection:
    "agentSection grid min-w-0 gap-0.5 [&>button]:min-h-[34px] [&>button]:font-medium [&>button]:!text-vui-fg-secondary [&>button]:[font-size:var(--vui-font-2xs)] [&>div]:gap-0.5 [&>div]:pl-0",
  agentDirectoryList:
    "agentDirectoryList grid min-w-0 gap-0.5",
  hiddenTeamEntry: "w-full justify-start",
  hiddenTeamList: "flex flex-col gap-2",
  hiddenTeamRow: "flex items-center justify-between gap-3",
  hiddenTeamName: "min-w-0 truncate",
  agentRoomHistory:
    "agentRoomHistory grid min-w-0 gap-0.5 pl-1 [&>button]:min-h-8 [&>button]:font-medium [&>button]:[font-size:var(--vui-font-xs)] [&>div]:gap-0.5 [&>div]:pl-0",
  agentRoomHistoryTopic:
    "agentRoomHistoryTopic grid min-w-0 gap-0.5 [&>button]:min-h-7 [&>button]:font-normal [&>button]:[font-size:var(--vui-font-2xs)] [&>div]:gap-0.5 [&>div]:pl-1",
  // surface-role: hover-fill — the trailing activity stays on the row mid-line.
  agentRow:
    "agentRow !grid !h-auto !min-h-[62px] !w-full min-w-0 max-w-full " +
    "grid-cols-[36px_minmax(0,1fr)_auto] !items-stretch !justify-items-stretch !justify-start " +
    "gap-x-[9px] gap-y-1 rounded-[8px] !border-0 [border:0] !bg-transparent px-2 py-[7px] " +
    "text-left !font-normal shadow-none transition-[background-color] hover:!border-transparent hover:!bg-vui-surface-card " +
    "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)]",
  agentRowActive:
    `agentRowActive !border-0 [border:0] ${vuiStateSelectedOpaqueRowClass} shadow-[var(--vui-sheen)]`,
  agentAvatar:
    "agentAvatar grid h-9 w-9 shrink-0 place-items-center self-center overflow-hidden rounded-[9px] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] [font-size:var(--vui-font-xs)] font-medium [color:var(--fg-secondary)]",
  agentAvatarImage:
    "agentAvatarImage h-full w-full object-cover",
  agentCopy:
    "agentCopy grid min-w-0 gap-1 self-center overflow-hidden text-left [overflow-wrap:anywhere]",
  agentTitleRow:
    "agentTitleRow flex min-w-0 items-center",
  agentTitle:
    "agentTitle min-w-0 whitespace-normal break-words [font-size:var(--vui-type-control-size)] font-medium leading-[1.35] [color:var(--fg-primary)] [overflow-wrap:anywhere]",
  // Stretch to row height then center the light — survives VButton/Shadcn justify/items defaults.
  agentStatusSlot:
    "agentStatusSlot flex h-full min-h-full min-w-3.5 shrink-0 items-center justify-end gap-1.5 self-stretch",
  agentActivity:
    "agentActivity grid h-2.5 w-2.5 shrink-0 place-items-center",
  agentActivitySpinner:
    "agentActivitySpinner animate-spin",
  agentActivityRunning:
    "agentActivityRunning h-3 w-3 text-[var(--state-success)]",
  agentActivityApproval:
    "agentActivityApproval h-3 w-3 text-[var(--state-warning)]",
  agentActivityError:
    "agentActivityError h-2.5 w-2.5 rounded-full bg-[var(--state-error)]",
  agentActivityCompleted:
    "agentActivityCompleted h-2.5 w-2.5 rounded-full bg-[var(--accent-cool)]",
  agentMeta:
    "agentMeta flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 whitespace-normal break-words [font-size:var(--vui-font-micro-11)] font-normal leading-[1.35] [color:var(--fg-secondary)] [overflow-wrap:anywhere]",
  agentMetaItem:
    "agentMetaItem min-w-0 whitespace-normal break-words [overflow-wrap:anywhere]",
  agentEmpty:
    "agentEmpty rounded-[var(--radius-control)] border border-dashed border-[var(--vui-border-subtle)] px-2.5 py-3 [font-size:var(--vui-font-sm)] [color:var(--fg-secondary)]",
} as const;

export default styles;
