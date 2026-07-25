// Wave 8F: research cluster extracted from TeamsRoute.styles

import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiStateCoolSoftClass,
  vuiStateSelectedRowClass,
  vuiStateSelectedRowFillClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  knowledgeCompletionFlowActions:
    "knowledgeCompletionFlowActions min-w-0 flex flex-wrap items-center gap-1.5 !flex flex-wrap items-center gap-1.5 min-w-0 mt-auto [&_a]:inline-flex [&_a]:w-fit [&_a]:max-w-full [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:min-h-[28px] [&_a]:px-2.5 [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_32%,var(--border-soft))] [&_a]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))] [&_a]:text-[var(--fg-primary)] [&_a]:font-[780] [&_a]:no-underline [&_a]:whitespace-nowrap [&_[data-vui=native-button]]:inline-flex [&_[data-vui=native-button]]:w-fit [&_[data-vui=native-button]]:max-w-full [&_[data-vui=native-button]]:items-center [&_[data-vui=native-button]]:justify-center [&_[data-vui=native-button]]:gap-1.5 [&_[data-vui=native-button]]:min-h-[28px] [&_[data-vui=native-button]]:px-2.5 [&_[data-vui=native-button]]:rounded-[7px] [&_[data-vui=native-button]]:border [&_[data-vui=native-button]]:border-[color:color-mix(in_srgb,var(--accent-cool)_32%,var(--border-soft))] [&_[data-vui=native-button]]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))] [&_[data-vui=native-button]]:text-[var(--fg-primary)] [&_[data-vui=native-button]]:font-[780]",
  knowledgeCompletionFlowError:
    "knowledgeCompletionFlowError min-w-0 break-words rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] px-2 py-1 [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--state-error)]",
  knowledgeCompletionFlowHeader:
    "knowledgeCompletionFlowHeader min-w-0 !grid grid-cols-[minmax(0,1fr)_auto] items-start gap-2 max-[680px]:grid-cols-[minmax(0,1fr)] [&>div]:grid [&>div]:min-w-0 [&>div]:gap-1 [&_span]:min-w-0 [&_span]:break-words [&_span]:[font-size:var(--vui-font-sm)] [&_span]:leading-[var(--vui-line-readable)]",
  knowledgeCompletionFlowNode: `knowledgeCompletionFlowNode min-w-0 grid min-h-[164px] grid-rows-[auto_minmax(0,1fr)_auto] gap-2 ${vuiOpaqueRowClass} p-2`,
  knowledgeCompletionFlowNodeBody:
    "knowledgeCompletionFlowNodeBody min-w-0 grid content-start gap-1 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)] [&_b]:min-w-0 [&_b]:break-words [&_small]:min-w-0 [&_small]:break-words [&_em]:not-italic [&_p]:m-0 [&_p]:max-w-[min(100%,72ch)] [&_p]:break-words",
  knowledgeCompletionFlowNodeCurrent:
    `knowledgeCompletionFlowNodeCurrent min-w-0 ${vuiStateCoolSoftClass}`,
  knowledgeCompletionFlowNodeHeader:
    "knowledgeCompletionFlowNodeHeader min-w-0 flex flex-wrap items-center gap-1.5 [&_strong]:shrink-0 [&_span]:min-w-0 [&_span]:truncate",
  knowledgeCompletionFlowNodes:
    "knowledgeCompletionFlowNodes min-w-0 !grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] items-stretch gap-2",
  knowledgeCompletionFlowPanel: `knowledgeCompletionFlowPanel min-w-0 grid gap-2 overflow-hidden ${vuiFlatPanelClass} p-2`,
  researchCanvasPanelHidden: `researchCanvasPanelHidden min-w-0 grid min-h-0 gap-2 p-2 ${vuiFlatPanelClass} hidden !hidden`,
  researchDiscussionPanel: `researchDiscussionPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  researchInspector:
    "researchInspector min-w-0",
  researchLoopActive:
    `researchLoopActive min-w-0 ${vuiStateSelectedRowClass}`,
  researchLoopDecisionForm:
    "researchLoopDecisionForm min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  researchLoopEvidenceForm:
    "researchLoopEvidenceForm min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  researchLoopHeader:
    "researchLoopHeader min-w-0 flex flex-wrap items-center gap-1.5",
  researchLoopOutcomeGrid:
    "researchLoopOutcomeGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  researchLoopPanel: `researchLoopPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  researchLoopStats:
    "researchLoopStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  researchLoopStatusPills:
    "researchLoopStatusPills min-w-0",
  researchLoopTemplateBar:
    "researchLoopTemplateBar min-w-0 flex flex-wrap items-center gap-1.5",
  researchLoopTemplateSummary: `researchLoopTemplateSummary min-w-0 ${vuiFlatPanelClass} p-2`,
  researchLoopWide:
    "researchLoopWide min-w-0",
  researchStageActionPanel: `researchStageActionPanel min-w-0 ${vuiFlatPanelClass} p-2 flex flex-wrap items-center gap-1.5`,
  researchStageActions:
    "researchStageActions min-w-0 mt-auto flex flex-wrap items-center gap-2 border-t border-[var(--vui-border-subtle)] pt-2 [&_a]:inline-flex [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:min-h-8 [&_a]:px-2.5 [&_a]:rounded-[var(--radius-control)] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_32%,var(--border-soft))] [&_a]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))] [&_a]:text-[var(--fg-primary)] [&_a]:font-[780] [&_a]:no-underline [&_a]:whitespace-nowrap [&_[data-vui=native-button]]:inline-flex [&_[data-vui=native-button]]:items-center [&_[data-vui=native-button]]:justify-center [&_[data-vui=native-button]]:gap-1.5 [&_[data-vui=native-button]]:min-h-8 [&_[data-vui=native-button]]:px-2.5 [&_[data-vui=native-button]]:rounded-[var(--radius-control)] [&_[data-vui=native-button]]:border [&_[data-vui=native-button]]:border-[color:color-mix(in_srgb,var(--accent-cool)_32%,var(--border-soft))] [&_[data-vui=native-button]]:bg-[color:color-mix(in_srgb,var(--accent-cool)_8%,var(--vui-surface-panel))] [&_[data-vui=native-button]]:text-[var(--fg-primary)] [&_[data-vui=native-button]]:font-[780]",
  researchStageAgentActions:
    "researchStageAgentActions min-w-0 flex flex-wrap items-center gap-1.5 text-[var(--fg-secondary)] !flex min-w-0 items-center justify-between gap-2 [&_a]:inline-flex [&_a]:shrink-0 [&_a]:min-h-[28px] [&_a]:items-center [&_a]:justify-center [&_a]:gap-[5px] [&_a]:px-[9px] [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_28%,var(--border-soft))] [&_a]:!bg-[var(--vui-surface-row)] [&_a]:text-[var(--fg-primary)] [&_a]:font-[780] [&_a]:no-underline [&_a]:whitespace-nowrap",
  researchStageAgentCard: `researchStageAgentCard min-w-0 ${vuiOpaqueRowClass} p-1.5 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]`,
  researchStageAgentCard_acquire:
    "researchStageAgentCard_acquire min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_active:
    "researchStageAgentCard_active min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_blocked:
    "researchStageAgentCard_blocked min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] text-[var(--state-error)]",
  researchStageAgentCard_cache:
    "researchStageAgentCard_cache min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_danger:
    "researchStageAgentCard_danger min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] text-[var(--state-error)]",
  researchStageAgentCard_done:
    "researchStageAgentCard_done min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] text-[var(--state-success)]",
  researchStageAgentCard_error:
    "researchStageAgentCard_error min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] text-[var(--state-error)]",
  researchStageAgentCard_extract:
    "researchStageAgentCard_extract min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_failed:
    "researchStageAgentCard_failed min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] text-[var(--state-error)]",
  researchStageAgentCard_idle:
    "researchStageAgentCard_idle min-w-0 border-[var(--vui-border-subtle)] text-[var(--fg-tertiary)]",
  researchStageAgentCard_info:
    "researchStageAgentCard_info min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_mental:
    "researchStageAgentCard_mental min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_missing:
    "researchStageAgentCard_missing min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] text-[var(--state-warning)]",
  researchStageAgentCard_muted:
    "researchStageAgentCard_muted min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)] border-[var(--vui-border-subtle)]",
  researchStageAgentCard_neutral:
    "researchStageAgentCard_neutral min-w-0 border-[var(--vui-border-subtle)] text-[var(--fg-secondary)]",
  researchStageAgentCard_ok:
    "researchStageAgentCard_ok min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] text-[var(--state-success)]",
  researchStageAgentCard_pending:
    "researchStageAgentCard_pending min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] text-[var(--state-warning)]",
  researchStageAgentCard_plan:
    "researchStageAgentCard_plan min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_quality:
    "researchStageAgentCard_quality min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_ready:
    "researchStageAgentCard_ready min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] text-[var(--state-success)]",
  researchStageAgentCard_running:
    "researchStageAgentCard_running min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_search:
    "researchStageAgentCard_search min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_status:
    "researchStageAgentCard_status min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_storage:
    "researchStageAgentCard_storage min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_success:
    "researchStageAgentCard_success min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] text-[var(--state-success)]",
  researchStageAgentCard_thought:
    "researchStageAgentCard_thought min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentCard_warn:
    "researchStageAgentCard_warn min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] text-[var(--state-warning)]",
  researchStageAgentCard_warning:
    "researchStageAgentCard_warning min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] text-[var(--state-warning)]",
  researchStageAgentGrid:
    "researchStageAgentGrid min-w-0 grid gap-2 text-[var(--fg-secondary)] !grid grid-cols-[repeat(auto-fit,minmax(210px,1fr))] gap-2",
  researchStageAgentMeta:
    "researchStageAgentMeta min-w-0 flex flex-wrap items-center gap-1.5 text-[var(--fg-secondary)]",
  researchStageAgentPanel: `researchStageAgentPanel min-w-0 ${vuiOpaqueRowClass} p-1.5 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]`,
  researchStageAgentPanelCompact:
    "researchStageAgentPanelCompact min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)]",
  researchStageAgentPanelHeader: `researchStageAgentPanelHeader min-w-0 ${vuiOpaqueRowClass} p-1.5 flex flex-wrap items-center gap-1.5 border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] text-[var(--accent-cool)] !flex min-w-0 items-center justify-between gap-2.5 [&>div]:grid [&>div]:min-w-0 [&>div]:gap-0.5 [&>div_strong]:truncate [&>div_strong]:text-[var(--fg-primary)] [&>div_span]:truncate [&>div_span]:text-[var(--fg-muted)] [&>div_span]:font-[760] [&_a]:inline-flex [&_a]:shrink-0 [&_a]:min-h-[28px] [&_a]:items-center [&_a]:justify-center [&_a]:gap-[5px] [&_a]:px-[9px] [&_a]:rounded-[7px] [&_a]:border [&_a]:border-[color:color-mix(in_srgb,var(--accent-cool)_28%,var(--border-soft))] [&_a]:!bg-[var(--vui-surface-row)] [&_a]:text-[var(--fg-primary)] [&_a]:font-[780] [&_a]:no-underline [&_a]:whitespace-nowrap`,
  researchStageAgentRole:
    "researchStageAgentRole min-w-0 text-[var(--fg-primary)]",
  researchStageAgentSummary:
    "researchStageAgentSummary min-w-0 inline-flex w-fit max-w-full items-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--fg-secondary)]",
  researchStageAgentSummaryBlocked:
    "researchStageAgentSummaryBlocked min-w-0 border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] text-[var(--state-error)]",
  researchStageAgentSummaryMissing:
    "researchStageAgentSummaryMissing min-w-0 border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] text-[var(--state-warning)]",
  researchStageAgentSummaryReady:
    "researchStageAgentSummaryReady min-w-0 border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] text-[var(--state-success)]",
  researchStageAgentSummaryLoading:
    "researchStageAgentSummaryLoading min-w-0 border-[var(--vui-border-subtle)] text-[var(--fg-muted)]",
  researchStageBoundaryPanel: `researchStageBoundaryPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  researchStageCard:
    "researchStageCard min-w-0 flex h-full flex-col gap-2 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] p-3",
  researchStageCardActive:
    `researchStageCardActive min-w-0 border-[color-mix(in_srgb,var(--accent-cool)_44%,var(--vui-border-subtle))] ${vuiStateSelectedRowFillClass}`,
  researchStageCardHead:
    "researchStageCardHead min-w-0 !grid grid-cols-[auto_minmax(0,1fr)] items-center gap-2.5 [&>small]:inline-flex [&>small]:h-7 [&>small]:w-7 [&>small]:items-center [&>small]:justify-center [&>small]:rounded-full [&>small]:bg-[var(--vui-control-muted)] [&>small]:font-[820] [&>small]:text-[var(--fg-muted)] [&>div]:grid [&>div]:gap-1",
  researchStageCardMetrics:
    "researchStageCardMetrics min-w-0 !grid grid-cols-[repeat(3,minmax(0,1fr))] gap-x-2 gap-y-1 rounded-[var(--radius-control)] bg-[var(--vui-control-muted)] px-2 py-1.5 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)]",
  challengeWorkspaceBody:
    "challengeWorkspaceBody min-w-0 w-full flex-1 !flex min-h-0 flex-col !gap-0 !overflow-auto !p-0 [scrollbar-gutter:stable]",
  challengeWorkspaceContextHidden:
    "challengeWorkspaceContextHidden hidden !hidden",
  challengeWorkspaceInspector:
    "challengeWorkspaceInspector min-w-0 w-full flex-1 !overflow-hidden !border-0 !bg-transparent",
  challengeWorkspaceLayout:
    "challengeWorkspaceLayout min-w-0 w-full flex-1 !grid !grid-cols-[minmax(0,1fr)] !overflow-hidden !border-0 !bg-vui-surface-base !p-0",
  researchStageGrid:
    "researchStageGrid min-w-0 grid items-stretch gap-3 grid-cols-[repeat(auto-fit,minmax(280px,1fr))]",
  researchExperimentMethodQuickSelect:
    "researchExperimentMethodQuickSelect min-w-0 grid gap-2 rounded-[var(--radius-control)] border border-[color:color-mix(in_srgb,var(--accent-cool)_24%,var(--vui-border-subtle))] bg-[color:color-mix(in_srgb,var(--accent-cool)_5%,var(--vui-surface-panel))] p-2 [&>label]:grid [&>label]:min-w-0 [&>label]:gap-1 [&>label>span]:[font-size:var(--vui-font-xs)] [&>label>span]:font-semibold [&>label>span]:text-[var(--fg-secondary)] [&_select]:w-full [&>div]:flex [&>div]:min-w-0 [&>div]:flex-wrap [&>div]:items-center [&>div]:gap-2 [&>div>span]:[font-size:var(--vui-font-xs)] [&>div>a]:ml-auto [&>div>a]:inline-flex [&>div>a]:min-h-7 [&>div>a]:items-center [&>div>a]:gap-1 [&>div>a]:rounded-[var(--radius-control)] [&>div>a]:border [&>div>a]:border-[var(--vui-border-subtle)] [&>div>a]:px-2 [&>div>a]:[font-size:var(--vui-font-xs)] [&>div>a]:font-semibold [&>div>a]:text-[var(--fg-primary)]",
  researchExperimentMethodReady:
    "text-[var(--state-success)]",
  researchExperimentMethodPending:
    "text-[var(--state-warning)]",
  researchExperimentMethodReason:
    "m-0 line-clamp-2 [font-size:var(--vui-font-xs)] leading-[var(--vui-line-readable)] text-[var(--fg-tertiary)]",
  researchExperimentMethodAlternatives:
    "researchExperimentMethodAlternatives flex min-w-0 flex-wrap items-center gap-1.5 border-t border-[var(--vui-border-subtle)] pt-2 [&>span]:mr-0.5 [&>span]:[font-size:var(--vui-font-xs)] [&>span]:font-semibold [&>span]:text-[var(--fg-secondary)] [&>button]:min-h-7 [&>button]:w-fit [&>button]:rounded-[var(--radius-control)] [&>button]:border [&>button]:border-[var(--vui-border-subtle)] [&>button]:bg-[var(--vui-surface-panel)] [&>button]:px-2 [&>button]:[font-size:var(--vui-font-xs)] [&>button]:font-semibold",
  researchStageHeroPanel: `researchStageHeroPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  researchStageHeroStats:
    "researchStageHeroStats min-w-0 grid gap-2 !grid grid-cols-[repeat(3,minmax(0,1fr))] gap-2",
  researchStageLauncher: `researchStageLauncher min-w-0 grid content-start gap-3 ${vuiFlatPanelClass} p-3`,
  researchStageLauncherHeader:
    "researchStageLauncherHeader min-w-0 !flex flex-wrap items-center justify-between gap-3",
  researchStageHeaderActions:
    "researchStageHeaderActions min-w-0 flex flex-wrap items-center justify-end gap-1.5 [&_a]:inline-flex [&_a]:min-h-8 [&_a]:items-center [&_a]:justify-center [&_a]:gap-1.5 [&_a]:rounded-[var(--radius-control)] [&_a]:border [&_a]:border-[var(--vui-border-subtle)] [&_a]:bg-[var(--vui-control-muted)] [&_a]:px-2.5 [&_a]:font-[760] [&_a]:text-[var(--fg-primary)] [&_a]:no-underline [&_[data-vui=native-button]]:inline-flex [&_[data-vui=native-button]]:min-h-8 [&_[data-vui=native-button]]:items-center [&_[data-vui=native-button]]:justify-center [&_[data-vui=native-button]]:rounded-[var(--radius-control)] [&_[data-vui=native-button]]:border [&_[data-vui=native-button]]:border-[var(--vui-border-subtle)] [&_[data-vui=native-button]]:bg-[var(--vui-control-muted)] [&_[data-vui=native-button]]:px-2",
  researchStageDegradedNotice:
    "researchStageDegradedNotice min-w-0 !flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-control)] border border-[color:color-mix(in_srgb,var(--state-warning)_40%,var(--vui-border-subtle))] bg-[color:color-mix(in_srgb,var(--state-warning)_8%,var(--vui-surface-panel))] px-3 py-2 [font-size:var(--vui-font-sm)] text-[var(--fg-secondary)] [&_[data-vui=native-button]]:inline-flex [&_[data-vui=native-button]]:min-h-8 [&_[data-vui=native-button]]:items-center [&_[data-vui=native-button]]:justify-center [&_[data-vui=native-button]]:gap-1.5 [&_[data-vui=native-button]]:rounded-[var(--radius-control)] [&_[data-vui=native-button]]:border [&_[data-vui=native-button]]:border-[var(--vui-border-subtle)] [&_[data-vui=native-button]]:bg-[var(--vui-surface-panel)] [&_[data-vui=native-button]]:px-2.5",
  researchStageStatus:
    "researchStageStatus inline-flex w-fit max-w-full items-center rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-0.5 [font-size:var(--vui-font-xs)] font-[760] leading-tight text-[var(--fg-secondary)]",
  researchStageStatusActive:
    "researchStageStatusActive border-[color-mix(in_srgb,var(--accent-cool)_42%,var(--vui-border-subtle))] bg-[color:color-mix(in_srgb,var(--accent-cool)_12%,var(--vui-control-muted))] text-[var(--accent-cool)]",
  researchStageStatusPending:
    "researchStageStatusPending text-[var(--fg-muted)]",
  researchStageStatusRecorded:
    "researchStageStatusRecorded border-[color-mix(in_srgb,var(--state-success)_32%,var(--vui-border-subtle))] text-[var(--state-success)]",
  researchStageStatusLoading:
    "researchStageStatusLoading text-[var(--fg-muted)]",
  researchStageStatusUnavailable:
    "researchStageStatusUnavailable border-[color-mix(in_srgb,var(--state-warning)_42%,var(--vui-border-subtle))] text-[var(--state-warning)]",
  researchStageModuleCard: `researchStageModuleCard min-w-0 ${vuiFlatPanelClass} p-2`,
  researchStageModuleGrid:
    "researchStageModuleGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  researchStagePage:
    "researchStagePage min-w-0",
  researchStagePageActions:
    "researchStagePageActions min-w-0 flex flex-wrap items-center gap-1.5",
  researchStagePageBody:
    "researchStagePageBody min-w-0 flex-1 min-h-0 overflow-auto [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  researchStagePageHeader:
    "researchStagePageHeader min-w-0 flex flex-wrap items-center gap-1.5",
  researchStageTopicInput:
    "researchStageTopicInput min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
} as const;

export default styles;
