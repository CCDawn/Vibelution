// Wave 8C: extracted from ChatCodingRoute.styles for TokenCoreStatusPanel.tsx

import {
  vuiStateCoolInfoClass,
  vuiStateDangerSoftClass,
  vuiStateSelectedRowClass,
  vuiStateSuccessSoftClass,
  vuiStateWarmSoftClass,
  vuiStateWarningSoftClass,
} from "../../design/vuiSurfaceRecipes";

const styles: Record<string, string> = {
  tokenCompressionCard:
    "vui-routes-chatcodingroute tokenCompressionCard min-w-0",
  tokenStatusBar:
    "vui-routes-chatcodingroute tokenStatusBar relative mt-1.5 block h-1.5 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--vui-border-subtle)_78%,transparent)] [&>span]:block [&>span]:h-full [&>span]:rounded-full [&>span]:bg-[var(--accent-cool)] [&>span]:w-[calc(var(--token-status-value)*1%)]",
  tokenStatusCopy:
    "vui-routes-chatcodingroute tokenStatusCopy grid min-w-0 self-center gap-0.5 overflow-visible text-center",
  tokenStatusLabel:
    "vui-routes-chatcodingroute tokenStatusLabel block min-w-0 max-w-full truncate whitespace-nowrap text-[11px] font-semibold leading-none text-vui-fg-primary",
  tokenStatusMeta:
    "vui-routes-chatcodingroute tokenStatusMeta sr-only",
  tokenStatusMetric:
    "vui-routes-chatcodingroute tokenStatusMetric !grid min-h-[64px] !w-full grid-cols-1 grid-rows-[28px_minmax(0,1fr)] place-items-center justify-stretch gap-1 overflow-visible rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--vui-border-strong)_60%,transparent)] bg-[var(--vui-surface-raised)] px-1 py-1.5 text-center shadow-none",
  tokenStatusMetricButton:
    "vui-routes-chatcodingroute tokenStatusMetricButton !grid !h-full !min-h-0 !w-full !border-0 !bg-transparent !p-0 !text-inherit !shadow-none [&_[data-slot=vui-button-content]]:contents [&_[data-slot=vui-button-label]]:contents",
  tokenStatusMetric_active:
    `vui-routes-chatcodingroute tokenStatusMetric_active min-w-0 ${vuiStateSelectedRowClass}`,
  tokenStatusMetric_answering:
    "vui-routes-chatcodingroute tokenStatusMetric_answering min-w-0",
  tokenStatusMetric_blocked:
    `vui-routes-chatcodingroute tokenStatusMetric_blocked min-w-0 ${vuiStateWarningSoftClass}`,
  tokenStatusMetric_bunny:
    "vui-routes-chatcodingroute tokenStatusMetric_bunny min-w-0",
  tokenStatusMetric_cache:
    "vui-routes-chatcodingroute tokenStatusMetric_cache border-[color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_7%,var(--vui-control-muted))]",
  tokenStatusMetric_cat:
    "vui-routes-chatcodingroute tokenStatusMetric_cat min-w-0",
  tokenStatusMetric_chat:
    "vui-routes-chatcodingroute tokenStatusMetric_chat min-w-0",
  tokenStatusMetric_checking:
    "vui-routes-chatcodingroute tokenStatusMetric_checking min-w-0",
  tokenStatusMetric_chick:
    "vui-routes-chatcodingroute tokenStatusMetric_chick min-w-0",
  tokenStatusMetric_compression:
    "vui-routes-chatcodingroute tokenStatusMetric_compression border-[color-mix(in_srgb,var(--accent-warm)_24%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-warm)_7%,var(--vui-control-muted))]",
  tokenStatusMetric_crab:
    "vui-routes-chatcodingroute tokenStatusMetric_crab min-w-0",
  tokenStatusMetric_danger:
    `vui-routes-chatcodingroute tokenStatusMetric_danger min-w-0 ${vuiStateDangerSoftClass}`,
  tokenStatusMetric_default:
    "vui-routes-chatcodingroute tokenStatusMetric_default min-w-0",
  tokenStatusMetric_disoriented:
    "vui-routes-chatcodingroute tokenStatusMetric_disoriented min-w-0",
  tokenStatusMetric_done:
    "vui-routes-chatcodingroute tokenStatusMetric_done min-w-0",
  tokenStatusMetric_editing:
    "vui-routes-chatcodingroute tokenStatusMetric_editing min-w-0",
  tokenStatusMetric_error:
    `vui-routes-chatcodingroute tokenStatusMetric_error min-w-0 ${vuiStateDangerSoftClass}`,
  tokenStatusMetric_failed:
    `vui-routes-chatcodingroute tokenStatusMetric_failed min-w-0 ${vuiStateDangerSoftClass}`,
  tokenStatusMetric_general:
    "vui-routes-chatcodingroute tokenStatusMetric_general min-w-0",
  tokenStatusMetric_healthy:
    "vui-routes-chatcodingroute tokenStatusMetric_healthy min-w-0",
  tokenStatusMetric_idle:
    "vui-routes-chatcodingroute tokenStatusMetric_idle min-w-0 border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-tertiary)]",
  tokenStatusMetric_info:
    `vui-routes-chatcodingroute tokenStatusMetric_info min-w-0 ${vuiStateCoolInfoClass}`,
  tokenStatusMetric_lobster:
    "vui-routes-chatcodingroute tokenStatusMetric_lobster min-w-0",
  tokenStatusMetric_looping:
    "vui-routes-chatcodingroute tokenStatusMetric_looping min-w-0",
  tokenStatusMetric_memory:
    "vui-routes-chatcodingroute tokenStatusMetric_memory min-w-0",
  tokenStatusMetric_mental:
    "vui-routes-chatcodingroute tokenStatusMetric_mental min-w-0",
  tokenStatusMetric_missing:
    "vui-routes-chatcodingroute tokenStatusMetric_missing min-w-0",
  tokenStatusMetric_modelInput:
    "vui-routes-chatcodingroute tokenStatusMetric_modelInput border-[color-mix(in_srgb,var(--state-success)_22%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--state-success)_7%,var(--vui-control-muted))]",
  tokenStatusMetric_moose:
    "vui-routes-chatcodingroute tokenStatusMetric_moose min-w-0",
  tokenStatusMetric_muted:
    "vui-routes-chatcodingroute tokenStatusMetric_muted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  tokenStatusMetric_needs_input:
    "vui-routes-chatcodingroute tokenStatusMetric_needs_input min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  tokenStatusMetric_neutral:
    "vui-routes-chatcodingroute tokenStatusMetric_neutral min-w-0",
  tokenStatusMetric_normal:
    "vui-routes-chatcodingroute tokenStatusMetric_normal min-w-0",
  tokenStatusMetric_offline:
    "vui-routes-chatcodingroute tokenStatusMetric_offline min-w-0",
  tokenStatusMetric_ok:
    `vui-routes-chatcodingroute tokenStatusMetric_ok min-w-0 ${vuiStateSuccessSoftClass}`,
  tokenStatusMetric_pending:
    "vui-routes-chatcodingroute tokenStatusMetric_pending min-w-0",
  tokenStatusMetric_penguin:
    "vui-routes-chatcodingroute tokenStatusMetric_penguin min-w-0",
  tokenStatusMetric_planning:
    "vui-routes-chatcodingroute tokenStatusMetric_planning min-w-0",
  tokenStatusMetric_productive:
    "vui-routes-chatcodingroute tokenStatusMetric_productive min-w-0",
  tokenStatusMetric_reading:
    "vui-routes-chatcodingroute tokenStatusMetric_reading min-w-0",
  tokenStatusMetric_ready:
    `vui-routes-chatcodingroute tokenStatusMetric_ready min-w-0 ${vuiStateSuccessSoftClass}`,
  tokenStatusMetric_research:
    "vui-routes-chatcodingroute tokenStatusMetric_research min-w-0",
  tokenStatusMetric_running:
    `vui-routes-chatcodingroute tokenStatusMetric_running min-w-0 ${vuiStateSuccessSoftClass}`,
  tokenStatusMetric_self:
    "vui-routes-chatcodingroute tokenStatusMetric_self min-w-0",
  tokenStatusMetric_shrimp:
    "vui-routes-chatcodingroute tokenStatusMetric_shrimp min-w-0",
  tokenStatusMetric_slime:
    "vui-routes-chatcodingroute tokenStatusMetric_slime min-w-0",
  tokenStatusMetric_speed:
    "vui-routes-chatcodingroute tokenStatusMetric_speed border-[color-mix(in_srgb,var(--accent-cool)_22%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_6%,var(--vui-control-muted))]",
  tokenStatusMetric_stale:
    "vui-routes-chatcodingroute tokenStatusMetric_stale min-w-0",
  tokenStatusMetric_status:
    "vui-routes-chatcodingroute tokenStatusMetric_status min-w-0",
  tokenStatusMetric_success:
    `vui-routes-chatcodingroute tokenStatusMetric_success min-w-0 ${vuiStateSuccessSoftClass}`,
  tokenStatusMetric_supervised:
    "vui-routes-chatcodingroute tokenStatusMetric_supervised min-w-0",
  tokenStatusMetric_thinking:
    "vui-routes-chatcodingroute tokenStatusMetric_thinking min-w-0",
  tokenStatusMetric_thought:
    "vui-routes-chatcodingroute tokenStatusMetric_thought min-w-0",
  tokenStatusMetric_thrashing:
    "vui-routes-chatcodingroute tokenStatusMetric_thrashing min-w-0",
  tokenStatusMetric_tool:
    `vui-routes-chatcodingroute tokenStatusMetric_tool min-w-0 ${vuiStateWarmSoftClass}`,
  tokenStatusMetric_tooling:
    "vui-routes-chatcodingroute tokenStatusMetric_tooling min-w-0",
  tokenStatusMetric_tunnel_vision:
    "vui-routes-chatcodingroute tokenStatusMetric_tunnel_vision min-w-0",
  tokenStatusMetric_unhealthy:
    "vui-routes-chatcodingroute tokenStatusMetric_unhealthy min-w-0",
  tokenStatusMetric_unknown:
    "vui-routes-chatcodingroute tokenStatusMetric_unknown min-w-0",
  tokenStatusMetric_verifying:
    "vui-routes-chatcodingroute tokenStatusMetric_verifying min-w-0",
  tokenStatusMetric_waiting:
    "vui-routes-chatcodingroute tokenStatusMetric_waiting min-w-0",
  tokenStatusMetric_warn:
    "vui-routes-chatcodingroute tokenStatusMetric_warn min-w-0",
  tokenStatusMetric_warning:
    `vui-routes-chatcodingroute tokenStatusMetric_warning min-w-0 ${vuiStateWarningSoftClass}`,
  tokenStatusRing:
    "vui-routes-chatcodingroute tokenStatusRing relative size-[28px] shrink-0 rounded-full bg-[conic-gradient(var(--accent-cool)_calc(var(--token-status-value)*1%),var(--vui-border-subtle)_0)]",
  tokenStatusRingCore:
    "vui-routes-chatcodingroute tokenStatusRingCore absolute inset-[3px] grid max-w-full place-items-center overflow-hidden text-ellipsis rounded-full bg-[var(--vui-surface-panel)] px-0.5 text-center text-[10px] font-bold leading-none text-vui-fg-primary",
  tokenStatusVisualGrid:
    "vui-routes-chatcodingroute tokenStatusVisualGrid !grid w-full grid-cols-[repeat(4,minmax(0,1fr))] justify-stretch gap-1.5 rounded-[var(--radius-control)]",
};

export default styles;
