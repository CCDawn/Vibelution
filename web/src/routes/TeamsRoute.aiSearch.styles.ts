// Wave 8F: aiSearch cluster extracted from TeamsRoute.styles

import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiStateDangerSoftClass,
  vuiStateSuccessSoftClass,
  vuiStateWarningSoftClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  aiSearchRunCard: `aiSearchRunCard min-w-0 ${vuiOpaqueRowClass} p-1.5`,
  aiSearchRunCardDegraded: `aiSearchRunCardDegraded min-w-0 ${vuiOpaqueRowClass} p-1.5`,
  aiSearchRunCardDetails: `aiSearchRunCardDetails min-w-0 ${vuiOpaqueRowClass} p-1.5`,
  aiSearchRunCardFailed: `aiSearchRunCardFailed min-w-0 ${vuiFlatPanelClass} p-2 ${vuiStateDangerSoftClass}`,
  aiSearchRunCardHeader: `aiSearchRunCardHeader min-w-0 ${vuiOpaqueRowClass} p-1.5 flex flex-wrap items-center gap-1.5`,
  aiSearchRunCardReview: `aiSearchRunCardReview min-w-0 ${vuiOpaqueRowClass} p-1.5`,
  aiSearchRunCards:
    "aiSearchRunCards min-w-0 grid gap-2 !grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-[7px]",
  aiSearchRunFallbackReason:
    "aiSearchRunFallbackReason min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  aiSearchRunHeader:
    "aiSearchRunHeader min-w-0 flex flex-wrap items-center gap-1.5",
  aiSearchRunInsight:
    "aiSearchRunInsight min-w-0",
  aiSearchRunLatest:
    "aiSearchRunLatest min-w-0",
  aiSearchRunPanel: `aiSearchRunPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  aiSearchRunQuery:
    "aiSearchRunQuery min-w-0",
  aiSearchRunRefs:
    "aiSearchRunRefs min-w-0",
  aiSearchRunResultHeader:
    "aiSearchRunResultHeader min-w-0 flex flex-wrap items-center gap-1.5",
  aiSearchRunStats:
    "aiSearchRunStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  aiSearchRunStatus:
    "aiSearchRunStatus min-w-0",
  aiSearchRunStatusCompleted:
    `aiSearchRunStatusCompleted min-w-0 ${vuiStateSuccessSoftClass}`,
  aiSearchRunStatusFailed:
    `aiSearchRunStatusFailed min-w-0 ${vuiStateDangerSoftClass}`,
  aiSearchRunStatusPartial:
    `aiSearchRunStatusPartial min-w-0 ${vuiStateWarningSoftClass}`,
  aiSearchRunStatusRunning:
    `aiSearchRunStatusRunning min-w-0 ${vuiStateSuccessSoftClass}`,
  aiSearchRunStorage:
    "aiSearchRunStorage min-w-0",
  aiSearchRunSummary: `aiSearchRunSummary min-w-0 ${vuiFlatPanelClass} p-2`,
  aiSearchRunTopic:
    "aiSearchRunTopic min-w-0",
  aiSearchScopeBadge:
    `aiSearchScopeBadge min-w-0 ${vuiControlPillClass}`,
  aiSearchScopeDescription:
    "aiSearchScopeDescription min-w-0 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]",
  aiSearchScopeDetails:
    "aiSearchScopeDetails min-w-0",
  aiSearchScopeEnabled:
    "aiSearchScopeEnabled min-w-0",
  aiSearchScopeHeader:
    "aiSearchScopeHeader min-w-0 flex flex-wrap items-center gap-1.5",
  aiSearchScopePanel: `aiSearchScopePanel min-w-0 ${vuiFlatPanelClass} p-2`,
  aiSearchScopePolicy:
    "aiSearchScopePolicy min-w-0",
  aiSearchScopeSignal:
    "aiSearchScopeSignal min-w-0",
  aiSearchScopeStats:
    "aiSearchScopeStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  aiSearchSourceGroup:
    "aiSearchSourceGroup min-w-0",
  aiSearchSourceGroupHeader:
    "aiSearchSourceGroupHeader min-w-0 flex flex-wrap items-center gap-1.5",
  aiSearchSourceGroups:
    "aiSearchSourceGroups min-w-0",
  aiSearchSourceItem: `aiSearchSourceItem min-w-0 ${vuiOpaqueRowClass} p-2`,
  aiSearchSourceList:
    "aiSearchSourceList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  aiSearchWorkflowSummary: `aiSearchWorkflowSummary min-w-0 ${vuiFlatPanelClass} p-2`,
} as const;

export default styles;
