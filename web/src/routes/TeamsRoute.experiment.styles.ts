// Wave 8F: experiment cluster extracted from TeamsRoute.styles

import {
  vuiFlatPanelClass,
} from "../design/vuiSurfaceRecipes";

const styles = {
  experimentBaselineArtifact:
    "experimentBaselineArtifact min-w-0",
  experimentBaselineForm:
    "experimentBaselineForm min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  experimentChecklist:
    "experimentChecklist min-w-0",
  experimentChecklistPass:
    "experimentChecklistPass min-w-0",
  experimentChecklistWarn:
    "experimentChecklistWarn min-w-0",
  experimentEvidenceGrid:
    "experimentEvidenceGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  experimentGapList:
    "experimentGapList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  experimentHypothesisList:
    "experimentHypothesisList min-w-0 grid min-h-0 content-start gap-1.5 overflow-auto",
  experimentKnowledgeForm:
    "experimentKnowledgeForm min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  experimentKnowledgePanel: `experimentKnowledgePanel min-w-0 ${vuiFlatPanelClass} p-2`,
  experimentKnowledgeToggle:
    "experimentKnowledgeToggle min-w-0",
  experimentKnowledgeWide:
    "experimentKnowledgeWide min-w-0",
  experimentLedgerEmpty:
    "experimentLedgerEmpty min-w-0 [font-size:var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]",
  experimentLedgerHeader:
    "experimentLedgerHeader min-w-0 flex flex-wrap items-center gap-1.5",
  experimentLedgerPanel: `experimentLedgerPanel min-w-0 ${vuiFlatPanelClass} p-2`,
  experimentLedgerStats:
    "experimentLedgerStats min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  experimentPlanFields:
    "experimentPlanFields min-w-0",
  experimentPlanGrid:
    "experimentPlanGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(9rem,1fr))]",
  experimentPlanSummary: `experimentPlanSummary min-w-0 ${vuiFlatPanelClass} p-2`,
  experimentSmokeForm:
    "experimentSmokeForm min-w-0 grid gap-1 [font-size:var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full",
  experimentSmokeMeta:
    "experimentSmokeMeta min-w-0 flex flex-wrap items-center gap-1.5",
  experimentSmokeRunEvidence: `experimentSmokeRunEvidence min-w-0 ${vuiFlatPanelClass} grid gap-2 p-2`,
  experimentSmokeRunHeader:
    "experimentSmokeRunHeader min-w-0 flex flex-wrap items-start justify-between gap-2 [&>div:first-child]:grid [&>div:first-child]:min-w-0 [&>div:first-child]:gap-0.5 [&_span]:[font-size:var(--vui-font-xs)] [&_span]:text-vui-fg-tertiary [&_strong]:break-words [&_strong]:[font-size:var(--vui-font-sm)] [&_strong]:text-vui-fg-primary",
  experimentSmokeMetricList:
    "experimentSmokeMetricList min-w-0 flex flex-wrap items-center gap-1.5",
  experimentSmokeEvidenceGrid:
    "experimentSmokeEvidenceGrid min-w-0 grid gap-2 grid-cols-[repeat(auto-fit,minmax(14rem,1fr))] [&>div]:min-w-0 [&>div]:rounded-[var(--radius-control)] [&>div]:border [&>div]:border-vui-border-subtle [&>div]:bg-vui-surface-row/70 [&>div]:px-2 [&>div]:py-1.5 [&_dt]:[font-size:var(--vui-font-xs)] [&_dt]:text-vui-fg-tertiary [&_dd]:m-0 [&_dd]:break-all [&_dd]:font-mono [&_dd]:[font-size:var(--vui-font-xs)] [&_dd]:text-vui-fg-secondary",
  experimentSmokeBoundaryList:
    "experimentSmokeBoundaryList min-w-0 flex flex-wrap items-center gap-1.5",
  experimentSmokeResult:
    "experimentSmokeResult min-w-0",
  experimentSmokeResultPass:
    "experimentSmokeResultPass min-w-0",
  experimentSmokeResultWarn:
    "experimentSmokeResultWarn min-w-0",
  experimentSmokeWide:
    "experimentSmokeWide min-w-0",
} as const;

export default styles;
