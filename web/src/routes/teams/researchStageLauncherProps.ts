import type { ReactNode } from "react";
import type { NavigateFunction } from "react-router-dom";

import type { Team } from "../../api/types";
import type { ExperimentPlanningStatusPayload } from "./experimentLoopModel";
import type { SourceCollectionDraft } from "./source-collection/presentationModel";
import type {
  ResearchStagePhaseStatus,
  ResearchStageRoundStatusPayload,
  ResearchStageType,
} from "./source-collection/stageProjection";

type Lang = "zh" | "en";

type QueryLike = {
  isPending: boolean;
  isFetching: boolean;
  refetch: () => unknown;
};

type ErrorableQueryLike = QueryLike & {
  isError: boolean;
};

type Readiness = {
  disabled: boolean;
  reason?: string;
  loading?: boolean;
};

/**
 * Grouped injection model for the research stage launcher.
 * TeamsRoute assembles these bags; the panel flattens to local bindings.
 */
export type TeamResearchStageLauncherPanelProps = {
  lang: Lang;
  /**
   * overview: stage cards are read-only progress (no start/play CTAs).
   * interactive: full launch + details actions (stage pages / non-overview).
   */
  presentationMode?: "overview" | "interactive";
  team: {
    researchWorkflowSelected: boolean;
    challengeCupSelected: boolean;
    knowledgeExpansionSelected: boolean;
    selected: Team | null | undefined;
    memoryMembers: Array<{
      id: string;
      agentName: string;
      agentCode: string;
      roleLabel: string;
      statusTitle: string;
      statusLabel: string;
      statusTone: string;
      configRoute: string;
    }>;
    detailDegraded: boolean;
    detailLoading: boolean;
    detailQuery: { isFetching: boolean; refetch: () => unknown };
  };
  sourceCollection: {
    draft: SourceCollectionDraft;
    setDraft: (updater: (current: SourceCollectionDraft) => SourceCollectionDraft) => void;
    displayState: { statusText: string };
    selectedRun: { runId: string } | null | undefined;
    selectedRunEffectiveId: string;
    selectedAssignment: { status: string; agentRole: string; assignmentId: string } | null | undefined;
    searchOpenAssignmentCount: number;
    searchOpenAssignmentCountText: string;
    executeSearchPending: boolean;
    acceptedBackgroundActive: boolean;
    downstreamOpenAssignmentCount: number;
    downstreamOpenAssignmentCountText: string;
    pendingScreeningCount: number;
    startPending: boolean;
    canStart: boolean;
    searchActionReadiness: Readiness;
    actionInitialDataPending: boolean;
    actionDataError: boolean;
    actionBusyReason: string;
    actionNoInputReason: string;
    actionLoadingReason: string;
    actionErrorReason: string;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    actionReadiness: (...args: any[]) => Readiness;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    executeSearchMutation: { mutate: (payload: any) => void };
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    startRunMutation: { mutate: (payload: any) => void };
    collectedCountText: string;
    displayedCandidateCountText: string;
    queryCountText: string;
    runLoopAction: () => void;
    loopActionDisabled: boolean;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    actionDisabledTitle: (readiness: any, label: string) => string | undefined;
    loopActionReadiness: Readiness;
    loopActionLabel: string;
    loopStartsNewRun: boolean;
  };
  researchStage: {
    startPending: boolean;
    canLaunch: boolean;
    launch: (stageType: ResearchStageType, mode?: "continue_or_start" | "new_round") => void;
    roundStatus: ResearchStageRoundStatusPayload | null | undefined;
    roundStatusQuery: ErrorableQueryLike;
    phases: ResearchStagePhaseStatus[];
    startError: Error | null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    startResult: any;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    startFeedbackText: (payload: any, lang: Lang, stageLabel?: string) => string;
  };
  experiment: {
    preferredMethod: string;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    setPreferredMethod: (method: any) => void;
    planningStatus: ExperimentPlanningStatusPayload | null | undefined;
    planningStatusQuery: QueryLike;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    methodCatalogQuery: { data?: any; isFetching: boolean };
  };
  navigation: {
    navigate: NavigateFunction;
    searchParams: URLSearchParams;
  };
  renderResearchStageAgentSummary: (stageType: ResearchStageType) => ReactNode;
  renderChallengeCupStageAgentConfiguration: (stageType: ResearchStageType) => ReactNode;
};

/** Flat locals used inside the legacy panel body (stable names for minimal churn). */
export type TeamResearchStageLauncherFlatBindings = {
  researchWorkflowTeamSelected: boolean;
  challengeCupResearchTeamSelected: boolean;
  knowledgeExpansionWorkflowTeamSelected: boolean;
  experimentPlanningStatus: ExperimentPlanningStatusPayload | null | undefined;
  selectedTeam: Team | null | undefined;
  selectedTeamMemoryMembers: TeamResearchStageLauncherPanelProps["team"]["memoryMembers"];
  lang: Lang;
  presentationMode: "overview" | "interactive";
  sourceCollectionDraft: SourceCollectionDraft;
  setSourceCollectionDraft: TeamResearchStageLauncherPanelProps["sourceCollection"]["setDraft"];
  preferredExperimentMethod: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  setPreferredExperimentMethod: (method: any) => void;
  experimentPlanningStatusQuery: QueryLike;
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
  sourceCollectionSearchActionReadiness: Readiness;
  sourceCollectionActionInitialDataPending: boolean;
  sourceCollectionActionDataError: boolean;
  sourceCollectionActionBusyReason: string;
  sourceCollectionActionNoInputReason: string;
  sourceCollectionActionLoadingReason: string;
  sourceCollectionActionErrorReason: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionReadiness: (...args: any[]) => Readiness;
  selectedSourceCollectionAssignment: { status: string; agentRole: string; assignmentId: string } | null | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  executeSourceCollectionSearchMutation: { mutate: (payload: any) => void };
  selectedSourceCollectionRunEffectiveId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  startSourceCollectionRunMutation: { mutate: (payload: any) => void };
  launchResearchStage: TeamResearchStageLauncherPanelProps["researchStage"]["launch"];
  navigate: NavigateFunction;
  researchStageRoundStatus: ResearchStageRoundStatusPayload | null | undefined;
  researchStageRoundStatusQuery: ErrorableQueryLike;
  researchStagePhases: ResearchStagePhaseStatus[];
  searchParams: URLSearchParams;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  experimentMethodCatalogQuery: { data?: any; isFetching: boolean };
  researchTeamDetailDegraded: boolean;
  selectedTeamDetailLoading: boolean;
  teamDetailQuery: { isFetching: boolean; refetch: () => unknown };
  sourceCollectionSearchOpenAssignmentCountText: string;
  sourceCollectionDownstreamOpenAssignmentCountText: string;
  sourceCollectionCollectedCountText: string;
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionQueryCountText: string;
  renderResearchStageAgentSummary: (stageType: ResearchStageType) => ReactNode;
  renderChallengeCupStageAgentConfiguration: (stageType: ResearchStageType) => ReactNode;
  runKnowledgeCollectionLoopAction: () => void;
  sourceCollectionLoopActionDisabled: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  sourceCollectionLoopActionReadiness: Readiness;
  sourceCollectionLoopActionLabel: string;
  sourceCollectionLoopStartsNewRun: boolean;
  selectedTeamStartResearchStageError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedTeamStartResearchStageResult: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  researchStageStartFeedbackText: (payload: any, lang: Lang, stageLabel?: string) => string;
};

export function flattenResearchStageLauncherProps(
  props: TeamResearchStageLauncherPanelProps,
): TeamResearchStageLauncherFlatBindings {
  const { team, sourceCollection, researchStage, experiment, navigation } = props;
  return {
    researchWorkflowTeamSelected: team.researchWorkflowSelected,
    challengeCupResearchTeamSelected: team.challengeCupSelected,
    knowledgeExpansionWorkflowTeamSelected: team.knowledgeExpansionSelected,
    experimentPlanningStatus: experiment.planningStatus,
    selectedTeam: team.selected,
    selectedTeamMemoryMembers: team.memoryMembers,
    lang: props.lang,
    presentationMode: props.presentationMode ?? "interactive",
    sourceCollectionDraft: sourceCollection.draft,
    setSourceCollectionDraft: sourceCollection.setDraft,
    preferredExperimentMethod: experiment.preferredMethod,
    setPreferredExperimentMethod: experiment.setPreferredMethod,
    experimentPlanningStatusQuery: experiment.planningStatusQuery,
    sourceCollectionDisplayState: sourceCollection.displayState,
    selectedSourceCollectionRun: sourceCollection.selectedRun,
    sourceCollectionSearchOpenAssignmentCount: sourceCollection.searchOpenAssignmentCount,
    selectedTeamExecuteSourceCollectionSearchPending: sourceCollection.executeSearchPending,
    sourceCollectionAcceptedBackgroundActive: sourceCollection.acceptedBackgroundActive,
    sourceCollectionDownstreamOpenAssignmentCount: sourceCollection.downstreamOpenAssignmentCount,
    sourceCollectionRunPendingScreeningCount: sourceCollection.pendingScreeningCount,
    selectedTeamStartSourceCollectionPending: sourceCollection.startPending,
    sourceCollectionCanStart: sourceCollection.canStart,
    selectedTeamStartResearchStagePending: researchStage.startPending,
    researchStageCanLaunch: researchStage.canLaunch,
    sourceCollectionSearchActionReadiness: sourceCollection.searchActionReadiness,
    sourceCollectionActionInitialDataPending: sourceCollection.actionInitialDataPending,
    sourceCollectionActionDataError: sourceCollection.actionDataError,
    sourceCollectionActionBusyReason: sourceCollection.actionBusyReason,
    sourceCollectionActionNoInputReason: sourceCollection.actionNoInputReason,
    sourceCollectionActionLoadingReason: sourceCollection.actionLoadingReason,
    sourceCollectionActionErrorReason: sourceCollection.actionErrorReason,
    sourceCollectionActionReadiness: sourceCollection.actionReadiness,
    selectedSourceCollectionAssignment: sourceCollection.selectedAssignment,
    executeSourceCollectionSearchMutation: sourceCollection.executeSearchMutation,
    selectedSourceCollectionRunEffectiveId: sourceCollection.selectedRunEffectiveId,
    startSourceCollectionRunMutation: sourceCollection.startRunMutation,
    launchResearchStage: researchStage.launch,
    navigate: navigation.navigate,
    researchStageRoundStatus: researchStage.roundStatus,
    researchStageRoundStatusQuery: researchStage.roundStatusQuery,
    researchStagePhases: researchStage.phases,
    searchParams: navigation.searchParams,
    experimentMethodCatalogQuery: experiment.methodCatalogQuery,
    researchTeamDetailDegraded: team.detailDegraded,
    selectedTeamDetailLoading: team.detailLoading,
    teamDetailQuery: team.detailQuery,
    sourceCollectionSearchOpenAssignmentCountText: sourceCollection.searchOpenAssignmentCountText,
    sourceCollectionDownstreamOpenAssignmentCountText: sourceCollection.downstreamOpenAssignmentCountText,
    sourceCollectionCollectedCountText: sourceCollection.collectedCountText,
    sourceCollectionDisplayedCandidateCountText: sourceCollection.displayedCandidateCountText,
    sourceCollectionQueryCountText: sourceCollection.queryCountText,
    renderResearchStageAgentSummary: props.renderResearchStageAgentSummary,
    renderChallengeCupStageAgentConfiguration: props.renderChallengeCupStageAgentConfiguration,
    runKnowledgeCollectionLoopAction: sourceCollection.runLoopAction,
    sourceCollectionLoopActionDisabled: sourceCollection.loopActionDisabled,
    sourceCollectionActionDisabledTitle: sourceCollection.actionDisabledTitle,
    sourceCollectionLoopActionReadiness: sourceCollection.loopActionReadiness,
    sourceCollectionLoopActionLabel: sourceCollection.loopActionLabel,
    sourceCollectionLoopStartsNewRun: sourceCollection.loopStartsNewRun,
    selectedTeamStartResearchStageError: researchStage.startError,
    selectedTeamStartResearchStageResult: researchStage.startResult,
    researchStageStartFeedbackText: researchStage.startFeedbackText,
  };
}
