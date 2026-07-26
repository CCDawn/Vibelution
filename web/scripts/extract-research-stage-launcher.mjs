/**
 * Wave 8H: extract renderResearchStageLauncher into TeamResearchStageLauncherPanel.
 * Usage (from web/): node scripts/extract-research-stage-launcher.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/TeamsRoute.tsx";
const outPath = "src/routes/TeamResearchStageLauncherPanel.tsx";
const src = readFileSync(routePath, "utf8");

const start = src.indexOf("  function renderResearchStageLauncher() {");
const end = src.indexOf("  function renderResearchCanvasReadOnlyPanel() {");
if (start < 0 || end <= start) {
  console.error("launcher markers not found", start, end);
  process.exit(1);
}

const fn = src.slice(start, end);
// Drop "  function renderResearchStageLauncher() " keep body starting at {
const bodyStart = fn.indexOf("{");
const body = fn.slice(bodyStart); // { ... }\n\n

const propsFields = [
  "researchWorkflowTeamSelected",
  "challengeCupResearchTeamSelected",
  "knowledgeExpansionWorkflowTeamSelected",
  "experimentPlanningStatus",
  "selectedTeam",
  "selectedTeamMemoryMembers",
  "lang",
  "challengeTeamSurface",
  "sourceCollectionDraft",
  "setSourceCollectionDraft",
  "preferredExperimentMethod",
  "setPreferredExperimentMethod",
  "experimentPlanningStatusQuery",
  "sourceCollectionDisplayState",
  "selectedSourceCollectionRun",
  "sourceCollectionSearchOpenAssignmentCount",
  "selectedTeamExecuteSourceCollectionSearchPending",
  "sourceCollectionAcceptedBackgroundActive",
  "sourceCollectionDownstreamOpenAssignmentCount",
  "sourceCollectionRunPendingScreeningCount",
  "selectedTeamStartSourceCollectionPending",
  "sourceCollectionCanStart",
  "selectedTeamStartResearchStagePending",
  "researchStageCanLaunch",
  "sourceCollectionSearchActionReadiness",
  "sourceCollectionActionInitialDataPending",
  "sourceCollectionActionDataError",
  "sourceCollectionActionBusyReason",
  "sourceCollectionActionNoInputReason",
  "sourceCollectionActionLoadingReason",
  "sourceCollectionActionErrorReason",
  "sourceCollectionActionReadiness",
  "selectedSourceCollectionAssignment",
  "executeSourceCollectionSearchMutation",
  "selectedSourceCollectionRunEffectiveId",
  "startSourceCollectionRunMutation",
  "launchResearchStage",
  "navigate",
  "researchStageRoundStatus",
  "researchStageRoundStatusQuery",
  "researchStagePhases",
  "searchParams",
  "experimentMethodCatalogQuery",
  "researchTeamDetailDegraded",
  "selectedTeamDetailLoading",
  "teamDetailQuery",
  "sourceCollectionSearchOpenAssignmentCountText",
  "sourceCollectionDownstreamOpenAssignmentCountText",
  "sourceCollectionCollectedCountText",
  "sourceCollectionDisplayedCandidateCountText",
  "sourceCollectionQueryCountText",
  "renderResearchStageAgentSummary",
  "runKnowledgeCollectionLoopAction",
  "sourceCollectionLoopActionDisabled",
  "sourceCollectionActionDisabledTitle",
  "sourceCollectionLoopActionReadiness",
  "sourceCollectionLoopActionLabel",
  "sourceCollectionLoopStartsNewRun",
  "selectedTeamStartResearchStageError",
  "selectedTeamStartResearchStageResult",
];

const header = `/**
 * Research stage launcher console (three-stage + Challenge Cup branch).
 * Wave 8H: extracted from TeamsRoute.tsx for domain componentization.
 * Presentation + local pure helpers; mutations/query objects injected by the route.
 */
import { CheckCircle2, Eye, Link2, Play, RefreshCw, Settings2 } from "lucide-react";
import type { NavigateFunction } from "react-router-dom";
import { Link } from "react-router-dom";

import type { ExperimentMethodId } from "../api/types";
import { VNativeButton, VNativeInput, VNativeSelect } from "../components/vui";
import {
  ChallengeCupOperationsWorkspace,
  type ChallengeCupWorkspaceAgent,
} from "./teams/challenge-cup/ChallengeCupOperationsWorkspace";
import {
  researchIterationLifecycleStatusLabel,
  type ExperimentMethodCatalogPayload,
  type ExperimentPlanningStatusPayload,
  type ExperimentPlanRecord,
} from "./teams/experimentLoopModel";
import { isChallengeCupResearchWorkflowTeam } from "./teams/teamKindModel";
import {
  RESEARCH_TEAM_ID,
  RESEARCH_WORKSPACE_NAV_ITEMS,
  researchCanvasRoute,
  researchSourceCollectionRoute,
  researchWorkspaceStageRoute,
  researchWorkspaceViewLabel,
  type ResearchStageWorkspaceView,
} from "./teams/researchWorkspaceModel";
import type {
  ResearchStagePhaseStatus,
  ResearchStageRoundStatusPayload,
  ResearchStageType,
} from "./teams/source-collection/stageProjection";
import { sourceCollectionRunLabel } from "./teams/source-collection/presentationModel";
import type { SourceCollectionDraft } from "./teams/source-collection/presentationModel";
import { SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES } from "./teams/source-collection/presentationModel";
import { ResearchProjectSwitcher } from "./teams/research-projects/ResearchProjectSwitcher";
import { ResearchMemoryEvidencePanel } from "./teams/ResearchMemoryEvidencePanel";
import type { ResearchMemoryContextSummary } from "./teams/experimentLoopModel";
import researchStyles from "./TeamsRoute.research.styles";
import shellStyles from "./TeamsRoute.styles";

const styles = { ...shellStyles, ...researchStyles } as Record<string, string>;

type Lang = "zh" | "en";

type ActionReadiness = {
  disabled: boolean;
  reason?: string;
  loading?: boolean;
};

export type TeamResearchStageLauncherPanelProps = {
  researchWorkflowTeamSelected: boolean;
  challengeCupResearchTeamSelected: boolean;
  knowledgeExpansionWorkflowTeamSelected: boolean;
  experimentPlanningStatus: ExperimentPlanningStatusPayload | null | undefined;
  selectedTeam: { teamId: string; members?: unknown[] } | null | undefined;
  selectedTeamMemoryMembers: Array<{
    id: string;
    agentName: string;
    agentCode: string;
    roleLabel: string;
    statusTitle: string;
    statusLabel: string;
    statusTone: string;
    configRoute: string;
  }>;
  lang: Lang;
  challengeTeamSurface: "workspace" | "progress";
  sourceCollectionDraft: SourceCollectionDraft;
  setSourceCollectionDraft: (updater: (current: SourceCollectionDraft) => SourceCollectionDraft) => void;
  preferredExperimentMethod: string;
  setPreferredExperimentMethod: (method: ExperimentMethodId | string) => void;
  experimentPlanningStatusQuery: {
    isPending: boolean;
    isFetching: boolean;
    refetch: () => unknown;
  };
  sourceCollectionDisplayState: { statusText: string };
  selectedSourceCollectionRun: { runId: string } | null | undefined;
  sourceCollectionSearchOpenAssignmentCount: number;
  selectedTeamExecuteSourceCollectionSearchPending: boolean;
  sourceCollectionAcceptedBackgroundActive: boolean;
  sourceCollectionDownstreamOpenAssignmentCount: number;
  sourceCollectionRunPendingScreeningCount: number;
  selectedTeamStartSourceCollectionPending: boolean;
  sourceCollectionCanStart: boolean;
  selectedTeamStartResearchStagePending: boolean;
  researchStageCanLaunch: boolean;
  sourceCollectionSearchActionReadiness: ActionReadiness;
  sourceCollectionActionInitialDataPending: boolean;
  sourceCollectionActionDataError: boolean;
  sourceCollectionActionBusyReason: string;
  sourceCollectionActionNoInputReason: string;
  sourceCollectionActionLoadingReason: string;
  sourceCollectionActionErrorReason: string;
  sourceCollectionActionReadiness: (disabled: boolean, reason?: string, loading?: boolean) => ActionReadiness;
  selectedSourceCollectionAssignment: { status: string; agentRole: string; assignmentId: string } | null | undefined;
  executeSourceCollectionSearchMutation: { mutate: (payload: Record<string, unknown>) => void };
  selectedSourceCollectionRunEffectiveId: string;
  startSourceCollectionRunMutation: { mutate: (payload: { teamId: string; draft: SourceCollectionDraft }) => void };
  launchResearchStage: (stageType: ResearchStageType, mode?: "continue_or_start" | "new_round") => void;
  navigate: NavigateFunction;
  researchStageRoundStatus: ResearchStageRoundStatusPayload | null | undefined;
  researchStageRoundStatusQuery: {
    isPending: boolean;
    isError: boolean;
    isFetching: boolean;
    refetch: () => unknown;
  };
  researchStagePhases: ResearchStagePhaseStatus[];
  searchParams: URLSearchParams;
  experimentMethodCatalogQuery: {
    data?: ExperimentMethodCatalogPayload;
    isFetching: boolean;
  };
  researchTeamDetailDegraded: boolean;
  selectedTeamDetailLoading: boolean;
  teamDetailQuery: { isFetching: boolean; refetch: () => unknown };
  sourceCollectionSearchOpenAssignmentCountText: string;
  sourceCollectionDownstreamOpenAssignmentCountText: string;
  sourceCollectionCollectedCountText: string;
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionQueryCountText: string;
  renderResearchStageAgentSummary: (stageType: ResearchStageType) => React.ReactNode;
  runKnowledgeCollectionLoopAction: () => void;
  sourceCollectionLoopActionDisabled: boolean;
  sourceCollectionActionDisabledTitle: (readiness: ActionReadiness, label: string) => string | undefined;
  sourceCollectionLoopActionReadiness: ActionReadiness;
  sourceCollectionLoopActionLabel: string;
  sourceCollectionLoopStartsNewRun: boolean;
  selectedTeamStartResearchStageError: Error | null;
  selectedTeamStartResearchStageResult: {
    stageRound?: { stageType: string; roundNumber: number };
    reusedExistingRound?: boolean;
    sourceCollectionRef?: { runId: string; recordCount: number; openAssignmentCount: number };
  } | null;
  researchStageStartFeedbackText: (
    payload: {
      stageRound: { stageType: string; roundNumber: number };
      reusedExistingRound?: boolean;
      sourceCollectionRef?: { runId: string; recordCount: number; openAssignmentCount: number };
    },
    lang: Lang,
    stageLabel?: string,
  ) => string;
};

export function TeamResearchStageLauncherPanel(props: TeamResearchStageLauncherPanelProps) {
  const {
${propsFields.map((f) => `    ${f},`).join("\n")}
  } = props;

`;

// body is `{ ... }\n\n` from the original function — use as component body
const component = `${header}${body.slice(1)}`; // drop leading `{` then we already have destructure; need opening brace after destructure

// Fix: header ends with destructure, then we need body without outer braces of original function
// original body = `{ statements }\n\n`
// We want: `export function ... { const {..} = props; statements }`
const statements = body.slice(1, body.lastIndexOf("}")); // drop outer { and last }
const fixed = `${header}${statements}
}
`;

writeFileSync(outPath, fixed);
console.log("wrote", outPath, "chars", fixed.length);

// Replace in TeamsRoute
const replacement = `  function renderResearchStageLauncher() {
    return (
      <TeamResearchStageLauncherPanel
        researchWorkflowTeamSelected={researchWorkflowTeamSelected}
        challengeCupResearchTeamSelected={challengeCupResearchTeamSelected}
        knowledgeExpansionWorkflowTeamSelected={knowledgeExpansionWorkflowTeamSelected}
        experimentPlanningStatus={experimentPlanningStatus}
        selectedTeam={selectedTeam}
        selectedTeamMemoryMembers={selectedTeamMemoryMembers}
        lang={lang}
        challengeTeamSurface={challengeTeamSurface}
        sourceCollectionDraft={sourceCollectionDraft}
        setSourceCollectionDraft={setSourceCollectionDraft}
        preferredExperimentMethod={preferredExperimentMethod}
        setPreferredExperimentMethod={setPreferredExperimentMethod}
        experimentPlanningStatusQuery={experimentPlanningStatusQuery}
        sourceCollectionDisplayState={sourceCollectionDisplayState}
        selectedSourceCollectionRun={selectedSourceCollectionRun}
        sourceCollectionSearchOpenAssignmentCount={sourceCollectionSearchOpenAssignmentCount}
        selectedTeamExecuteSourceCollectionSearchPending={selectedTeamExecuteSourceCollectionSearchPending}
        sourceCollectionAcceptedBackgroundActive={sourceCollectionAcceptedBackgroundActive}
        sourceCollectionDownstreamOpenAssignmentCount={sourceCollectionDownstreamOpenAssignmentCount}
        sourceCollectionRunPendingScreeningCount={sourceCollectionRunPendingScreeningCount}
        selectedTeamStartSourceCollectionPending={selectedTeamStartSourceCollectionPending}
        sourceCollectionCanStart={sourceCollectionCanStart}
        selectedTeamStartResearchStagePending={selectedTeamStartResearchStagePending}
        researchStageCanLaunch={researchStageCanLaunch}
        sourceCollectionSearchActionReadiness={sourceCollectionSearchActionReadiness}
        sourceCollectionActionInitialDataPending={sourceCollectionActionInitialDataPending}
        sourceCollectionActionDataError={sourceCollectionActionDataError}
        sourceCollectionActionBusyReason={sourceCollectionActionBusyReason}
        sourceCollectionActionNoInputReason={sourceCollectionActionNoInputReason}
        sourceCollectionActionLoadingReason={sourceCollectionActionLoadingReason}
        sourceCollectionActionErrorReason={sourceCollectionActionErrorReason}
        sourceCollectionActionReadiness={sourceCollectionActionReadiness}
        selectedSourceCollectionAssignment={selectedSourceCollectionAssignment}
        executeSourceCollectionSearchMutation={executeSourceCollectionSearchMutation}
        selectedSourceCollectionRunEffectiveId={selectedSourceCollectionRunEffectiveId}
        startSourceCollectionRunMutation={startSourceCollectionRunMutation}
        launchResearchStage={launchResearchStage}
        navigate={navigate}
        researchStageRoundStatus={researchStageRoundStatus}
        researchStageRoundStatusQuery={researchStageRoundStatusQuery}
        researchStagePhases={researchStagePhases}
        searchParams={searchParams}
        experimentMethodCatalogQuery={experimentMethodCatalogQuery}
        researchTeamDetailDegraded={researchTeamDetailDegraded}
        selectedTeamDetailLoading={selectedTeamDetailLoading}
        teamDetailQuery={teamDetailQuery}
        sourceCollectionSearchOpenAssignmentCountText={sourceCollectionSearchOpenAssignmentCountText}
        sourceCollectionDownstreamOpenAssignmentCountText={sourceCollectionDownstreamOpenAssignmentCountText}
        sourceCollectionCollectedCountText={sourceCollectionCollectedCountText}
        sourceCollectionDisplayedCandidateCountText={sourceCollectionDisplayedCandidateCountText}
        sourceCollectionQueryCountText={sourceCollectionQueryCountText}
        renderResearchStageAgentSummary={renderResearchStageAgentSummary}
        runKnowledgeCollectionLoopAction={runKnowledgeCollectionLoopAction}
        sourceCollectionLoopActionDisabled={sourceCollectionLoopActionDisabled}
        sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
        sourceCollectionLoopActionReadiness={sourceCollectionLoopActionReadiness}
        sourceCollectionLoopActionLabel={sourceCollectionLoopActionLabel}
        sourceCollectionLoopStartsNewRun={sourceCollectionLoopStartsNewRun}
        selectedTeamStartResearchStageError={selectedTeamStartResearchStageError}
        selectedTeamStartResearchStageResult={selectedTeamStartResearchStageResult}
        researchStageStartFeedbackText={researchStageStartFeedbackText}
      />
    );
  }

`;

const next = src.slice(0, start) + replacement + src.slice(end);
// ensure lazy import exists
let wired = next;
if (!wired.includes("TeamResearchStageLauncherPanel")) {
  console.error("replacement missing component name");
}
if (!wired.includes('createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageLauncherPanel")')) {
  wired = wired.replace(
    "const TeamResearchStageAgentSummary = createLazyNamedTeamPanel(loadTeamSecondaryPanels, \"TeamResearchStageAgentSummary\");",
    `const TeamResearchStageAgentSummary = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageAgentSummary");
const TeamResearchStageLauncherPanel = createLazyNamedTeamPanel(loadTeamSecondaryPanels, "TeamResearchStageLauncherPanel");`,
  );
}
writeFileSync(routePath, wired);
console.log("patched TeamsRoute.tsx");
