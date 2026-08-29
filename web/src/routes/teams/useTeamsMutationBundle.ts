/**
 * Wire all Teams mutation hooks in one place.
 * Phase R2-g extract from useTeamsWorkbenchModel (behavior-conserving).
 */
import type { Dispatch, MutableRefObject, SetStateAction } from "react";
import type { NavigateFunction, SetURLSearchParams } from "react-router-dom";

import type { Team, TeamOrganizationCanvas } from "../../api/types";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import type {
  ExperimentFullRunResultDraft,
  ExperimentKnowledgeIngestionDraft,
  ExperimentSmokeResultDraft,
  ResearchLoopDecisionDraft,
  ResearchLoopEvidenceDraft,
} from "./experimentLoopModel";
import type { ResearchWorkspaceView } from "./researchWorkspaceModel";
import { researchSourceCollectionRoute } from "./researchWorkspaceModel";
import { writableTeamCanvas } from "./researchStageAgentPresentation";
import type { SourceCollectionDraft } from "./source-collection/presentationModel";
import type { SourceCollectionStageModuleId } from "./source-collection/stageProjection";
import type { SourceCollectionOutputDraft } from "./sourceCollectionMutationModel";
import { useTeamExperimentLoopMutations } from "./useTeamExperimentLoopMutations";
import { useTeamShellMutations } from "./useTeamShellMutations";
import { useTeamSourceCollectionMutations } from "./useTeamSourceCollectionMutations";
import { useTeamWorkflowStartMutations } from "./useTeamWorkflowStartMutations";

export type TeamsChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;

export type UseTeamsMutationBundleOptions = {
  selectedTeamId: string;
  setSelectedTeamId: Dispatch<SetStateAction<string>>;
  setSelectedNodeId: Dispatch<SetStateAction<string>>;
  setSearchParams: SetURLSearchParams;
  setTeamMessage: Dispatch<SetStateAction<string>>;
  setTeamTaskTopic: Dispatch<SetStateAction<string>>;
  chatWorkspaceCache: TeamsChatWorkspaceCache;
  selectedTeam: Team | null;
  knowledgeExpansionWorkflowTeamSelected: boolean;
  sourceCollectionOwnerAgentId: string;
  sourceCollectionAgentIds: Record<string, string>;
  sourceCollectionExtractorAgentId: string;
  sourceCollectionRelationMapperAgentId: string;
  sourceCollectionIngestorAgentId: string;
  activeSourceCollectionResearchProjectId: string;
  sourceCollectionStandalone: boolean;
  sourceCollectionDraft: SourceCollectionDraft;
  setSelectedSourceCollectionRunId: Dispatch<SetStateAction<string>>;
  setSourceCollectionStageSyncUntilMs: Dispatch<SetStateAction<number>>;
  setSourceCollectionPendingStageTaskIds: Dispatch<
    SetStateAction<Partial<Record<SourceCollectionStageModuleId, string[]>>>
  >;
  setSourceCollectionOutputDraft: Dispatch<SetStateAction<SourceCollectionOutputDraft>>;
  setResearchWorkspaceView: Dispatch<SetStateAction<ResearchWorkspaceView>>;
  navigate: NavigateFunction;
  latestExperimentStageRoundId: string;
  setExperimentSmokeResultDraft: Dispatch<SetStateAction<ExperimentSmokeResultDraft>>;
  setExperimentFullRunResultDraft: Dispatch<SetStateAction<ExperimentFullRunResultDraft>>;
  setExperimentKnowledgeIngestionDraft: Dispatch<SetStateAction<ExperimentKnowledgeIngestionDraft>>;
  setResearchLoopEvidenceDraft: Dispatch<SetStateAction<ResearchLoopEvidenceDraft>>;
  setResearchLoopDecisionDraft: Dispatch<SetStateAction<ResearchLoopDecisionDraft>>;
  scrollSourceCollectionPanelIntoViewRef: MutableRefObject<(panelId: string) => void>;
};

export function useTeamsMutationBundle(options: UseTeamsMutationBundleOptions) {
  const {
    selectedTeamId,
    setSelectedTeamId,
    setSelectedNodeId,
    setSearchParams,
    setTeamMessage,
    setTeamTaskTopic,
    chatWorkspaceCache,
    selectedTeam,
    knowledgeExpansionWorkflowTeamSelected,
    sourceCollectionOwnerAgentId,
    sourceCollectionAgentIds,
    sourceCollectionExtractorAgentId,
    sourceCollectionRelationMapperAgentId,
    sourceCollectionIngestorAgentId,
    activeSourceCollectionResearchProjectId,
    sourceCollectionStandalone,
    sourceCollectionDraft,
    setSelectedSourceCollectionRunId,
    setSourceCollectionStageSyncUntilMs,
    setSourceCollectionPendingStageTaskIds,
    setSourceCollectionOutputDraft,
    setResearchWorkspaceView,
    navigate,
    latestExperimentStageRoundId,
    setExperimentSmokeResultDraft,
    setExperimentFullRunResultDraft,
    setExperimentKnowledgeIngestionDraft,
    setResearchLoopEvidenceDraft,
    setResearchLoopDecisionDraft,
    scrollSourceCollectionPanelIntoViewRef,
  } = options;

  const {
    archiveTeamMutation,
    saveCanvasMutation,
    sendTeamMessageMutation,
    revokeTeamMessageMutation,
    syncTeamChatRoomMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    startTeamRoundMutation,
    stopTeamRoundMutation,
  } = useTeamShellMutations({
    selectedTeamId,
    setSelectedTeamId,
    setSelectedNodeId,
    clearTeamSearchParams: () => setSearchParams({}),
    setTeamMessage,
    setTeamTaskTopic,
    chatWorkspaceCache,
  });

  const {
    resetResearchProjectSourceCollectionMutation,
    seedSourceCollectionAgentSessionContextMutation,
    startSourceCollectionStageSessionTaskMutation,
    startAiSearchRunMutation,
    startSourceCollectionRunMutation,
    startResearchStageRoundMutation,
  } = useTeamWorkflowStartMutations({
    selectedTeam,
    knowledgeExpansionWorkflowTeamSelected,
    sourceCollectionOwnerAgentId,
    sourceCollectionAgentIds,
    activeSourceCollectionResearchProjectId,
    sourceCollectionStandalone,
    chatWorkspaceCache,
    setSelectedSourceCollectionRunId,
    setSourceCollectionStageSyncUntilMs,
    setSourceCollectionPendingStageTaskIds,
    setSourceCollectionOutputDraft,
    setResearchWorkspaceView,
    navigateToSourceCollection: (teamId) => navigate(researchSourceCollectionRoute(teamId)),
  });

  const {
    createExperimentPlanMutation,
    materializeEngineeringProxyHypothesisMutation,
    completeScientificHypothesisFromDesignMutation,
    reviewExperimentHypothesisMutation,
    createExperimentHypothesisRevisionMutation,
    freezeExperimentDesignMutation,
    resumeExperimentHypothesisMutation,
    registerExperimentBaselineArtifactMutation,
    runExperimentSmokeMutation,
    registerExperimentSmokeResultMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
    materializeResearchLoopIterationDesignMutation,
  } = useTeamExperimentLoopMutations({
    sourceCollectionOwnerAgentId,
    sourceCollectionIngestorAgentId,
    sourceCollectionDraftGoal: sourceCollectionDraft.goal,
    latestExperimentStageRoundId,
    setExperimentSmokeResultDraft,
    setExperimentFullRunResultDraft,
    setExperimentKnowledgeIngestionDraft,
    setResearchLoopEvidenceDraft,
    setResearchLoopDecisionDraft,
  });

  const {
    recordSourceCollectionOutputMutation,
    executeSourceCollectionSearchMutation,
    extractSourceCollectionCandidatesMutation,
    openSourceCollectionStorageMutation,
    assessSourceQualityMutation,
    assessSourceQualityBatchMutation,
    planPaperNoteChunksMutation,
    buildCandidateGraphMutation,
    runKnowledgeIngestionPrecheckMutation,
    runKnowledgeCollectionCompletionMutation,
  } = useTeamSourceCollectionMutations({
    sourceCollectionOwnerAgentId,
    sourceCollectionExtractorAgentId,
    sourceCollectionRelationMapperAgentId,
    sourceCollectionDraftTopic: sourceCollectionDraft.topic,
    sourceCollectionDraftMaxResultsPerQuery: sourceCollectionDraft.maxResultsPerQuery || 3,
    setSelectedSourceCollectionRunId,
    setSourceCollectionOutputDraft,
    scrollSourceCollectionPanelIntoView: (panelId) => {
      scrollSourceCollectionPanelIntoViewRef.current(panelId);
    },
  });

  const canvasSavePendingForTeam = (teamId: string | undefined | null) =>
    saveCanvasMutation.isPending && Boolean(teamId) && saveCanvasMutation.variables?.teamId === teamId;

  function saveCanvas(nextCanvas: TeamOrganizationCanvas | null) {
    if (!nextCanvas || canvasSavePendingForTeam(nextCanvas.teamId)) {
      return;
    }
    saveCanvasMutation.mutate(writableTeamCanvas(nextCanvas));
  }

  return {
    archiveTeamMutation,
    saveCanvasMutation,
    sendTeamMessageMutation,
    revokeTeamMessageMutation,
    syncTeamChatRoomMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    startTeamRoundMutation,
    stopTeamRoundMutation,
    resetResearchProjectSourceCollectionMutation,
    seedSourceCollectionAgentSessionContextMutation,
    startSourceCollectionStageSessionTaskMutation,
    startAiSearchRunMutation,
    startSourceCollectionRunMutation,
    startResearchStageRoundMutation,
    createExperimentPlanMutation,
    materializeEngineeringProxyHypothesisMutation,
    completeScientificHypothesisFromDesignMutation,
    reviewExperimentHypothesisMutation,
    createExperimentHypothesisRevisionMutation,
    freezeExperimentDesignMutation,
    resumeExperimentHypothesisMutation,
    registerExperimentBaselineArtifactMutation,
    runExperimentSmokeMutation,
    registerExperimentSmokeResultMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
    materializeResearchLoopIterationDesignMutation,
    recordSourceCollectionOutputMutation,
    executeSourceCollectionSearchMutation,
    extractSourceCollectionCandidatesMutation,
    openSourceCollectionStorageMutation,
    assessSourceQualityMutation,
    assessSourceQualityBatchMutation,
    planPaperNoteChunksMutation,
    buildCandidateGraphMutation,
    runKnowledgeIngestionPrecheckMutation,
    runKnowledgeCollectionCompletionMutation,
    canvasSavePendingForTeam,
    saveCanvas,
  };
}
