/**
 * Wave 8M: extract remaining SC orchestration bodies.
 * - Selected source detail workspace
 * - Controls workspace
 * - Active stage workspace
 * Usage (from web/): node scripts/extract-source-collection-8m.mjs
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

const selected = sliceBetween(
  "  function renderSourceCollectionSelectedSourcePanel() {",
  "  function renderSourceCollectionScreeningPanel() {",
);
const controls = sliceBetween(
  "  function renderSourceCollectionControlsPanel() {",
  "  function renderSourceCollectionActiveStagePanel() {",
);
const active = sliceBetween(
  "  function renderSourceCollectionActiveStagePanel() {",
  "  function renderResearchLoopPanel(",
);

const selectedHeader = `/**
 * Source-collection selected-source detail workspace.
 * Wave 8M: extracted from TeamsRoute.tsx for domain componentization.
 */
import {
  sourceCollectionCandidateOpenLabel,
  sourceCollectionCandidateProvenance,
  sourceCollectionCandidateTrace,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionStorageTargetForRef,
  sourceCollectionStorageTargetLabel,
  sourceCollectionSourceTypeLabel,
  sourceCollectionEvidenceLedgerDetailItems,
} from "./teams/source-collection/evidenceModel";
import {
  candidateSourceQualityAssessmentSummary,
  sourceCollectionStatusLabel,
} from "./teams/source-collection/presentationModel";
import { translateResearchPhrase } from "./teams/source-collection/runModel";
import { workflowStateLabel } from "./teams/workflowPresentation";
import {
  TeamSourceCollectionSourceDetailPanel,
  type TeamSourceCollectionSourceDetailAction,
  type TeamSourceCollectionSourceDetailEvidence,
  type TeamSourceCollectionSourceDetailLink,
} from "./TeamSourceCollectionSourceDetailPanel";
import type { SourceCollectionStorageOpenTarget } from "./teams/source-collection/presentationModel";

type Lang = "zh" | "en";

export type TeamSourceCollectionSelectedSourceWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionCandidate: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionCandidateTrace: any;
  selectedSourceCollectionRunEffectiveId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionCandidateStorageArtifacts: any;
  workflowQualityTone: (value: string) => string;
  selectedSourceCollectionStorageOpenPending: boolean;
  openSourceCollectionStorageTarget: (target: SourceCollectionStorageOpenTarget, runId?: string) => void;
};

export function TeamSourceCollectionSelectedSourceWorkspacePanel(props: TeamSourceCollectionSelectedSourceWorkspacePanelProps) {
  const {
    lang,
    selectedSourceCollectionCandidate,
    selectedSourceCollectionCandidateTrace,
    selectedSourceCollectionRunEffectiveId,
    selectedSourceCollectionCandidateStorageArtifacts,
    workflowQualityTone,
    selectedSourceCollectionStorageOpenPending,
    openSourceCollectionStorageTarget,
  } = props;

`;

const controlsHeader = `/**
 * Source-collection controls / side-rail workspace body.
 * Wave 8M: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode, Ref } from "react";

import type { Team } from "../api/types";
import { TeamSourceCollectionControlsPanel } from "./TeamSourceCollectionControlsPanel";
import { TeamSourceCollectionRunSettingsPanel } from "./TeamSourceCollectionRunSettingsPanel";
import { TeamSourceCollectionFindingDetailsPanel } from "./TeamSourceCollectionFindingDetailsPanel";
import {
  sourceCollectionStatusLabel,
} from "./teams/source-collection/presentationModel";
import { sourceCollectionRunLabel } from "./teams/source-collection/runModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionControlsWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionControlPanelRef: Ref<any>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageModules: any[];
  selectedSourceCollectionStageId: SourceCollectionStageModuleId | string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionRun: any;
  sourceCollectionStageFocusLabel: string;
  workflowIngestionTone: (value: string) => string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionRunStatus: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionSelectedSourcePanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionDraft: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionModeFields: () => ReactNode;
  sourceCollectionCanStart: boolean;
  selectedTeamStartSourceCollectionPending: boolean;
  setSourceCollectionDraft: (updater: (current: any) => any) => void;
  selectedTeam: Team | null | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  startSourceCollectionRunMutation: any;
  selectedSourceCollectionRunEffectiveId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFindingRunOptions: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFindingAssignments: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFindingQueries: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionStorageActions: () => ReactNode;
  setSelectedSourceCollectionRunId: (runId: string) => void;
  setSourceCollectionOutputDraft: (updater: (current: any) => any) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionManualWritebackPanel: () => ReactNode;
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionProjectedAssessedCountText: string;
  sourceCollectionProjectedApprovedCountText: string;
  sourceCollectionRunPendingScreeningCountText: string;
  candidateGraphNodeCount: number | string;
  candidateGraphEdgeCount: number | string;
  sourceCollectionPrecheckCandidateCount: number | string;
  knowledgePendingReviewCount: number | string;
  formalKnowledgeItemCount: number | string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamKnowledgeCollectionIngestResult: any;
  selectedTeamKnowledgeCollectionIngestError: Error | null;
  selectedTeamStartSourceCollectionError: Error | null;
  selectedTeamRecordSourceCollectionOutputError: Error | null;
  selectedTeamExecuteSourceCollectionSearchError: Error | null;
  selectedTeamStartSourceCollectionStageTaskError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamExecuteSourceCollectionSearchResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamRecordSourceCollectionOutputResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionStageAgents: (stageId: any) => ReactNode;
};

export function TeamSourceCollectionControlsWorkspacePanel(props: TeamSourceCollectionControlsWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionControlPanelRef,
    sourceCollectionStageModules,
    selectedSourceCollectionStageId,
    selectedSourceCollectionRun,
    sourceCollectionStageFocusLabel,
    workflowIngestionTone,
    sourceCollectionRunStatus,
    renderSourceCollectionSelectedSourcePanel,
    sourceCollectionDraft,
    renderSourceCollectionModeFields,
    sourceCollectionCanStart,
    selectedTeamStartSourceCollectionPending,
    setSourceCollectionDraft,
    selectedTeam,
    startSourceCollectionRunMutation,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionFindingRunOptions,
    sourceCollectionFindingAssignments,
    sourceCollectionFindingQueries,
    renderSourceCollectionStorageActions,
    setSelectedSourceCollectionRunId,
    setSourceCollectionOutputDraft,
    renderSourceCollectionManualWritebackPanel,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionRunPendingScreeningCountText,
    candidateGraphNodeCount,
    candidateGraphEdgeCount,
    sourceCollectionPrecheckCandidateCount,
    knowledgePendingReviewCount,
    formalKnowledgeItemCount,
    selectedTeamKnowledgeCollectionIngestResult,
    selectedTeamKnowledgeCollectionIngestError,
    selectedTeamStartSourceCollectionError,
    selectedTeamRecordSourceCollectionOutputError,
    selectedTeamExecuteSourceCollectionSearchError,
    selectedTeamStartSourceCollectionStageTaskError,
    selectedTeamExecuteSourceCollectionSearchResult,
    selectedTeamRecordSourceCollectionOutputResult,
    renderSourceCollectionStageAgents,
  } = props;

`;

const activeHeader = `/**
 * Source-collection active-stage workspace body.
 * Wave 8M: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { Link2, MessageSquare } from "lucide-react";
import { Link } from "react-router-dom";

import { VNativeButton, VTooltip } from "../components/vui";
import { researchStageAgentManagementRoute } from "./teams/researchStageAgentPresentation";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionActiveStagePanel } from "./TeamSourceCollectionActiveStagePanel";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionActiveStageWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageModules: any[];
  selectedSourceCollectionStageId: SourceCollectionStageModuleId | string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageAgentChatState: (stageId: any) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  repairChallengeCupTeamAgentsMutation: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageActionReadinessFor: (stageId: any) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStagePrimaryAgentBinding: (stageId: any) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  stageChatLabels: Record<string, { zh: string; en: string }>;
  openSourceCollectionStageAgentChat: (stageId: any) => void;
  sourceCollectionFindingStageCompact: boolean;
  selectedTeamStartSourceCollectionStageTaskError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionConversation: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionCandidatePanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionScreeningPanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionGraphPanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionMemoryPanel: () => ReactNode;
};

export function TeamSourceCollectionActiveStageWorkspacePanel(props: TeamSourceCollectionActiveStageWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionStageModules,
    selectedSourceCollectionStageId,
    sourceCollectionStageAgentChatState,
    repairChallengeCupTeamAgentsMutation,
    sourceCollectionActionDisabledTitle,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionStagePrimaryAgentBinding,
    stageChatLabels,
    openSourceCollectionStageAgentChat,
    sourceCollectionFindingStageCompact,
    selectedTeamStartSourceCollectionStageTaskError,
    renderSourceCollectionConversation,
    renderSourceCollectionCandidatePanel,
    renderSourceCollectionScreeningPanel,
    renderSourceCollectionGraphPanel,
    renderSourceCollectionMemoryPanel,
  } = props;

`;

// Active stage body uses SOURCE_COLLECTION_STAGE_CHAT_LABELS — rewrite to stageChatLabels
let activeBody = active.body.replace(/SOURCE_COLLECTION_STAGE_CHAT_LABELS/g, "stageChatLabels");

const selectedOut = "src/routes/TeamSourceCollectionSelectedSourceWorkspacePanel.tsx";
const controlsOut = "src/routes/TeamSourceCollectionControlsWorkspacePanel.tsx";
const activeOut = "src/routes/TeamSourceCollectionActiveStageWorkspacePanel.tsx";

writeFileSync(selectedOut, `${selectedHeader}${selected.body}\n}\n`);
writeFileSync(controlsOut, `${controlsHeader}${controls.body}\n}\n`);
writeFileSync(activeOut, `${activeHeader}${activeBody}\n}\n`);

console.log("wrote selected", selected.body.includes("缺少可读来源") || selected.body.includes("Readable source"));
console.log("wrote controls", controls.body.includes("等待启动搜集批次") || controls.body.includes("Waiting for a collection"));
console.log("wrote active", activeBody.includes("配置 Agent") || activeBody.includes("Configure Agent"));

const selectedWrapper = `  function renderSourceCollectionSelectedSourcePanel() {
    return (
      <TeamSourceCollectionSelectedSourceWorkspacePanel
        lang={lang}
        selectedSourceCollectionCandidate={selectedSourceCollectionCandidate}
        selectedSourceCollectionCandidateTrace={selectedSourceCollectionCandidateTrace}
        selectedSourceCollectionRunEffectiveId={selectedSourceCollectionRunEffectiveId}
        selectedSourceCollectionCandidateStorageArtifacts={selectedSourceCollectionCandidateStorageArtifacts}
        workflowQualityTone={workflowQualityTone}
        selectedSourceCollectionStorageOpenPending={selectedSourceCollectionStorageOpenPending}
        openSourceCollectionStorageTarget={openSourceCollectionStorageTarget}
      />
    );
  }

`;

const controlsWrapper = `  function renderSourceCollectionControlsPanel() {
    return (
      <TeamSourceCollectionControlsWorkspacePanel
        lang={lang}
        sourceCollectionControlPanelRef={sourceCollectionControlPanelRef}
        sourceCollectionStageModules={sourceCollectionStageModules}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        selectedSourceCollectionRun={selectedSourceCollectionRun}
        sourceCollectionStageFocusLabel={sourceCollectionStageFocusLabel}
        workflowIngestionTone={workflowIngestionTone}
        sourceCollectionRunStatus={sourceCollectionRunStatus}
        renderSourceCollectionSelectedSourcePanel={renderSourceCollectionSelectedSourcePanel}
        sourceCollectionDraft={sourceCollectionDraft}
        renderSourceCollectionModeFields={renderSourceCollectionModeFields}
        sourceCollectionCanStart={sourceCollectionCanStart}
        selectedTeamStartSourceCollectionPending={selectedTeamStartSourceCollectionPending}
        setSourceCollectionDraft={setSourceCollectionDraft}
        selectedTeam={selectedTeam}
        startSourceCollectionRunMutation={startSourceCollectionRunMutation}
        selectedSourceCollectionRunEffectiveId={selectedSourceCollectionRunEffectiveId}
        sourceCollectionFindingRunOptions={sourceCollectionFindingRunOptions}
        sourceCollectionFindingAssignments={sourceCollectionFindingAssignments}
        sourceCollectionFindingQueries={sourceCollectionFindingQueries}
        renderSourceCollectionStorageActions={renderSourceCollectionStorageActions}
        setSelectedSourceCollectionRunId={setSelectedSourceCollectionRunId}
        setSourceCollectionOutputDraft={setSourceCollectionOutputDraft}
        renderSourceCollectionManualWritebackPanel={renderSourceCollectionManualWritebackPanel}
        sourceCollectionDisplayedCandidateCountText={sourceCollectionDisplayedCandidateCountText}
        sourceCollectionProjectedAssessedCountText={sourceCollectionProjectedAssessedCountText}
        sourceCollectionProjectedApprovedCountText={sourceCollectionProjectedApprovedCountText}
        sourceCollectionRunPendingScreeningCountText={sourceCollectionRunPendingScreeningCountText}
        candidateGraphNodeCount={candidateGraphNodeCount}
        candidateGraphEdgeCount={candidateGraphEdgeCount}
        sourceCollectionPrecheckCandidateCount={sourceCollectionPrecheckCandidateCount}
        knowledgePendingReviewCount={knowledgePendingReviewCount}
        formalKnowledgeItemCount={formalKnowledgeItemCount}
        selectedTeamKnowledgeCollectionIngestResult={selectedTeamKnowledgeCollectionIngestResult}
        selectedTeamKnowledgeCollectionIngestError={selectedTeamKnowledgeCollectionIngestError}
        selectedTeamStartSourceCollectionError={selectedTeamStartSourceCollectionError}
        selectedTeamRecordSourceCollectionOutputError={selectedTeamRecordSourceCollectionOutputError}
        selectedTeamExecuteSourceCollectionSearchError={selectedTeamExecuteSourceCollectionSearchError}
        selectedTeamStartSourceCollectionStageTaskError={selectedTeamStartSourceCollectionStageTaskError}
        selectedTeamExecuteSourceCollectionSearchResult={selectedTeamExecuteSourceCollectionSearchResult}
        selectedTeamRecordSourceCollectionOutputResult={selectedTeamRecordSourceCollectionOutputResult}
        renderSourceCollectionStageAgents={renderSourceCollectionStageAgents}
      />
    );
  }

`;

const activeWrapper = `  function renderSourceCollectionActiveStagePanel() {
    return (
      <TeamSourceCollectionActiveStageWorkspacePanel
        lang={lang}
        sourceCollectionStageModules={sourceCollectionStageModules}
        selectedSourceCollectionStageId={selectedSourceCollectionStageId}
        sourceCollectionStageAgentChatState={sourceCollectionStageAgentChatState}
        repairChallengeCupTeamAgentsMutation={repairChallengeCupTeamAgentsMutation}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionStageActionReadinessFor={sourceCollectionStageActionReadinessFor}
        sourceCollectionStagePrimaryAgentBinding={sourceCollectionStagePrimaryAgentBinding}
        stageChatLabels={SOURCE_COLLECTION_STAGE_CHAT_LABELS}
        openSourceCollectionStageAgentChat={openSourceCollectionStageAgentChat}
        sourceCollectionFindingStageCompact={sourceCollectionFindingStageCompact}
        selectedTeamStartSourceCollectionStageTaskError={selectedTeamStartSourceCollectionStageTaskError}
        renderSourceCollectionConversation={renderSourceCollectionConversation}
        renderSourceCollectionCandidatePanel={renderSourceCollectionCandidatePanel}
        renderSourceCollectionScreeningPanel={renderSourceCollectionScreeningPanel}
        renderSourceCollectionGraphPanel={renderSourceCollectionGraphPanel}
        renderSourceCollectionMemoryPanel={renderSourceCollectionMemoryPanel}
      />
    );
  }

`;

let next = src;
next = next.slice(0, active.start) + activeWrapper + next.slice(active.end);
next = next.slice(0, controls.start) + controlsWrapper + next.slice(controls.end);
next = next.slice(0, selected.start) + selectedWrapper + next.slice(selected.end);

if (!next.includes('"TeamSourceCollectionActiveStageWorkspacePanel"')) {
  next = next.replace(
    'const TeamSourceCollectionMemoryWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionMemoryWorkspacePanel");',
    `const TeamSourceCollectionMemoryWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionMemoryWorkspacePanel");
const TeamSourceCollectionSelectedSourceWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionSelectedSourceWorkspacePanel");
const TeamSourceCollectionControlsWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionControlsWorkspacePanel");
const TeamSourceCollectionActiveStageWorkspacePanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamSourceCollectionActiveStageWorkspacePanel");`,
  );
}

writeFileSync(routePath, next);
console.log("rewrote TeamsRoute.tsx delta", next.length - src.length);

const secondaryPath = "src/routes/teams/teamSecondaryPanels.ts";
let secondary = readFileSync(secondaryPath, "utf8");
if (!secondary.includes("TeamSourceCollectionActiveStageWorkspacePanel")) {
  secondary += `
export { TeamSourceCollectionSelectedSourceWorkspacePanel } from "../TeamSourceCollectionSelectedSourceWorkspacePanel";
export { TeamSourceCollectionControlsWorkspacePanel } from "../TeamSourceCollectionControlsWorkspacePanel";
export { TeamSourceCollectionActiveStageWorkspacePanel } from "../TeamSourceCollectionActiveStageWorkspacePanel";
`;
  writeFileSync(secondaryPath, secondary);
  console.log("updated teamSecondaryPanels.ts");
}
