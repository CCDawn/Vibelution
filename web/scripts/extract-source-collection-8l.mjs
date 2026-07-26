/**
 * Wave 8L: extract remaining large SC orchestration bodies.
 * - Extraction recovery workspace
 * - Candidate workspace
 * - Graph workspace
 * - Memory workspace
 * Usage (from web/): node scripts/extract-source-collection-8l.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/TeamsRoute.tsx";
const src = readFileSync(routePath, "utf8");

function extractBody(fnText) {
  const bodyStart = fnText.indexOf("{");
  const body = fnText.slice(bodyStart);
  return body.slice(1, body.lastIndexOf("}"));
}

function sliceBetween(startMark, endMark) {
  const start = src.indexOf(startMark);
  const end = src.indexOf(endMark);
  if (start < 0 || end <= start) {
    console.error("markers missing", startMark.slice(0, 70), start, end);
    process.exit(1);
  }
  return { start, end, body: extractBody(src.slice(start, end)) };
}

const recovery = sliceBetween(
  "  function renderSourceCollectionExtractionRecoveryPanel(",
  "  function renderSourceCollectionCandidatePanel() {",
);
const candidate = sliceBetween(
  "  function renderSourceCollectionCandidatePanel() {",
  "  function renderSourceCollectionGraphPanel() {",
);
const graph = sliceBetween(
  "  function renderSourceCollectionGraphPanel() {",
  "  function renderSourceCollectionMemoryPanel() {",
);
const memory = sliceBetween(
  "  function renderSourceCollectionMemoryPanel() {",
  "  function renderSourceCollectionModeFields() {",
);

const recoveryHeader = `/**
 * Source-collection extraction recovery workspace.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 */
import { CheckCircle2, MessageSquare, Play, RefreshCw } from "lucide-react";

import { VButton } from "../components/vui";
import {
  sourceCollectionStageRecoveryStatusLabel,
  sourceCollectionStageUserSummary,
  sourceCollectionNonNegativeCount,
  type SourceCollectionStageCardProjection,
  type SourceCollectionStageModuleId,
} from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionExtractionRecoveryPanel } from "./TeamSourceCollectionExtractionRecoveryPanel";

type Lang = "zh" | "en";

export type TeamSourceCollectionExtractionRecoveryWorkspacePanelProps = {
  candidateProjection: SourceCollectionStageCardProjection | null | undefined;
  lang: Lang;
  sourceCollectionRawRecordCount: number;
  sourceCollectionRunApprovedCount: number;
  sourceCollectionDisplayedCandidateCount: number;
  sourceCollectionPrimaryDataLoading: boolean;
  sourceCollectionLoadingText: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateStepState: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionExtractionExcludedRecoveryState: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageActionReadinessFor: (stageId: SourceCollectionStageModuleId) => any;
  openSourceCollectionStageAgentChat: (stageId: SourceCollectionStageModuleId) => void;
  startSourceCollectionStageSessionTask: (stageId: SourceCollectionStageModuleId) => void;
  runSourceCollectionCandidateExtractionAction: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateExtractionActionReadiness: any;
  runSourceCollectionScreeningAction: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionScreeningActionReadiness: any;
  sourceCollectionScreeningButtonText: string;
  sourceCollectionRunPendingScreeningCountText: string;
};

export function TeamSourceCollectionExtractionRecoveryWorkspacePanel(props: TeamSourceCollectionExtractionRecoveryWorkspacePanelProps) {
  const {
    candidateProjection,
    lang,
    sourceCollectionRawRecordCount,
    sourceCollectionRunApprovedCount,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionLoadingText,
    sourceCollectionCandidateStepState,
    sourceCollectionExtractionExcludedRecoveryState,
    sourceCollectionActionDisabledTitle,
    sourceCollectionStageActionReadinessFor,
    openSourceCollectionStageAgentChat,
    startSourceCollectionStageSessionTask,
    runSourceCollectionCandidateExtractionAction,
    sourceCollectionCandidateExtractionActionReadiness,
    runSourceCollectionScreeningAction,
    sourceCollectionScreeningActionReadiness,
    sourceCollectionScreeningButtonText,
    sourceCollectionRunPendingScreeningCountText,
  } = props;

`;

const candidateHeader = `/**
 * Source-collection extracted-candidates workspace body.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";

import { TeamCandidateCard } from "../components/vui/product/team-management";
import {
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionEvidenceLedgerCardLabel,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionEvidenceLedgerTone,
  sourceCollectionSourceFilterLabel,
  sourceCollectionCandidateEmptyStateText,
} from "./teams/source-collection/evidenceModel";
import {
  candidateSourceQualityAssessmentSummary,
  sourceCollectionResultTone,
  sourceCollectionSimpleCandidateStatusLabel,
} from "./teams/source-collection/presentationModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionCandidatePanel } from "./TeamSourceCollectionCandidatePanel";

type Lang = "zh" | "en";

export type TeamSourceCollectionCandidateWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFilteredRunCandidates: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPageItems: (stageId: SourceCollectionStageModuleId, items: any[]) => { items: any[]; start: number; end: number };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateProjection: any;
  sourceCollectionSourceFilter: string;
  sourceCollectionDisplayedCandidateCount: number;
  sourceCollectionCountText: (loading: boolean, count: number) => string;
  sourceCollectionPrimaryDataLoading: boolean;
  sourceCollectionDataSyncText: string;
  sourceCollectionRunCandidateCount: number;
  sourceCollectionFocusedPanelId: string;
  selectedSourceCollectionStageId: string;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: (id: string) => void;
  sourceCollectionExtractionDefaultPanelId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateStepState: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionDisplayedCandidateFilterCounts: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionFilterBar: (...args: any[]) => ReactNode;
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionProjectedAssessedCountText: string;
  sourceCollectionProjectedApprovedCountText: string;
  sourceCollectionRunPendingScreeningCountText: string;
  sourceCollectionEvidenceReadyCandidateCount: number | string;
  sourceCollectionMissingEvidenceAnchorCount: number | string;
  sourceCollectionProjectedCollectedCount: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionExtractionRecoveryPanel: (projection: any) => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  selectedSourceCollectionCandidateId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectSourceCollectionCandidate: (candidate: any) => void;
};

export function TeamSourceCollectionCandidateWorkspacePanel(props: TeamSourceCollectionCandidateWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionFilteredRunCandidates,
    sourceCollectionPageItems,
    sourceCollectionCandidateProjection,
    sourceCollectionSourceFilter,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionCountText,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionDataSyncText,
    sourceCollectionRunCandidateCount,
    sourceCollectionFocusedPanelId,
    selectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionExtractionDefaultPanelId,
    sourceCollectionCandidateStepState,
    sourceCollectionDisplayedCandidateFilterCounts,
    renderSourceCollectionFilterBar,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionRunPendingScreeningCountText,
    sourceCollectionEvidenceReadyCandidateCount,
    sourceCollectionMissingEvidenceAnchorCount,
    sourceCollectionProjectedCollectedCount,
    renderSourceCollectionExtractionRecoveryPanel,
    renderSourceCollectionPagination,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
  } = props;

`;

const graphHeader = `/**
 * Source-collection ingestion graph workspace body.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";

import { TeamCandidateCard } from "../components/vui/product/team-management";
import {
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionEvidenceLedgerActionLabel,
  sourceCollectionEvidenceLedgerCardLabel,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionEvidenceLedgerTone,
  sourceCollectionFilterCounts,
  sourceCollectionFilterMatches,
  sourceCollectionSourceFilterLabel,
  sourceCollectionSourceTypeLabel,
} from "./teams/source-collection/evidenceModel";
import { sourceCollectionResultTone } from "./teams/source-collection/presentationModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { workflowGraphLayout } from "./TeamWorkflowGraphLayout";
import { TeamWorkflowGraphView } from "./TeamWorkflowGraphView";
import { workflowStateLabel } from "./teams/workflowPresentation";
import { TeamSourceCollectionGraphPanel } from "./TeamSourceCollectionGraphPanel";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionGraphWorkspacePanelProps = {
  lang: Lang;
  selectedSourceCollectionRunEffectiveId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionGraphProjection: any;
  sourceCollectionProjectedGraphNodeCount: number;
  sourceCollectionProjectedGraphEdgeCount: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowCandidateGraph: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowCandidatesById: Map<string, any>;
  sourceCollectionSourceFilter: string;
  sourceCollectionFocusedPanelId: string;
  selectedSourceCollectionStageId: string;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: (id: string) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionGraphStepState: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionFilterBar: (...args: any[]) => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPageItems: (stageId: SourceCollectionStageModuleId, items: any[]) => { items: any[]; start: number; end: number };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowCandidateGraphQuery: { isPending: boolean; error?: unknown };
  selectedTeamBuildCandidateGraphError: Error | null;
  selectedSourceCollectionCandidateId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectSourceCollectionCandidate: (candidate: any) => void;
};

export function TeamSourceCollectionGraphWorkspacePanel(props: TeamSourceCollectionGraphWorkspacePanelProps) {
  const {
    lang,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionGraphProjection,
    sourceCollectionProjectedGraphNodeCount,
    sourceCollectionProjectedGraphEdgeCount,
    teamWorkflowCandidateGraph,
    teamWorkflowCandidatesById,
    sourceCollectionSourceFilter,
    sourceCollectionFocusedPanelId,
    selectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionGraphStepState,
    renderSourceCollectionFilterBar,
    sourceCollectionPageItems,
    renderSourceCollectionPagination,
    teamWorkflowCandidateGraphQuery,
    selectedTeamBuildCandidateGraphError,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
  } = props;

`;

const memoryHeader = `/**
 * Source-collection memory / knowledge-ingestion workspace body.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";

import { TeamCandidateCard } from "../components/vui/product/team-management";
import {
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionSourceFilterLabel,
} from "./teams/source-collection/evidenceModel";
import {
  candidateSourceQualityAssessmentSummary,
  formatTime,
  sourceCollectionCandidateQualityState,
  sourceCollectionResultTone,
  workflowIngestionStatusLabel,
} from "./teams/source-collection/presentationModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { workflowStateLabel } from "./teams/workflowPresentation";
import { TeamSourceCollectionMemoryPanel } from "./TeamSourceCollectionMemoryPanel";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionMemoryWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowKnowledgeIngestionStatus: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFilteredRunCandidates: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPageItems: (stageId: SourceCollectionStageModuleId, items: any[]) => { items: any[]; start: number; end: number };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowCandidatesById: Map<string, any>;
  sourceCollectionFocusedPanelId: string;
  selectedSourceCollectionStageId: string;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: (id: string) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionMemoryStepState: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateFilterCounts: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionFilterBar: (...args: any[]) => ReactNode;
  knowledgePendingReviewCount: number | string;
  formalKnowledgeItemCount: number | string;
  sourceCollectionApprovedCount: number | string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  workflowIngestionTone: (value: string) => string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowKnowledgeIngestionStatusQuery: { error?: unknown };
  selectedSourceCollectionCandidateId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectSourceCollectionCandidate: (candidate: any) => void;
};

export function TeamSourceCollectionMemoryWorkspacePanel(props: TeamSourceCollectionMemoryWorkspacePanelProps) {
  const {
    lang,
    teamWorkflowKnowledgeIngestionStatus,
    sourceCollectionFilteredRunCandidates,
    sourceCollectionPageItems,
    teamWorkflowCandidatesById,
    sourceCollectionFocusedPanelId,
    selectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionMemoryStepState,
    sourceCollectionCandidateFilterCounts,
    renderSourceCollectionFilterBar,
    knowledgePendingReviewCount,
    formalKnowledgeItemCount,
    sourceCollectionApprovedCount,
    renderSourceCollectionPagination,
    workflowIngestionTone,
    teamWorkflowKnowledgeIngestionStatusQuery,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
  } = props;

`;

// Recovery body starts with param - extractBody already dropped outer braces of function.
// But for recovery the signature is: function ...(candidateProjection: ...) { body }
// extractBody from full fn including signature still works because first { is body.

const recoveryOut = "src/routes/TeamSourceCollectionExtractionRecoveryWorkspacePanel.tsx";
const candidateOut = "src/routes/TeamSourceCollectionCandidateWorkspacePanel.tsx";
const graphOut = "src/routes/TeamSourceCollectionGraphWorkspacePanel.tsx";
const memoryOut = "src/routes/TeamSourceCollectionMemoryWorkspacePanel.tsx";

// Recovery function includes param line - body still correct
writeFileSync(recoveryOut, `${recoveryHeader}${recovery.body}\n}\n`);
writeFileSync(candidateOut, `${candidateHeader}${candidate.body}\n}\n`);
writeFileSync(graphOut, `${graphHeader}${graph.body}\n}\n`);
writeFileSync(memoryOut, `${memoryHeader}${memory.body}\n}\n`);

console.log("wrote recovery", recovery.body.includes("继续 Agent 提炼") || recovery.body.includes("Continue Agent"));
console.log("wrote candidate", candidate.body.includes("本轮候选"));
console.log("wrote graph", graph.body.includes("入库关系") || graph.body.includes("Ingestion map"));
console.log("wrote memory", memory.body.includes("入库资料") || memory.body.includes("Ingestion"));

const recoveryWrapper = `  function renderSourceCollectionExtractionRecoveryPanel(
    candidateProjection: SourceCollectionStageCardProjection | null | undefined,
  ) {
    return (
      <TeamSourceCollectionExtractionRecoveryWorkspacePanel
        candidateProjection={candidateProjection}
        lang={lang}
        sourceCollectionRawRecordCount={sourceCollectionRawRecordCount}
        sourceCollectionRunApprovedCount={sourceCollectionRunApprovedCount}
        sourceCollectionDisplayedCandidateCount={sourceCollectionDisplayedCandidateCount}
        sourceCollectionPrimaryDataLoading={sourceCollectionPrimaryDataLoading}
        sourceCollectionLoadingText={sourceCollectionLoadingText}
        sourceCollectionCandidateStepState={sourceCollectionCandidateStepState}
        sourceCollectionExtractionExcludedRecoveryState={sourceCollectionExtractionExcludedRecoveryState}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionStageActionReadinessFor={sourceCollectionStageActionReadinessFor}
        openSourceCollectionStageAgentChat={openSourceCollectionStageAgentChat}
        startSourceCollectionStageSessionTask={startSourceCollectionStageSessionTask}
        runSourceCollectionCandidateExtractionAction={runSourceCollectionCandidateExtractionAction}
        sourceCollectionCandidateExtractionActionReadiness={sourceCollectionCandidateExtractionActionReadiness}
        runSourceCollectionScreeningAction={runSourceCollectionScreeningAction}
        sourceCollectionScreeningActionReadiness={sourceCollectionScreeningActionReadiness}
        sourceCollectionScreeningButtonText={sourceCollectionScreeningButtonText}
        sourceCollectionRunPendingScreeningCountText={sourceCollectionRunPendingScreeningCountText}
      />
    );
  }

`;

const candidateWrapper = `  function renderSourceCollectionCandidatePanel() {
    return (
      <TeamSourceCollectionCandidateWorkspacePanel
        lang={lang}
        sourceCollectionFilteredRunCandidates={sourceCollectionFilteredRunCandidates}
        sourceCollectionPageItems={sourceCollectionPageItems}
        sourceCollectionCandidateProjection={sourceCollectionCandidateProjection}
        sourceCollectionSourceFilter={sourceCollectionSourceFilter}
        sourceCollectionDisplayedCandidateCount={sourceCollectionDisplayedCandidateCount}
        sourceCollectionCountText={sourceCollectionCountText}
        sourceCollectionPrimaryDataLoading={sourceCollectionPrimaryDataLoading}
        sourceCollectionDataSyncText={sourceCollectionDataSyncText}
        sourceCollectionRunCandidateCount={sourceCollectionRunCandidateCount}
        sourceCollectionFocusedPanelId={sourceCollectionFocusedPanelId}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        sourceCollectionExpandedPanelId={sourceCollectionExpandedPanelId}
        setSourceCollectionExpandedPanelId={setSourceCollectionExpandedPanelId}
        sourceCollectionExtractionDefaultPanelId={sourceCollectionExtractionDefaultPanelId}
        sourceCollectionCandidateStepState={sourceCollectionCandidateStepState}
        sourceCollectionDisplayedCandidateFilterCounts={sourceCollectionDisplayedCandidateFilterCounts}
        renderSourceCollectionFilterBar={renderSourceCollectionFilterBar}
        sourceCollectionDisplayedCandidateCountText={sourceCollectionDisplayedCandidateCountText}
        sourceCollectionProjectedAssessedCountText={sourceCollectionProjectedAssessedCountText}
        sourceCollectionProjectedApprovedCountText={sourceCollectionProjectedApprovedCountText}
        sourceCollectionRunPendingScreeningCountText={sourceCollectionRunPendingScreeningCountText}
        sourceCollectionEvidenceReadyCandidateCount={sourceCollectionEvidenceReadyCandidateCount}
        sourceCollectionMissingEvidenceAnchorCount={sourceCollectionMissingEvidenceAnchorCount}
        sourceCollectionProjectedCollectedCount={sourceCollectionProjectedCollectedCount}
        renderSourceCollectionExtractionRecoveryPanel={renderSourceCollectionExtractionRecoveryPanel}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
      />
    );
  }

`;

const graphWrapper = `  function renderSourceCollectionGraphPanel() {
    return (
      <TeamSourceCollectionGraphWorkspacePanel
        lang={lang}
        selectedSourceCollectionRunEffectiveId={selectedSourceCollectionRunEffectiveId}
        sourceCollectionGraphProjection={sourceCollectionGraphProjection}
        sourceCollectionProjectedGraphNodeCount={sourceCollectionProjectedGraphNodeCount}
        sourceCollectionProjectedGraphEdgeCount={sourceCollectionProjectedGraphEdgeCount}
        teamWorkflowCandidateGraph={teamWorkflowCandidateGraph}
        teamWorkflowCandidatesById={teamWorkflowCandidatesById}
        sourceCollectionSourceFilter={sourceCollectionSourceFilter}
        sourceCollectionFocusedPanelId={sourceCollectionFocusedPanelId}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        sourceCollectionExpandedPanelId={sourceCollectionExpandedPanelId}
        setSourceCollectionExpandedPanelId={setSourceCollectionExpandedPanelId}
        sourceCollectionGraphStepState={sourceCollectionGraphStepState}
        renderSourceCollectionFilterBar={renderSourceCollectionFilterBar}
        sourceCollectionPageItems={sourceCollectionPageItems}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        teamWorkflowCandidateGraphQuery={teamWorkflowCandidateGraphQuery}
        selectedTeamBuildCandidateGraphError={selectedTeamBuildCandidateGraphError}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
      />
    );
  }

`;

const memoryWrapper = `  function renderSourceCollectionMemoryPanel() {
    return (
      <TeamSourceCollectionMemoryWorkspacePanel
        lang={lang}
        teamWorkflowKnowledgeIngestionStatus={teamWorkflowKnowledgeIngestionStatus}
        sourceCollectionFilteredRunCandidates={sourceCollectionFilteredRunCandidates}
        sourceCollectionPageItems={sourceCollectionPageItems}
        teamWorkflowCandidatesById={teamWorkflowCandidatesById}
        sourceCollectionFocusedPanelId={sourceCollectionFocusedPanelId}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        sourceCollectionExpandedPanelId={sourceCollectionExpandedPanelId}
        setSourceCollectionExpandedPanelId={setSourceCollectionExpandedPanelId}
        sourceCollectionMemoryStepState={sourceCollectionMemoryStepState}
        sourceCollectionCandidateFilterCounts={sourceCollectionCandidateFilterCounts}
        renderSourceCollectionFilterBar={renderSourceCollectionFilterBar}
        knowledgePendingReviewCount={knowledgePendingReviewCount}
        formalKnowledgeItemCount={formalKnowledgeItemCount}
        sourceCollectionApprovedCount={sourceCollectionApprovedCount}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        workflowIngestionTone={workflowIngestionTone}
        teamWorkflowKnowledgeIngestionStatusQuery={teamWorkflowKnowledgeIngestionStatusQuery}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
      />
    );
  }

`;

// Replace from end to start to keep indices valid
let next = src;
next = next.slice(0, memory.start) + memoryWrapper + next.slice(memory.end);
next = next.slice(0, graph.start) + graphWrapper + next.slice(graph.end);
next = next.slice(0, candidate.start) + candidateWrapper + next.slice(candidate.end);
next = next.slice(0, recovery.start) + recoveryWrapper + next.slice(recovery.end);

if (!next.includes('"TeamSourceCollectionMemoryWorkspacePanel"')) {
  next = next.replace(
    'const TeamSourceCollectionScreeningWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionScreeningWorkspacePanel");',
    `const TeamSourceCollectionScreeningWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionScreeningWorkspacePanel");
const TeamSourceCollectionExtractionRecoveryWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionExtractionRecoveryWorkspacePanel");
const TeamSourceCollectionCandidateWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionCandidateWorkspacePanel");
const TeamSourceCollectionGraphWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionGraphWorkspacePanel");
const TeamSourceCollectionMemoryWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionMemoryWorkspacePanel");`,
  );
}

writeFileSync(routePath, next);
console.log("rewrote TeamsRoute.tsx delta", next.length - src.length);

const secondaryPath = "src/routes/teams/teamSecondaryPanels.ts";
let secondary = readFileSync(secondaryPath, "utf8");
if (!secondary.includes("TeamSourceCollectionMemoryWorkspacePanel")) {
  secondary += `
export { TeamSourceCollectionExtractionRecoveryWorkspacePanel } from "../TeamSourceCollectionExtractionRecoveryWorkspacePanel";
export { TeamSourceCollectionCandidateWorkspacePanel } from "../TeamSourceCollectionCandidateWorkspacePanel";
export { TeamSourceCollectionGraphWorkspacePanel } from "../TeamSourceCollectionGraphWorkspacePanel";
export { TeamSourceCollectionMemoryWorkspacePanel } from "../TeamSourceCollectionMemoryWorkspacePanel";
`;
  writeFileSync(secondaryPath, secondary);
  console.log("updated teamSecondaryPanels.ts");
}
