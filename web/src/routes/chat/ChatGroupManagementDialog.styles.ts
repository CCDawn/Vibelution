import { vuiControlPillClass, vuiControlQuietClass } from "../../design/vuiChromeRecipes";
import {
  vuiOpaqueRowClass,
  vuiStateCoolInfoClass,
  vuiStateCoolSoftClass,
  vuiStateDangerSoftClass,
} from "../../design/vuiSurfaceRecipes";

const styles: Record<string, string> = {
  dialogContent: "vui-routes-chatgroupmanagementdialog dialogContent max-h-[min(88dvh,52rem)]",
  dialogBody: "vui-routes-chatgroupmanagementdialog dialogBody grid min-h-0 gap-4 overflow-y-auto py-1",
  header: "vui-routes-chatgroupmanagementdialog header min-w-0 flex flex-wrap items-center gap-1.5",
  identity: "vui-routes-chatgroupmanagementdialog identity grid min-w-0 gap-0.5",
  identityMeta: "vui-routes-chatgroupmanagementdialog identityMeta text-xs text-[var(--fg-tertiary)]",
  actions: "vui-routes-chatgroupmanagementdialog actions min-w-0 !grid grid-cols-[repeat(2,minmax(0,1fr))] gap-[7px]",
  applyButton: `vui-routes-chatgroupmanagementdialog applyButton min-w-0 ${vuiControlQuietClass}`,
  secondaryButton: `vui-routes-chatgroupmanagementdialog secondaryButton min-w-0 ${vuiControlQuietClass}`,
  deleteButton: `vui-routes-chatgroupmanagementdialog deleteButton min-w-0 ${vuiControlQuietClass} ${vuiStateDangerSoftClass}`,
  notice: "vui-routes-chatgroupmanagementdialog notice grid min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-warm)_22%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-warm)_5%,var(--vui-surface-row))] px-2 py-1.5 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)]",
  controls: "vui-routes-chatgroupmanagementdialog controls min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-[9px]",
  titleField: "vui-routes-chatgroupmanagementdialog titleField min-w-0 grid gap-1 [font-size:var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_input]:w-full",
  selectField: "vui-routes-chatgroupmanagementdialog selectField min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_input]:w-full [&_select]:w-full",
  memberPicker: "vui-routes-chatgroupmanagementdialog memberPicker grid min-h-0 min-w-0 gap-1.5 overflow-auto pr-1",
  memberPickerResizeHandle: "vui-routes-chatgroupmanagementdialog memberPickerResizeHandle",
  memberChip: `vui-routes-chatgroupmanagementdialog memberChip min-w-0 !grid min-h-[34px] !w-full max-w-full grid-cols-[18px_26px_minmax(0,1fr)_auto] items-center gap-1.5 overflow-hidden ${vuiOpaqueRowClass} px-1.5 py-1 text-left [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)]`,
  memberChipSelected: `vui-routes-chatgroupmanagementdialog memberChipSelected min-w-0 ${vuiStateCoolSoftClass}`,
  memberCopy: "vui-routes-chatgroupmanagementdialog memberCopy grid min-w-0 gap-0.5 overflow-hidden text-left [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] [&_small]:min-w-0 [&_small]:truncate [&_strong]:min-w-0 [&_strong]:truncate",
  agentAvatar: `vui-routes-chatgroupmanagementdialog agentAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] ${vuiStateCoolInfoClass}`,
  agentRoleTag: `vui-routes-chatgroupmanagementdialog agentRoleTag min-w-0 ${vuiControlPillClass} ${vuiStateCoolInfoClass}`,
  agentRoleTag_chat: `vui-routes-chatgroupmanagementdialog agentRoleTag_chat min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_general: `vui-routes-chatgroupmanagementdialog agentRoleTag_general min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_memory: `vui-routes-chatgroupmanagementdialog agentRoleTag_memory min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_research: `vui-routes-chatgroupmanagementdialog agentRoleTag_research min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_self: `vui-routes-chatgroupmanagementdialog agentRoleTag_self min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_supervised: `vui-routes-chatgroupmanagementdialog agentRoleTag_supervised min-w-0 ${vuiStateCoolInfoClass}`,
  agentRoleTag_tool: `vui-routes-chatgroupmanagementdialog agentRoleTag_tool min-w-0 ${vuiStateCoolInfoClass}`,
  missingInline: `vui-routes-chatgroupmanagementdialog missingInline min-w-0 ${vuiStateCoolInfoClass}`,
  hint: "vui-routes-chatgroupmanagementdialog hint min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
};

export default styles;
