// Wave 8C: extracted from ChatCodingRoute.styles for ChatStatusRail.tsx

import {
  vuiControlPillClass,
  vuiControlQuietClass,
} from "../../design/vuiChromeRecipes";

import {
  vuiGlassPanelClass,
  vuiOpaqueRowClass,
  vuiStateCoolInfoClass,
  vuiStateCoolSoftClass,
  vuiStateDangerSoftClass,
  vuiStateSelectedRowClass,
  vuiStateSuccessSoftClass,
  vuiStateWarmSoftClass,
  vuiStateWarningSoftClass,
} from "../../design/vuiSurfaceRecipes";

const styles: Record<string, string> = {
  activeSkillEyebrow:
    `vui-routes-chatcodingroute activeSkillEyebrow min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] ${vuiStateSelectedRowClass}`,
  activeSkillIdentity:
    `vui-routes-chatcodingroute activeSkillIdentity grid min-w-0 gap-1 ${vuiStateSelectedRowClass} [&_strong]:min-w-0 [&_strong]:whitespace-normal [&_strong]:leading-tight [overflow-wrap:anywhere]`,
  activeSkillMeta:
    `vui-routes-chatcodingroute activeSkillMeta min-w-0 flex flex-wrap items-center gap-1.5 ${vuiStateSelectedRowClass} [&_span]:min-w-0 [&_span]:whitespace-normal [overflow-wrap:anywhere]`,
  activeSkillState:
    `vui-routes-chatcodingroute activeSkillState min-w-0 ${vuiStateSelectedRowClass}`,
  activeSkillStatus:
    "vui-routes-chatcodingroute activeSkillStatus min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_5%,var(--vui-surface-panel))] text-[var(--accent-cool)] !grid grid-cols-[minmax(0,1fr)] items-start gap-1 rounded-[var(--radius-control)] px-1.5 py-1 shadow-none",
  agentMissingInline:
    `vui-routes-chatcodingroute agentMissingInline min-w-0 ${vuiStateCoolInfoClass}`,
  compactDetails: `vui-routes-chatcodingroute compactDetails grid min-w-0 gap-1 ${vuiOpaqueRowClass} px-1.5 py-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&>summary]:grid [&>summary]:cursor-pointer [&>summary]:list-none [&>summary]:grid-cols-[14px_minmax(0,1fr)] [&>summary]:items-center [&>summary]:gap-1 [&>summary]:font-semibold [&>summary::-webkit-details-marker]:hidden [&>summary_svg]:transition-transform [&[open]>summary_svg]:rotate-90 [&_.compactDetailsOpenLabel]:hidden [&[open]_.compactDetailsOpenLabel]:inline [&[open]_.compactDetailsClosedLabel]:hidden`,
  compactDetailsBody:
    "vui-routes-chatcodingroute compactDetailsBody grid min-h-0 min-w-0 content-start gap-1 overflow-auto [scrollbar-gutter:stable]",
  compactDetailsClosedLabel:
    "vui-routes-chatcodingroute compactDetailsClosedLabel min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  compactDetailsOpenLabel:
    `vui-routes-chatcodingroute compactDetailsOpenLabel min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] ${vuiStateCoolSoftClass}`,
  compactDetailsResizeHandle:
    "vui-routes-chatcodingroute compactDetailsResizeHandle",
  companionBlock:
    "vui-routes-chatcodingroute companionBlock min-w-0 content-start overflow-visible",
  companionCompact:
    "vui-routes-chatcodingroute companionCompact !grid min-w-0 grid-cols-[32px_minmax(0,1fr)] items-start gap-2 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-strong)_64%,transparent)] bg-[var(--vui-surface-raised)] px-1.5 py-1.5 shadow-none",
  companionCopy:
    "vui-routes-chatcodingroute companionCopy grid min-w-0 gap-0.5 [font-size:var(--vui-font-xs)] leading-snug text-[var(--fg-secondary)] [&>p]:min-w-0 [&>p]:[display:-webkit-box] [&>p]:[-webkit-box-orient:vertical] [&>p]:[-webkit-line-clamp:2] [&>p]:overflow-hidden [&>p]:leading-snug [&>p]:[overflow-wrap:anywhere]",
  companionTopLine:
    "vui-routes-chatcodingroute companionTopLine !grid min-w-0 grid-cols-[minmax(0,1fr)] items-start gap-0.5 [font-size:var(--vui-font-xs)] leading-tight [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:[font-size:var(--vui-font-sm)] [&_strong]:font-[760] [&_strong]:text-[var(--fg-primary)] [&_span]:min-w-0 [&_span]:truncate [&_span]:text-[var(--fg-tertiary)]",
  currentSessionBlock:
    "vui-routes-chatcodingroute currentSessionBlock min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_26%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_5%,transparent)] text-[var(--fg-primary)]",
  currentSessionLine: `vui-routes-chatcodingroute currentSessionLine min-w-0 ${vuiOpaqueRowClass} px-1.5 py-1 [font-size:var(--vui-font-xs)] font-medium leading-[1.4] text-[var(--fg-secondary)] [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2] overflow-hidden [overflow-wrap:anywhere]`,
  currentSessionMetaList:
    "vui-routes-chatcodingroute currentSessionMetaList min-w-0 flex flex-wrap items-center gap-1 border-[color-mix(in_srgb,var(--accent-cool)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_6%,transparent)] text-[var(--accent-cool)]",
  featureChip:
    "vui-routes-chatcodingroute featureChip !grid !h-auto min-h-[28px] min-w-0 !w-full max-w-full grid-cols-[minmax(0,1fr)_auto] items-center justify-start gap-1 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] transition-colors hover:border-[var(--vui-control-hover-border)] hover:bg-[var(--vui-control-hover-bg)] hover:text-[var(--vui-control-hover-fg)] disabled:cursor-default disabled:opacity-55 [&_[data-slot=vui-button-content]]:min-w-0 [&_[data-slot=vui-button-content]]:max-w-full [&_[data-slot=vui-button-content]]:w-full [&_[data-slot=vui-button-label]]:grid [&_[data-slot=vui-button-label]]:min-w-0 [&_[data-slot=vui-button-label]]:w-full [&_[data-slot=vui-button-label]]:grid-cols-[minmax(0,1fr)_auto] [&_[data-slot=vui-button-label]]:items-center [&_[data-slot=vui-button-label]]:gap-1 [&_strong]:min-w-0 [&_strong]:truncate [&_strong]:leading-tight [&_em]:inline-flex [&_em]:min-h-[18px] [&_em]:shrink-0 [&_em]:items-center [&_em]:justify-center [&_em]:rounded-full [&_em]:border [&_em]:border-[color-mix(in_srgb,var(--vui-border-subtle)_80%,transparent)] [&_em]:!bg-[var(--vui-surface-panel)] [&_em]:px-1.5 [&_em]:text-[10px] [&_em]:font-bold [&_em]:not-italic [&_em]:leading-none [&_em]:text-[var(--fg-tertiary)]",
  featureChipActive:
    "vui-routes-chatcodingroute featureChipActive border-[color-mix(in_srgb,var(--accent-cool)_40%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-control-muted))] text-[var(--fg-primary)] [&_em]:border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] [&_em]:bg-[color-mix(in_srgb,var(--accent-cool)_14%,transparent)] [&_em]:text-[var(--accent-cool)]",
  featureChipPrimary:
    "vui-routes-chatcodingroute featureChipPrimary border-[color-mix(in_srgb,var(--accent-warm)_28%,var(--vui-border-subtle))]",
  featureChipPrimaryActive:
    "vui-routes-chatcodingroute featureChipPrimaryActive border-[color-mix(in_srgb,var(--accent-warm)_42%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-warm)_11%,var(--vui-control-muted))] text-[var(--fg-primary)] [&_em]:border-[color-mix(in_srgb,var(--accent-warm)_36%,transparent)] [&_em]:bg-[color-mix(in_srgb,var(--accent-warm)_14%,transparent)] [&_em]:text-[var(--accent-warm-2)]",
  featureChipRow:
    "vui-routes-chatcodingroute featureChipRow grid min-w-0 grid-cols-2 gap-1 overflow-visible rounded-none border-0 bg-transparent p-0",
  featurePresetBlock:
    "vui-routes-chatcodingroute featurePresetBlock min-w-0",
  featurePresetScope:
    "vui-routes-chatcodingroute featurePresetScope min-w-0 shrink-0 [font-size:10px] font-semibold leading-none text-[var(--fg-tertiary)]",
  groupApplyButton:
    `vui-routes-chatcodingroute groupApplyButton min-w-0 ${vuiControlQuietClass}`,
  groupDeleteButton:
    `vui-routes-chatcodingroute groupDeleteButton min-w-0 ${vuiControlQuietClass} ${vuiStateDangerSoftClass}`,
  groupManagementActions:
    "vui-routes-chatcodingroute groupManagementActions min-w-0 flex flex-wrap items-center gap-1.5 !grid grid-cols-[repeat(2,minmax(0,1fr))] gap-[7px]",
  groupManagementControls:
    "vui-routes-chatcodingroute groupManagementControls min-w-0 flex flex-wrap items-center gap-1.5 !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-[9px]",
  groupManagementCount:
    "vui-routes-chatcodingroute groupManagementCount min-w-0",
  groupManagementHeader:
    "vui-routes-chatcodingroute groupManagementHeader min-w-0 flex flex-wrap items-center gap-1.5",
  groupManagementHint:
    "vui-routes-chatcodingroute groupManagementHint min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  groupManagementPanel: `vui-routes-chatcodingroute groupManagementPanel min-w-0 ${vuiGlassPanelClass} p-2`,
  groupManagementTitleRow:
    "vui-routes-chatcodingroute groupManagementTitleRow inline-flex min-w-0 items-center gap-1",
  groupMemberChip: `vui-routes-chatcodingroute groupMemberChip min-w-0 !grid min-h-[34px] !w-full max-w-full grid-cols-[18px_26px_minmax(0,1fr)_auto] items-center gap-1.5 overflow-hidden ${vuiOpaqueRowClass} px-1.5 py-1 text-left [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)]`,
  groupMemberChipSelected:
    `vui-routes-chatcodingroute groupMemberChipSelected min-w-0 ${vuiStateCoolSoftClass}`,
  groupMemberCopy:
    "vui-routes-chatcodingroute groupMemberCopy grid min-w-0 gap-0.5 overflow-hidden text-left [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-secondary)] [&_small]:min-w-0 [&_small]:truncate [&_strong]:min-w-0 [&_strong]:truncate",
  // Wave 6G: height from PersistedHeightListShell / pane-heights.v1, not fixed max-h.,
  groupMemberPicker:
    "vui-routes-chatcodingroute groupMemberPicker grid min-h-0 min-w-0 gap-1.5 overflow-auto pr-1",
  groupMemberPickerResizeHandle:
    "vui-routes-chatcodingroute groupMemberPickerResizeHandle",
  groupModeSelect:
    "vui-routes-chatcodingroute groupModeSelect min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  groupProfileBlock:
    "vui-routes-chatcodingroute groupProfileBlock min-w-0",
  groupSecondaryButton:
    `vui-routes-chatcodingroute groupSecondaryButton min-w-0 ${vuiControlQuietClass}`,
  groupTitleField:
    "vui-routes-chatcodingroute groupTitleField min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full [font-size:var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]",
  inlineMetaList:
    "vui-routes-chatcodingroute inlineMetaList min-w-0 grid min-h-0 content-start overflow-visible !grid grid-cols-[minmax(0,1fr)] gap-[4px]",
  inlineMetaPill: `vui-routes-chatcodingroute inlineMetaPill min-w-0 min-h-[24px] max-w-full ${vuiOpaqueRowClass} px-1.5 py-1 text-[11px] font-semibold leading-tight text-[var(--fg-secondary)] !grid grid-cols-[minmax(58px,0.42fr)_minmax(0,1fr)] items-baseline gap-1 [&_span]:min-w-0 [&_span]:whitespace-normal [&_strong]:min-w-0 [&_strong]:whitespace-normal [overflow-wrap:anywhere]`,
  inlineStat:
    "vui-routes-chatcodingroute inlineStat min-w-0 !grid grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] items-baseline gap-0.5 [font-size:var(--vui-font-xs)] leading-tight [&_span]:min-w-0 [&_span]:whitespace-normal [&_span]:text-[var(--fg-tertiary)] [&_strong]:min-w-0 [&_strong]:whitespace-normal [overflow-wrap:anywhere]",
  inlineStatGrid:
    "vui-routes-chatcodingroute inlineStatGrid min-w-0 grid gap-2 !grid grid-cols-[1fr] gap-[3px]",
  mentalStateBadge_active:
    `vui-routes-chatcodingroute mentalStateBadge_active min-w-0 ${vuiStateSelectedRowClass}`,
  mentalStateBadge_answering:
    "vui-routes-chatcodingroute mentalStateBadge_answering min-w-0",
  mentalStateBadge_blocked:
    `vui-routes-chatcodingroute mentalStateBadge_blocked min-w-0 ${vuiStateWarningSoftClass}`,
  mentalStateBadge_bunny:
    "vui-routes-chatcodingroute mentalStateBadge_bunny min-w-0",
  mentalStateBadge_cache:
    "vui-routes-chatcodingroute mentalStateBadge_cache min-w-0",
  mentalStateBadge_cat:
    "vui-routes-chatcodingroute mentalStateBadge_cat min-w-0",
  mentalStateBadge_chat:
    "vui-routes-chatcodingroute mentalStateBadge_chat min-w-0",
  mentalStateBadge_checking:
    "vui-routes-chatcodingroute mentalStateBadge_checking min-w-0",
  mentalStateBadge_chick:
    "vui-routes-chatcodingroute mentalStateBadge_chick min-w-0",
  mentalStateBadge_compression:
    "vui-routes-chatcodingroute mentalStateBadge_compression min-w-0",
  mentalStateBadge_crab:
    "vui-routes-chatcodingroute mentalStateBadge_crab min-w-0",
  mentalStateBadge_danger:
    `vui-routes-chatcodingroute mentalStateBadge_danger min-w-0 ${vuiStateDangerSoftClass}`,
  mentalStateBadge_default:
    "vui-routes-chatcodingroute mentalStateBadge_default min-w-0",
  mentalStateBadge_disoriented:
    "vui-routes-chatcodingroute mentalStateBadge_disoriented min-w-0",
  mentalStateBadge_done:
    "vui-routes-chatcodingroute mentalStateBadge_done min-w-0",
  mentalStateBadge_editing:
    "vui-routes-chatcodingroute mentalStateBadge_editing min-w-0",
  mentalStateBadge_error:
    `vui-routes-chatcodingroute mentalStateBadge_error min-w-0 ${vuiStateDangerSoftClass}`,
  mentalStateBadge_failed:
    `vui-routes-chatcodingroute mentalStateBadge_failed min-w-0 ${vuiStateDangerSoftClass}`,
  mentalStateBadge_general:
    "vui-routes-chatcodingroute mentalStateBadge_general min-w-0",
  mentalStateBadge_healthy:
    "vui-routes-chatcodingroute mentalStateBadge_healthy min-w-0",
  mentalStateBadge_idle:
    "vui-routes-chatcodingroute mentalStateBadge_idle min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-tertiary)]",
  mentalStateBadge_info:
    `vui-routes-chatcodingroute mentalStateBadge_info min-w-0 ${vuiStateCoolInfoClass}`,
  mentalStateBadge_lobster:
    "vui-routes-chatcodingroute mentalStateBadge_lobster min-w-0",
  mentalStateBadge_looping:
    "vui-routes-chatcodingroute mentalStateBadge_looping min-w-0",
  mentalStateBadge_memory:
    "vui-routes-chatcodingroute mentalStateBadge_memory min-w-0",
  mentalStateBadge_mental:
    "vui-routes-chatcodingroute mentalStateBadge_mental min-w-0",
  mentalStateBadge_missing:
    "vui-routes-chatcodingroute mentalStateBadge_missing min-w-0",
  mentalStateBadge_modelInput:
    "vui-routes-chatcodingroute mentalStateBadge_modelInput min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  mentalStateBadge_moose:
    "vui-routes-chatcodingroute mentalStateBadge_moose min-w-0",
  mentalStateBadge_muted:
    "vui-routes-chatcodingroute mentalStateBadge_muted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  mentalStateBadge_needs_input:
    "vui-routes-chatcodingroute mentalStateBadge_needs_input min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  mentalStateBadge_neutral:
    "vui-routes-chatcodingroute mentalStateBadge_neutral min-w-0",
  mentalStateBadge_normal:
    "vui-routes-chatcodingroute mentalStateBadge_normal min-w-0",
  mentalStateBadge_offline:
    "vui-routes-chatcodingroute mentalStateBadge_offline min-w-0",
  mentalStateBadge_ok:
    `vui-routes-chatcodingroute mentalStateBadge_ok min-w-0 ${vuiStateSuccessSoftClass}`,
  mentalStateBadge_pending:
    "vui-routes-chatcodingroute mentalStateBadge_pending min-w-0",
  mentalStateBadge_penguin:
    "vui-routes-chatcodingroute mentalStateBadge_penguin min-w-0",
  mentalStateBadge_planning:
    "vui-routes-chatcodingroute mentalStateBadge_planning min-w-0",
  mentalStateBadge_productive:
    "vui-routes-chatcodingroute mentalStateBadge_productive min-w-0",
  mentalStateBadge_reading:
    "vui-routes-chatcodingroute mentalStateBadge_reading min-w-0",
  mentalStateBadge_ready:
    `vui-routes-chatcodingroute mentalStateBadge_ready min-w-0 ${vuiStateSuccessSoftClass}`,
  mentalStateBadge_research:
    "vui-routes-chatcodingroute mentalStateBadge_research min-w-0",
  mentalStateBadge_running:
    `vui-routes-chatcodingroute mentalStateBadge_running min-w-0 ${vuiStateSuccessSoftClass}`,
  mentalStateBadge_self:
    "vui-routes-chatcodingroute mentalStateBadge_self min-w-0",
  mentalStateBadge_shrimp:
    "vui-routes-chatcodingroute mentalStateBadge_shrimp min-w-0",
  mentalStateBadge_slime:
    "vui-routes-chatcodingroute mentalStateBadge_slime min-w-0",
  mentalStateBadge_stale:
    "vui-routes-chatcodingroute mentalStateBadge_stale min-w-0",
  mentalStateBadge_status:
    "vui-routes-chatcodingroute mentalStateBadge_status min-w-0",
  mentalStateBadge_success:
    `vui-routes-chatcodingroute mentalStateBadge_success min-w-0 ${vuiStateSuccessSoftClass}`,
  mentalStateBadge_supervised:
    "vui-routes-chatcodingroute mentalStateBadge_supervised min-w-0",
  mentalStateBadge_thinking:
    "vui-routes-chatcodingroute mentalStateBadge_thinking min-w-0",
  mentalStateBadge_thought:
    "vui-routes-chatcodingroute mentalStateBadge_thought min-w-0",
  mentalStateBadge_thrashing:
    "vui-routes-chatcodingroute mentalStateBadge_thrashing min-w-0",
  mentalStateBadge_tool:
    `vui-routes-chatcodingroute mentalStateBadge_tool min-w-0 ${vuiStateWarmSoftClass}`,
  mentalStateBadge_tooling:
    "vui-routes-chatcodingroute mentalStateBadge_tooling min-w-0",
  mentalStateBadge_tunnel_vision:
    "vui-routes-chatcodingroute mentalStateBadge_tunnel_vision min-w-0",
  mentalStateBadge_unhealthy:
    "vui-routes-chatcodingroute mentalStateBadge_unhealthy min-w-0",
  mentalStateBadge_unknown:
    "vui-routes-chatcodingroute mentalStateBadge_unknown min-w-0",
  mentalStateBadge_verifying:
    "vui-routes-chatcodingroute mentalStateBadge_verifying min-w-0",
  mentalStateBadge_waiting:
    "vui-routes-chatcodingroute mentalStateBadge_waiting min-w-0",
  mentalStateBadge_warn:
    "vui-routes-chatcodingroute mentalStateBadge_warn min-w-0",
  mentalStateBadge_warning:
    `vui-routes-chatcodingroute mentalStateBadge_warning min-w-0 ${vuiStateWarningSoftClass}`,
  petMiniAvatar:
    "vui-routes-chatcodingroute petMiniAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseAction:
    "vui-routes-chatcodingroute petShowcaseAction min-w-0 !grid !h-auto min-h-[30px] !w-full grid-cols-[14px_minmax(0,1fr)] items-center gap-1 rounded-[var(--radius-control)] px-1.5 py-1 [font-size:var(--vui-font-sm)] [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents [&_span]:min-w-0 [&_span]:whitespace-normal [&_span]:leading-tight [&_span]:[overflow-wrap:anywhere] [&_svg]:shrink-0",
  petShowcaseActionHint:
    "vui-routes-chatcodingroute petShowcaseActionHint min-w-0 flex flex-wrap items-center gap-1.5 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  petShowcaseActions:
    "vui-routes-chatcodingroute petShowcaseActions min-w-0 !grid grid-cols-3 gap-1",
  petShowcaseAvatar:
    "vui-routes-chatcodingroute petShowcaseAvatar min-w-0 inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]",
  petShowcaseEarLeft:
    "vui-routes-chatcodingroute petShowcaseEarLeft min-w-0",
  petShowcaseEarRight:
    "vui-routes-chatcodingroute petShowcaseEarRight min-w-0",
  petShowcaseEye:
    "vui-routes-chatcodingroute petShowcaseEye min-w-0",
  petShowcaseFace:
    "vui-routes-chatcodingroute petShowcaseFace min-w-0",
  petShowcaseFeedback:
    "vui-routes-chatcodingroute petShowcaseFeedback min-w-0 rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--accent-cool)_20%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_6%,transparent)] px-1.5 py-1 [font-size:var(--vui-font-sm)] leading-snug text-[var(--fg-secondary)]",
  petShowcaseFootLeft:
    "vui-routes-chatcodingroute petShowcaseFootLeft min-w-0",
  petShowcaseFootRight:
    "vui-routes-chatcodingroute petShowcaseFootRight min-w-0",
  petShowcaseMuzzle:
    "vui-routes-chatcodingroute petShowcaseMuzzle min-w-0",
  petShowcaseSymbol:
    "vui-routes-chatcodingroute petShowcaseSymbol min-w-0",
  runModeBlock:
    "vui-routes-chatcodingroute runModeBlock min-w-0",
  sessionBindingNotice: `vui-routes-chatcodingroute sessionBindingNotice min-w-0 ${vuiGlassPanelClass} p-2 !grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1.5`,
  sessionStatePill:
    `vui-routes-chatcodingroute sessionStatePill min-w-0 ${vuiControlPillClass}`,
  sessionStatePill_active:
    `vui-routes-chatcodingroute sessionStatePill_active min-w-0 ${vuiStateSelectedRowClass}`,
  sessionStatePill_answering:
    "vui-routes-chatcodingroute sessionStatePill_answering min-w-0",
  sessionStatePill_blocked:
    `vui-routes-chatcodingroute sessionStatePill_blocked min-w-0 ${vuiStateWarningSoftClass}`,
  sessionStatePill_bunny:
    "vui-routes-chatcodingroute sessionStatePill_bunny min-w-0",
  sessionStatePill_cache:
    "vui-routes-chatcodingroute sessionStatePill_cache min-w-0",
  sessionStatePill_cat:
    "vui-routes-chatcodingroute sessionStatePill_cat min-w-0",
  sessionStatePill_chat:
    "vui-routes-chatcodingroute sessionStatePill_chat min-w-0",
  sessionStatePill_checking:
    "vui-routes-chatcodingroute sessionStatePill_checking min-w-0",
  sessionStatePill_chick:
    "vui-routes-chatcodingroute sessionStatePill_chick min-w-0",
  sessionStatePill_compression:
    "vui-routes-chatcodingroute sessionStatePill_compression min-w-0",
  sessionStatePill_crab:
    "vui-routes-chatcodingroute sessionStatePill_crab min-w-0",
  sessionStatePill_danger:
    `vui-routes-chatcodingroute sessionStatePill_danger min-w-0 ${vuiStateDangerSoftClass}`,
  sessionStatePill_default:
    "vui-routes-chatcodingroute sessionStatePill_default min-w-0",
  sessionStatePill_disoriented:
    "vui-routes-chatcodingroute sessionStatePill_disoriented min-w-0",
  sessionStatePill_done:
    "vui-routes-chatcodingroute sessionStatePill_done min-w-0",
  sessionStatePill_editing:
    "vui-routes-chatcodingroute sessionStatePill_editing min-w-0",
  sessionStatePill_error:
    `vui-routes-chatcodingroute sessionStatePill_error min-w-0 ${vuiStateDangerSoftClass}`,
  sessionStatePill_failed:
    `vui-routes-chatcodingroute sessionStatePill_failed min-w-0 ${vuiStateDangerSoftClass}`,
  sessionStatePill_general:
    "vui-routes-chatcodingroute sessionStatePill_general min-w-0",
  sessionStatePill_healthy:
    "vui-routes-chatcodingroute sessionStatePill_healthy min-w-0",
  sessionStatePill_idle:
    "vui-routes-chatcodingroute sessionStatePill_idle min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-tertiary)]",
  sessionStatePill_info:
    `vui-routes-chatcodingroute sessionStatePill_info min-w-0 ${vuiStateCoolInfoClass}`,
  sessionStatePill_lobster:
    "vui-routes-chatcodingroute sessionStatePill_lobster min-w-0",
  sessionStatePill_looping:
    "vui-routes-chatcodingroute sessionStatePill_looping min-w-0",
  sessionStatePill_memory:
    "vui-routes-chatcodingroute sessionStatePill_memory min-w-0",
  sessionStatePill_mental:
    "vui-routes-chatcodingroute sessionStatePill_mental min-w-0",
  sessionStatePill_missing:
    "vui-routes-chatcodingroute sessionStatePill_missing min-w-0",
  sessionStatePill_modelInput:
    "vui-routes-chatcodingroute sessionStatePill_modelInput min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  sessionStatePill_moose:
    "vui-routes-chatcodingroute sessionStatePill_moose min-w-0",
  sessionStatePill_muted:
    "vui-routes-chatcodingroute sessionStatePill_muted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  sessionStatePill_needs_input:
    "vui-routes-chatcodingroute sessionStatePill_needs_input min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  sessionStatePill_neutral:
    "vui-routes-chatcodingroute sessionStatePill_neutral min-w-0",
  sessionStatePill_normal:
    "vui-routes-chatcodingroute sessionStatePill_normal min-w-0",
  sessionStatePill_offline:
    "vui-routes-chatcodingroute sessionStatePill_offline min-w-0",
  sessionStatePill_ok:
    `vui-routes-chatcodingroute sessionStatePill_ok min-w-0 ${vuiStateSuccessSoftClass}`,
  sessionStatePill_pending:
    "vui-routes-chatcodingroute sessionStatePill_pending min-w-0",
  sessionStatePill_penguin:
    "vui-routes-chatcodingroute sessionStatePill_penguin min-w-0",
  sessionStatePill_planning:
    "vui-routes-chatcodingroute sessionStatePill_planning min-w-0",
  sessionStatePill_productive:
    "vui-routes-chatcodingroute sessionStatePill_productive min-w-0",
  sessionStatePill_reading:
    "vui-routes-chatcodingroute sessionStatePill_reading min-w-0",
  sessionStatePill_ready:
    `vui-routes-chatcodingroute sessionStatePill_ready min-w-0 ${vuiStateSuccessSoftClass}`,
  sessionStatePill_research:
    "vui-routes-chatcodingroute sessionStatePill_research min-w-0",
  sessionStatePill_running:
    `vui-routes-chatcodingroute sessionStatePill_running min-w-0 ${vuiStateSuccessSoftClass}`,
  sessionStatePill_self:
    "vui-routes-chatcodingroute sessionStatePill_self min-w-0",
  sessionStatePill_shrimp:
    "vui-routes-chatcodingroute sessionStatePill_shrimp min-w-0",
  sessionStatePill_slime:
    "vui-routes-chatcodingroute sessionStatePill_slime min-w-0",
  sessionStatePill_stale:
    "vui-routes-chatcodingroute sessionStatePill_stale min-w-0",
  sessionStatePill_status:
    "vui-routes-chatcodingroute sessionStatePill_status min-w-0",
  sessionStatePill_success:
    `vui-routes-chatcodingroute sessionStatePill_success min-w-0 ${vuiStateSuccessSoftClass}`,
  sessionStatePill_supervised:
    "vui-routes-chatcodingroute sessionStatePill_supervised min-w-0",
  sessionStatePill_thinking:
    "vui-routes-chatcodingroute sessionStatePill_thinking min-w-0",
  sessionStatePill_thought:
    "vui-routes-chatcodingroute sessionStatePill_thought min-w-0",
  sessionStatePill_thrashing:
    "vui-routes-chatcodingroute sessionStatePill_thrashing min-w-0",
  sessionStatePill_tool:
    `vui-routes-chatcodingroute sessionStatePill_tool min-w-0 ${vuiStateWarmSoftClass}`,
  sessionStatePill_tooling:
    "vui-routes-chatcodingroute sessionStatePill_tooling min-w-0",
  sessionStatePill_tunnel_vision:
    "vui-routes-chatcodingroute sessionStatePill_tunnel_vision min-w-0",
  sessionStatePill_unhealthy:
    "vui-routes-chatcodingroute sessionStatePill_unhealthy min-w-0",
  sessionStatePill_unknown:
    "vui-routes-chatcodingroute sessionStatePill_unknown min-w-0",
  sessionStatePill_verifying:
    "vui-routes-chatcodingroute sessionStatePill_verifying min-w-0",
  sessionStatePill_waiting:
    "vui-routes-chatcodingroute sessionStatePill_waiting min-w-0",
  sessionStatePill_warn:
    "vui-routes-chatcodingroute sessionStatePill_warn min-w-0",
  sessionStatePill_warning:
    `vui-routes-chatcodingroute sessionStatePill_warning min-w-0 ${vuiStateWarningSoftClass}`,
};

export default styles;
