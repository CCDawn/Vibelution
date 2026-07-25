// Wave 8F: workflow cluster extracted from TeamsRoute.styles

import {
  vuiControlPillClass,
} from "../design/vuiChromeRecipes";

import {
  vuiFlatPanelClass,
  vuiOpaqueRowClass,
  vuiStateDangerSoftClass,
  vuiStateSelectedRowClass,
  vuiStateSuccessSoftClass,
  vuiStateWarningSoftClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  kernelTraceLink:
    "kernelTraceLink min-w-0",
  linkedRoomLine: `linkedRoomLine min-w-0 ${vuiOpaqueRowClass} p-2 inline-flex max-w-full flex-wrap items-center gap-1 px-2 py-1 [font-size:var(--vui-font-xs)] font-semibold leading-tight text-[var(--accent-cool)]`,
  teamHistoryHeader:
    "teamHistoryHeader min-w-0 flex flex-wrap items-center gap-1.5",
  teamHistoryItem: `teamHistoryItem min-w-0 ${vuiOpaqueRowClass} p-2`,
  teamHistoryItemRevoked: `teamHistoryItemRevoked min-w-0 ${vuiOpaqueRowClass} p-2`,
  teamHistoryList:
    "teamHistoryList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  teamHistoryMeta:
    "teamHistoryMeta min-w-0 flex flex-wrap items-center gap-1.5",
  teamHistoryPanel: `teamHistoryPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  teamRoundCard: `teamRoundCard min-w-0 ${vuiFlatPanelClass} p-2`,
  teamRoundHeader:
    "teamRoundHeader min-w-0 flex flex-wrap items-center gap-1.5",
  teamRoundMeta:
    "teamRoundMeta min-w-0 flex flex-wrap items-center gap-1.5",
  teamRoundPanel: `teamRoundPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  workflowError:
    "workflowError min-w-0 break-words rounded-[var(--radius-control)] border border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] px-2 py-1.5 [font-size:var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--state-error)]",
  workflowIngestionActions:
    "workflowIngestionActions min-w-0 flex flex-wrap items-center gap-1.5",
  workflowMeta:
    "workflowMeta min-w-0 flex flex-wrap items-center gap-1.5",
  workflowPanel: `workflowPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  workflowSourceQualityStats:
    "workflowSourceQualityStats min-w-0 grid gap-2 !grid grid-cols-[repeat(5,minmax(72px,1fr))] gap-[5px]",
  workflowStageActive:
    `workflowStageActive min-w-0 ${vuiStateSelectedRowClass}`,
  workflowStageList:
    "workflowStageList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  workflowStats:
    "workflowStats min-w-0 grid gap-2 !grid grid-cols-[repeat(3,minmax(0,1fr))] gap-1.5",
  workflowSuccess:
    `workflowSuccess min-w-0 ${vuiStateSuccessSoftClass}`,
  workflowTag:
    `workflowTag min-w-0 ${vuiControlPillClass}`,
  workflowTagDanger:
    `workflowTagDanger min-w-0 ${vuiStateDangerSoftClass}`,
  workflowTagNeutral:
    "workflowTagNeutral min-w-0",
  workflowTagReady:
    `workflowTagReady min-w-0 ${vuiStateSuccessSoftClass}`,
  workflowTagWarning:
    `workflowTagWarning min-w-0 ${vuiStateWarningSoftClass}`,
  workflowValidation:
    "workflowValidation min-w-0",
} as const;

export default styles;
