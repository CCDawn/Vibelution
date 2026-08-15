/**
 * Wave 8K: extract SC orchestration blocks from TeamsRoute into secondary-lazy panels.
 * - TeamKnowledgeCollectionCompletionFlowPanel
 * - TeamSourceCollectionConversationWorkspacePanel
 * - TeamSourceCollectionScreeningWorkspacePanel
 * Usage (from web/): node scripts/extract-source-collection-8k.mjs
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
    console.error("markers missing", startMark.slice(0, 60), start, end);
    process.exit(1);
  }
  return { start, end, fn: src.slice(start, end), body: extractBody(src.slice(start, end)) };
}

const completion = sliceBetween(
  "  function renderKnowledgeCollectionCompletionFlowPanel() {",
  "  function renderAiSearchSourceScopePanel() {",
);
const conversation = sliceBetween(
  "  function renderSourceCollectionConversation() {",
  "  function renderSourceCollectionStorageActions() {",
);
const screening = sliceBetween(
  "  function renderSourceCollectionScreeningPanel() {",
  "  function renderSourceCollectionExtractionRecoveryPanel(",
);

// --- Completion flow panel ---
const completionHeader = `/**
 * Knowledge-collection one-click completion flow graph.
 * Wave 8K: extracted from TeamsRoute.tsx for domain componentization.
 */
import { Link2, MessageSquare, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { VNativeButton } from "../components/vui";
import { agentDisplayInfo } from "./agentDisplay";
import {
  sourceCollectionAgentRoleLabel,
  workflowIngestionStatusLabel,
} from "./teams/source-collection/presentationModel";
import {
  sourceCollectionCompletionFlowNodeState,
} from "./teams/source-collection/runModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import researchStyles from "./TeamsRoute.research.styles";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...researchStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamKnowledgeCollectionCompletionFlowPanelProps = {
  lang: Lang;
  researchWorkflowTeamSelected: boolean;
  researchCanvasReadOnly: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamKnowledgeCollectionWorkRun: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCompletionFlow: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCompletionFlowNodes: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageModules: Array<{ id: SourceCollectionStageModuleId; label: string }>;
  workflowIngestionTone: (value: string) => string;
  parseSourceCollectionStageModuleId: (value: string | null) => SourceCollectionStageModuleId | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStagePrimaryAgentBinding: (stageId: SourceCollectionStageModuleId) => any;
  sourceCollectionStageReturnRoute: (stageId: SourceCollectionStageModuleId) => string;
  openSourceCollectionStageAgentChat: (stageId: SourceCollectionStageModuleId) => void;
  sourceCollectionStepClassName: (state: string) => string;
  runKnowledgeCollectionCompletionAction: () => void;
  sourceCollectionCompletionActionDisabled: boolean;
  selectedTeamKnowledgeCollectionIngestPending: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCompletionActionReadiness: any;
};

export function TeamKnowledgeCollectionCompletionFlowPanel(props: TeamKnowledgeCollectionCompletionFlowPanelProps) {
  const {
    lang,
    researchWorkflowTeamSelected,
    researchCanvasReadOnly,
    selectedTeamKnowledgeCollectionWorkRun,
    sourceCollectionCompletionFlow,
    sourceCollectionCompletionFlowNodes,
    sourceCollectionStageModules,
    workflowIngestionTone,
    parseSourceCollectionStageModuleId,
    sourceCollectionStagePrimaryAgentBinding,
    sourceCollectionStageReturnRoute,
    openSourceCollectionStageAgentChat,
    sourceCollectionStepClassName,
    runKnowledgeCollectionCompletionAction,
    sourceCollectionCompletionActionDisabled,
    selectedTeamKnowledgeCollectionIngestPending,
    sourceCollectionActionDisabledTitle,
    sourceCollectionCompletionActionReadiness,
  } = props;

`;

// --- Conversation workspace ---
const conversationHeader = `/**
 * Source-collection conversation / raw-records workspace body.
 * Wave 8K: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { Play, RefreshCw, Search } from "lucide-react";

import type { Team } from "../api/types";
import { VButton } from "../components/vui";
import {
  TeamSourceEmptyState,
  TeamSourceResultItem,
  TeamSourceResultList,
  type TeamSourceEmptyStateFact,
} from "../components/vui/product/team-management";
import {
  candidateSourceQualityAssessmentSummary,
  sourceCollectionRecordProvenance,
  sourceCollectionResultTone,
  sourceCollectionSimpleRecordStatusLabel,
  sourceCollectionSourceTypeLabel,
} from "./teams/source-collection/presentationModel";
import {
  sourceCollectionRunCandidateMetric,
  sourceCollectionRunHasUsableRecords,
  sourceCollectionRunRecordCount,
  sourceCollectionRunTitleLabel,
} from "./teams/source-collection/runModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionConversationPanel } from "./TeamSourceCollectionConversationPanel";

type Lang = "zh" | "en";

export type TeamSourceCollectionConversationWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPageItems: (stageId: SourceCollectionStageModuleId, items: any[]) => { items: any[]; start: number; end: number };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFilteredRecords: any[];
  sourceCollectionRecordsDataLoading: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionRecords: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionRun: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionHistoricalRunWithRecords: any;
  sourceCollectionLoadingText: string;
  sourceCollectionRawRecordCount: number;
  sourceCollectionRecordClickableSourceCount: number;
  sourceCollectionRecordLocalFileCount: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageModules: Array<{ id: string; actionLabel?: string; actionDisabled?: boolean; onAction?: () => void }>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageActionReadinessFor: (stageId: string) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionDraft: { title: string };
  sourceCollectionCollectedCountLabel: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionStorageArtifacts: any;
  sourceCollectionBoardNextStepLabel: string;
  sourceCollectionSourceFilter: string;
  setSourceCollectionSourceFilter: (value: any) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionRecordFilterCounts: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionFilterBar: (...args: any[]) => ReactNode;
  sourceCollectionCollectedCountText: string;
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionPendingCandidateImportCount: number;
  sourceCollectionRecordMissingSourceCount: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidatesByRecordId: Map<string, any>;
  selectedSourceCollectionCandidateId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectSourceCollectionCandidate: (candidate: any) => void;
  setSelectedSourceCollectionRunId: (runId: string) => void;
};

export function TeamSourceCollectionConversationWorkspacePanel(props: TeamSourceCollectionConversationWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionPageItems,
    sourceCollectionFilteredRecords,
    sourceCollectionRecordsDataLoading,
    sourceCollectionRecords,
    selectedSourceCollectionRun,
    sourceCollectionHistoricalRunWithRecords,
    sourceCollectionLoadingText,
    sourceCollectionRawRecordCount,
    sourceCollectionRecordClickableSourceCount,
    sourceCollectionRecordLocalFileCount,
    sourceCollectionStageModules,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionDraft,
    sourceCollectionCollectedCountLabel,
    selectedSourceCollectionStorageArtifacts,
    sourceCollectionBoardNextStepLabel,
    sourceCollectionSourceFilter,
    setSourceCollectionSourceFilter,
    sourceCollectionActionDisabledTitle,
    sourceCollectionRecordFilterCounts,
    renderSourceCollectionFilterBar,
    sourceCollectionCollectedCountText,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionPendingCandidateImportCount,
    sourceCollectionRecordMissingSourceCount,
    renderSourceCollectionPagination,
    sourceCollectionCandidatesByRecordId,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
    setSelectedSourceCollectionRunId,
  } = props;

`;

// --- Screening workspace ---
const screeningHeader = `/**
 * Source-collection screening / review workspace body.
 * Wave 8K: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Eye, Plus, RefreshCw } from "lucide-react";

import type { Team } from "../api/types";
import { VButton, VNativeButton } from "../components/vui";
import { TeamCandidateCard } from "../components/vui/product/team-management";
import {
  candidateSourceQualityAssessmentSummary,
  formatTime,
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionResultTone,
  sourceCollectionSourceFilterLabel,
  workflowIngestionStatusLabel,
} from "./teams/source-collection/presentationModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionScreeningPanel } from "./TeamSourceCollectionScreeningPanel";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionScreeningWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFilteredRunCandidates: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPageItems: (stageId: SourceCollectionStageModuleId, items: any[]) => { items: any[]; start: number; end: number };
  sourceCollectionSourceFilter: string;
  sourceCollectionDisplayedCandidateCount: number;
  sourceCollectionCountText: (loading: boolean, count: number) => string;
  sourceCollectionPrimaryDataLoading: boolean;
  sourceCollectionDataSyncText: string;
  sourceCollectionFocusedPanelId: string;
  selectedSourceCollectionStageId: string;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: (id: string) => void;
  sourceCollectionExtractionDefaultPanelId: string;
  sourceCollectionScreeningStepState: string;
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
  runSourceCollectionScreeningAction: () => void;
  sourceCollectionScreeningDisabled: boolean;
  selectedTeamSourceQualityPending: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionScreeningActionReadiness: any;
  sourceCollectionScreeningButtonText: string;
  openSourceCollectionScreeningPanel: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowSourceQualityStatus: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamWorkflowSourceQualityStatusQuery: { error?: unknown };
  workflowIngestionTone: (value: string) => string;
  selectedTeamSourceQualityError: Error | null;
  selectedSourceCollectionCandidateId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectSourceCollectionCandidate: (candidate: any) => void;
  selectedTeam: Team | null | undefined;
  selectedTeamAssessSourceQualityPending: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  assessSourceQualityMutation: any;
  selectedTeamPlanPaperNoteChunksPending: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  planPaperNoteChunksMutation: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCandidateHasCompletedExtraction: (candidate: any) => boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  candidatePaperNoteChunkPlanSummary: (candidate: any) => any;
};

export function TeamSourceCollectionScreeningWorkspacePanel(props: TeamSourceCollectionScreeningWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionFilteredRunCandidates,
    sourceCollectionPageItems,
    sourceCollectionSourceFilter,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionCountText,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionDataSyncText,
    sourceCollectionFocusedPanelId,
    selectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionExtractionDefaultPanelId,
    sourceCollectionScreeningStepState,
    sourceCollectionDisplayedCandidateFilterCounts,
    renderSourceCollectionFilterBar,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionRunPendingScreeningCountText,
    sourceCollectionEvidenceReadyCandidateCount,
    sourceCollectionMissingEvidenceAnchorCount,
    runSourceCollectionScreeningAction,
    sourceCollectionScreeningDisabled,
    selectedTeamSourceQualityPending,
    sourceCollectionActionDisabledTitle,
    sourceCollectionScreeningActionReadiness,
    sourceCollectionScreeningButtonText,
    openSourceCollectionScreeningPanel,
    renderSourceCollectionPagination,
    teamWorkflowSourceQualityStatus,
    teamWorkflowSourceQualityStatusQuery,
    workflowIngestionTone,
    selectedTeamSourceQualityError,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
    selectedTeam,
    selectedTeamAssessSourceQualityPending,
    assessSourceQualityMutation,
    selectedTeamPlanPaperNoteChunksPending,
    planPaperNoteChunksMutation,
    sourceCandidateHasCompletedExtraction,
    candidatePaperNoteChunkPlanSummary,
  } = props;

`;

const completionOut = "src/routes/TeamKnowledgeCollectionCompletionFlowPanel.tsx";
const conversationOut = "src/routes/TeamSourceCollectionConversationWorkspacePanel.tsx";
const screeningOut = "src/routes/TeamSourceCollectionScreeningWorkspacePanel.tsx";

writeFileSync(completionOut, `${completionHeader}${completion.body}\n}\n`);
writeFileSync(conversationOut, `${conversationHeader}${conversation.body}\n}\n`);
writeFileSync(screeningOut, `${screeningHeader}${screening.body}\n}\n`);

console.log("wrote", completionOut, completion.body.includes("一键流程图"));
console.log("wrote", conversationOut, conversation.body.includes("原始资料"));
console.log("wrote", screeningOut, screening.body.includes("资料提炼复核") || screening.body.includes("本轮候选"));

const completionWrapper = `  function renderKnowledgeCollectionCompletionFlowPanel() {
    return (
      <TeamKnowledgeCollectionCompletionFlowPanel
        lang={lang}
        researchWorkflowTeamSelected={researchWorkflowTeamSelected}
        researchCanvasReadOnly={researchCanvasReadOnly}
        selectedTeamKnowledgeCollectionWorkRun={selectedTeamKnowledgeCollectionWorkRun}
        sourceCollectionCompletionFlow={sourceCollectionCompletionFlow}
        sourceCollectionCompletionFlowNodes={sourceCollectionCompletionFlowNodes}
        sourceCollectionStageModules={sourceCollectionStageModules}
        workflowIngestionTone={workflowIngestionTone}
        parseSourceCollectionStageModuleId={parseSourceCollectionStageModuleId}
        sourceCollectionStagePrimaryAgentBinding={sourceCollectionStagePrimaryAgentBinding}
        sourceCollectionStageReturnRoute={sourceCollectionStageReturnRoute}
        openSourceCollectionStageAgentChat={openSourceCollectionStageAgentChat}
        sourceCollectionStepClassName={sourceCollectionStepClassName}
        runKnowledgeCollectionCompletionAction={runKnowledgeCollectionCompletionAction}
        sourceCollectionCompletionActionDisabled={sourceCollectionCompletionActionDisabled}
        selectedTeamKnowledgeCollectionIngestPending={selectedTeamKnowledgeCollectionIngestPending}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionCompletionActionReadiness={sourceCollectionCompletionActionReadiness}
      />
    );
  }

`;

const conversationWrapper = `  function renderSourceCollectionConversation() {
    return (
      <TeamSourceCollectionConversationWorkspacePanel
        lang={lang}
        sourceCollectionPageItems={sourceCollectionPageItems}
        sourceCollectionFilteredRecords={sourceCollectionFilteredRecords}
        sourceCollectionRecordsDataLoading={sourceCollectionRecordsDataLoading}
        sourceCollectionRecords={sourceCollectionRecords}
        selectedSourceCollectionRun={selectedSourceCollectionRun}
        sourceCollectionHistoricalRunWithRecords={sourceCollectionHistoricalRunWithRecords}
        sourceCollectionLoadingText={sourceCollectionLoadingText}
        sourceCollectionRawRecordCount={sourceCollectionRawRecordCount}
        sourceCollectionRecordClickableSourceCount={sourceCollectionRecordClickableSourceCount}
        sourceCollectionRecordLocalFileCount={sourceCollectionRecordLocalFileCount}
        sourceCollectionStageModules={sourceCollectionStageModules}
        sourceCollectionStageActionReadinessFor={sourceCollectionStageActionReadinessFor}
        sourceCollectionDraft={sourceCollectionDraft}
        sourceCollectionCollectedCountLabel={sourceCollectionCollectedCountLabel}
        selectedSourceCollectionStorageArtifacts={selectedSourceCollectionStorageArtifacts}
        sourceCollectionBoardNextStepLabel={sourceCollectionBoardNextStepLabel}
        sourceCollectionSourceFilter={sourceCollectionSourceFilter}
        setSourceCollectionSourceFilter={setSourceCollectionSourceFilter}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionRecordFilterCounts={sourceCollectionRecordFilterCounts}
        renderSourceCollectionFilterBar={renderSourceCollectionFilterBar}
        sourceCollectionCollectedCountText={sourceCollectionCollectedCountText}
        sourceCollectionDisplayedCandidateCountText={sourceCollectionDisplayedCandidateCountText}
        sourceCollectionPendingCandidateImportCount={sourceCollectionPendingCandidateImportCount}
        sourceCollectionRecordMissingSourceCount={sourceCollectionRecordMissingSourceCount}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        sourceCollectionCandidatesByRecordId={sourceCollectionCandidatesByRecordId}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
        setSelectedSourceCollectionRunId={setSelectedSourceCollectionRunId}
      />
    );
  }

`;

const screeningWrapper = `  function renderSourceCollectionScreeningPanel() {
    return (
      <TeamSourceCollectionScreeningWorkspacePanel
        lang={lang}
        sourceCollectionFilteredRunCandidates={sourceCollectionFilteredRunCandidates}
        sourceCollectionPageItems={sourceCollectionPageItems}
        sourceCollectionSourceFilter={sourceCollectionSourceFilter}
        sourceCollectionDisplayedCandidateCount={sourceCollectionDisplayedCandidateCount}
        sourceCollectionCountText={sourceCollectionCountText}
        sourceCollectionPrimaryDataLoading={sourceCollectionPrimaryDataLoading}
        sourceCollectionDataSyncText={sourceCollectionDataSyncText}
        sourceCollectionFocusedPanelId={sourceCollectionFocusedPanelId}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        sourceCollectionExpandedPanelId={sourceCollectionExpandedPanelId}
        setSourceCollectionExpandedPanelId={setSourceCollectionExpandedPanelId}
        sourceCollectionExtractionDefaultPanelId={sourceCollectionExtractionDefaultPanelId}
        sourceCollectionScreeningStepState={sourceCollectionScreeningStepState}
        sourceCollectionDisplayedCandidateFilterCounts={sourceCollectionDisplayedCandidateFilterCounts}
        renderSourceCollectionFilterBar={renderSourceCollectionFilterBar}
        sourceCollectionDisplayedCandidateCountText={sourceCollectionDisplayedCandidateCountText}
        sourceCollectionProjectedAssessedCountText={sourceCollectionProjectedAssessedCountText}
        sourceCollectionProjectedApprovedCountText={sourceCollectionProjectedApprovedCountText}
        sourceCollectionRunPendingScreeningCountText={sourceCollectionRunPendingScreeningCountText}
        sourceCollectionEvidenceReadyCandidateCount={sourceCollectionEvidenceReadyCandidateCount}
        sourceCollectionMissingEvidenceAnchorCount={sourceCollectionMissingEvidenceAnchorCount}
        runSourceCollectionScreeningAction={runSourceCollectionScreeningAction}
        sourceCollectionScreeningDisabled={sourceCollectionScreeningDisabled}
        selectedTeamSourceQualityPending={selectedTeamSourceQualityPending}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionScreeningActionReadiness={sourceCollectionScreeningActionReadiness}
        sourceCollectionScreeningButtonText={sourceCollectionScreeningButtonText}
        openSourceCollectionScreeningPanel={openSourceCollectionScreeningPanel}
        renderSourceCollectionPagination={renderSourceCollectionPagination}
        teamWorkflowSourceQualityStatus={teamWorkflowSourceQualityStatus}
        teamWorkflowSourceQualityStatusQuery={teamWorkflowSourceQualityStatusQuery}
        workflowIngestionTone={workflowIngestionTone}
        selectedTeamSourceQualityError={selectedTeamSourceQualityError}
        selectedSourceCollectionCandidateId={selectedSourceCollectionCandidateId}
        selectSourceCollectionCandidate={selectSourceCollectionCandidate}
        selectedTeam={selectedTeam}
        selectedTeamAssessSourceQualityPending={selectedTeamAssessSourceQualityPending}
        assessSourceQualityMutation={assessSourceQualityMutation}
        selectedTeamPlanPaperNoteChunksPending={selectedTeamPlanPaperNoteChunksPending}
        planPaperNoteChunksMutation={planPaperNoteChunksMutation}
        sourceCandidateHasCompletedExtraction={sourceCandidateHasCompletedExtraction}
        candidatePaperNoteChunkPlanSummary={candidatePaperNoteChunkPlanSummary}
      />
    );
  }

`;

// Replace three function bodies in route (from end to start so indices remain valid)
let next = src;
next = next.slice(0, screening.start) + screeningWrapper + next.slice(screening.end);
next = next.slice(0, conversation.start) + conversationWrapper + next.slice(conversation.end);
next = next.slice(0, completion.start) + completionWrapper + next.slice(completion.end);

// Add lazy declarations after TeamSourceCollectionScreeningPanel line
if (!next.includes('"TeamSourceCollectionScreeningWorkspacePanel"')) {
  next = next.replace(
    'const TeamSourceCollectionScreeningPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionScreeningPanel");',
    `const TeamSourceCollectionScreeningPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionScreeningPanel");
const TeamKnowledgeCollectionCompletionFlowPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamKnowledgeCollectionCompletionFlowPanel");
const TeamSourceCollectionConversationWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionConversationWorkspacePanel");
const TeamSourceCollectionScreeningWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionScreeningWorkspacePanel");`,
  );
}

writeFileSync(routePath, next);
console.log("rewrote TeamsRoute.tsx", "delta", next.length - src.length);

// Secondary barrel
const secondaryPath = "src/routes/teams/teamSecondaryPanels.ts";
let secondary = readFileSync(secondaryPath, "utf8");
if (!secondary.includes("TeamKnowledgeCollectionCompletionFlowPanel")) {
  secondary += `
export { TeamKnowledgeCollectionCompletionFlowPanel } from "../TeamKnowledgeCollectionCompletionFlowPanel";
export { TeamSourceCollectionConversationWorkspacePanel } from "../TeamSourceCollectionConversationWorkspacePanel";
export { TeamSourceCollectionScreeningWorkspacePanel } from "../TeamSourceCollectionScreeningWorkspacePanel";
`;
  writeFileSync(secondaryPath, secondary);
  console.log("updated teamSecondaryPanels.ts");
}
