/**
 * Wave 8S: wire research secondary + SC run detail queries; extract workflow tone.
 * Usage (from web/): node scripts/wire-team-queries-8s.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/TeamsRoute.tsx";
let src = readFileSync(routePath, "utf8");

// Imports
if (!src.includes("useTeamResearchSecondaryQueries")) {
  src = src.replace(
    'import { useTeamWorkflowStartMutations } from "./teams/useTeamWorkflowStartMutations";',
    `import { useTeamWorkflowStartMutations } from "./teams/useTeamWorkflowStartMutations";
import { useTeamResearchSecondaryQueries } from "./teams/useTeamResearchSecondaryQueries";
import { useSourceCollectionRunQueries } from "./teams/useSourceCollectionRunQueries";
import type {
  DataProcessingRecordListPayload,
  SourceCollectionSummaryPayload,
} from "./teams/sourceCollectionRunQueryModel";
import { workflowIngestionTone, workflowQualityTone } from "./teams/workflowTone";`,
  );
}

// Remove local types
for (const marker of [
  ["type DataProcessingRecordListPayload = {", "\n\ntype SourceCollectionStageModule = {"],
  ["type SourceCollectionSummaryPayload = {", "\n\ntype NodeDragState = {"],
]) {
  const start = src.indexOf(marker[0]);
  const end = src.indexOf(marker[1], start);
  if (start >= 0 && end > start) {
    src = src.slice(0, start) + src.slice(end + 2);
    console.log("removed type", marker[0]);
  }
}

// Replace tone helpers with re-exports wrappers that bind styles
const toneStart = src.indexOf("function workflowQualityTone(value: string) {");
const toneEnd = src.indexOf("function isWorkflowCandidateGraphPayload", toneStart);
if (toneStart >= 0 && toneEnd > toneStart) {
  const wrapper = `function workflowQualityToneBound(value: string) {
  return workflowQualityTone(value, styles);
}

function workflowIngestionToneBound(value: string) {
  return workflowIngestionTone(value, styles);
}

`;
  src = src.slice(0, toneStart) + wrapper + src.slice(toneEnd);
  src = src.replaceAll("workflowQualityTone(", "workflowQualityToneBound(");
  src = src.replaceAll("workflowIngestionTone(", "workflowIngestionToneBound(");
  // Fix double-bound if any
  src = src.replaceAll("workflowQualityToneBoundBound(", "workflowQualityToneBound(");
  src = src.replaceAll("workflowIngestionToneBoundBound(", "workflowIngestionToneBound(");
  console.log("rewrote tone helpers");
}

// Replace research secondary queries block
const expStart = src.indexOf("  const experimentPlanningStatusQuery = useQuery({");
const expEnd = src.indexOf("  const sourceCollectionRunsQueryEnabled = resolveSourceCollectionRunsQueryEnabled({");
if (expStart >= 0 && expEnd > expStart) {
  const block = `  const {
    experimentPlanningStatusQuery,
    experimentMethodCatalogQuery,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
  } = useTeamResearchSecondaryQueries({
    effectiveTeamId,
    researchWorkflowTeamSelected,
    researchWorkspaceView,
    sourceCollectionStandalone,
    researchSecondaryStatusQueryEnabled,
  });
  `;
  src = src.slice(0, expStart) + block + src.slice(expEnd);
  console.log("wired research secondary queries");
}

// Replace SC summary+detail queries
const sumStart = src.indexOf("  const sourceCollectionSummaryQuery = useQuery({");
const sumEnd = src.indexOf("  const autoCanvasViewportStyle = useMemo(() => canvasViewStyle(displayCanvasNodes, canvasFrameSize), [canvasFrameSize, displayCanvasNodes]);");
if (sumStart >= 0 && sumEnd > sumStart) {
  // Keep finding details flags before hook; remove runtimeSummary? Keep runtimeSummaryQuery - it's between finding flags and run status in original.
  // Original order: summary, finding flags, runtimeSummary, runStatus, records, assignments, autoCanvas
  // We'll replace from summary through assignments, but need to preserve finding flags and runtimeSummary.

  // Better: find runtimeSummary and structure carefully.
}

// More careful SC replacement: after findingDetails flags + runtimeSummary, replace the three queries
// Remove summary query first (before finding flags)
const summaryBlockStart = src.indexOf("  const sourceCollectionSummaryQuery = useQuery({");
const findingStart = src.indexOf("  const sourceCollectionFindingDetailsVisible = Boolean(", summaryBlockStart);
if (summaryBlockStart >= 0 && findingStart > summaryBlockStart) {
  src = src.slice(0, summaryBlockStart) + src.slice(findingStart);
  console.log("removed inline summary query");
}

// After finding flags and runtimeSummary, replace run status/records/assignments with hook that also includes summary
const runtimeEndMarker = "  const sourceCollectionRunStatusQuery = useQuery({";
const runtimeEnd = src.indexOf(runtimeEndMarker);
const assignEnd = src.indexOf("  const autoCanvasViewportStyle = useMemo(() => canvasViewStyle(displayCanvasNodes, canvasFrameSize), [canvasFrameSize, displayCanvasNodes]);");
if (runtimeEnd >= 0 && assignEnd > runtimeEnd) {
  // Need finding flags still present before this
  const insert = `  const {
    sourceCollectionSummaryQuery,
    sourceCollectionRunStatusQuery,
    sourceCollectionRecordsQuery,
    sourceCollectionAssignmentsQuery,
  } = useSourceCollectionRunQueries({
    effectiveTeamId,
    pageVisible,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionWorkspaceSelected,
    sourceCollectionFindingDetailsVisible,
    sourceCollectionStageWritebackSyncActive,
    selectedRunStatusFallback: selectedSourceCollectionRun?.status || "",
  });
  `;
  src = src.slice(0, runtimeEnd) + insert + src.slice(assignEnd);
  console.log("wired SC run detail queries");
}

// Remove unused records/assignments enabled consts if orphaned
src = src.replace(
  /  const sourceCollectionRecordsQueryEnabled = sourceCollectionFindingDetailsVisible;\n  const sourceCollectionAssignmentsQueryEnabled = sourceCollectionFindingDetailsVisible;\n  const sourceCollectionRunStatusQueryEnabled = sourceCollectionRecordsQueryEnabled \|\| sourceCollectionAssignmentsQueryEnabled;\n/,
  "",
);

writeFileSync(routePath, src);
console.log("done", src.length);
