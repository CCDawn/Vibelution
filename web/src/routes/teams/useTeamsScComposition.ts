/**
 * R1-a / R2-o/p: SC composition for Teams workbench.
 * Owns presentation + stage surfaces; bag passthrough via spread (no flat re-list).
 */
import type { RuntimeSummary } from "../../api/types";
import { useSourceCollectionPresentation } from "./useSourceCollectionPresentation";
import type { UseSourceCollectionPresentationInput } from "./useSourceCollectionPresentationTypes";
import { composeSourceCollectionStageSurfaces } from "./composeSourceCollectionStageSurfaces";
import type { ComposeSourceCollectionStageSurfacesInput } from "./composeSourceCollectionStageSurfaces";
import { sourceCollectionStageUserSummary } from "./source-collection/stageProjection";

/**
 * Loose bag for SC composition; keys are presentation + stage-shell deps.
 * Foundation bag boundary: the 328-field workbench bag stays `unknown`-keyed
 * here; precise contracts are enforced at the presentation/compose casts below
 * (and by the key-list contract tests), not by re-listing the bag statically.
 */
export type TeamsScCompositionContext = {
  [key: string]: unknown;
  lang?: "zh" | "en";
  selectedTeam?: unknown;
  effectiveTeamId?: string;
};

function pickCtx(ctx: TeamsScCompositionContext, keys: readonly string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of keys) {
    if (key in ctx) out[key] = ctx[key];
  }
  return out;
}

const PRESENTATION_CTX_KEYS = ['lang', 'selectedTeam', 'effectiveTeamId', 'researchWorkflowTeamSelected', 'pageVisible', 'researchStagePhases', 'researchStageRoundStatus', 'researchStageProjectAgentTasks', 'teamWorkflowCandidates', 'teamWorkflowCandidatesQuery', 'teamWorkflowCandidateListEnabled', 'teamWorkflowSourceQualityStatus', 'teamWorkflowSourceQualityStatusQuery', 'teamWorkflowCandidateGraphQuery', 'teamWorkflowKnowledgeIngestionStatusQuery', 'teamWorkflowPaperNoteChunkStatus', 'teamWorkflow', 'sourceCollectionSummaryQuery', 'sourceCollectionRecordsQuery', 'sourceCollectionAssignmentsQuery', 'sourceCollectionRunStatusQuery', 'sourceCollectionFindingDetailsVisible', 'sourceCollectionRuns', 'sourceCollectionRunsQuery', 'sourceCollectionWorkspaceSelected', 'teamWorkflowSourceQualityEnabled', 'teamWorkflowGraphEnabled', 'teamWorkflowKnowledgeIngestionEnabled', 'selectedSourceCollectionRun', 'selectedSourceCollectionRunEffectiveId', 'sourceCollectionDraft', 'sourceCollectionOutputDraft', 'setSourceCollectionOutputDraft', 'selectedSourceCollectionCandidateId', 'setSelectedSourceCollectionCandidateId', 'sourceCollectionSourceFilter', 'setSourceCollectionSourceFilter', 'sourceCollectionResultPageByStage', 'setSourceCollectionResultPageByStage', 'selectedSourceCollectionStageId', 'setSelectedSourceCollectionStageId', 'sourceCollectionExpandedPanelId', 'setSourceCollectionExpandedPanelId', 'sourceCollectionFocusedPanelId', 'setSourceCollectionFocusedPanelId', 'activeSourceCollectionResearchProjectId', 'sourceCollectionNeedsCandidateList', 'experimentPlanningStatusQuery', 'researchLoopTemplatesQuery', 'researchLoopStatusQuery', 'aiSearchRunsQuery', 'aiSearchRunTopic', 'resetResearchProjectSourceCollectionMutation', 'startResearchStageRoundMutation', 'createExperimentPlanMutation', 'materializeEngineeringProxyHypothesisMutation', 'completeScientificHypothesisFromDesignMutation', 'reviewExperimentHypothesisMutation', 'createExperimentHypothesisRevisionMutation', 'freezeExperimentDesignMutation', 'resumeExperimentHypothesisMutation', 'registerExperimentBaselineArtifactMutation', 'runExperimentSmokeMutation', 'registerExperimentSmokeResultMutation', 'registerExperimentFullRunResultMutation', 'requestExperimentKnowledgeIngestionMutation', 'createResearchLoopMutation', 'recordResearchLoopEvidenceMutation', 'recordResearchLoopDecisionMutation', 'startSourceCollectionRunMutation', 'startSourceCollectionStageSessionTaskMutation', 'recordSourceCollectionOutputMutation', 'executeSourceCollectionSearchMutation', 'extractSourceCollectionCandidatesMutation', 'openSourceCollectionStorageMutation', 'startAiSearchRunMutation', 'buildCandidateGraphMutation', 'runKnowledgeIngestionPrecheckMutation', 'runKnowledgeCollectionCompletionMutation', 'planPaperNoteChunksMutation', 'assessSourceQualityMutation', 'assessSourceQualityBatchMutation', 'queryClient', 'setSourceCollectionStageSyncUntilMs', 'setSourceCollectionPendingStageTaskIds', 'searchParams', 'setSearchParams', 'navigate', 'scrollSourceCollectionPanelIntoViewRef', 'sourceCollectionControlPanelRef', 'sourceCollectionRelationMapperAgentId', 'sourceCollectionExtractorAgentId', 'sourceCollectionOwnerAgentId', 'sourceCollectionIngestorAgentId', 'sourceCollectionStandalone', 'sourceCollectionStageWritebackSyncActive', 'sourceCollectionPendingStageTaskIds', 'selectResearchWorkspaceView', 'launchResearchStage', 'styles'] as const;

const STAGE_SHELL_CTX_KEYS = ['activeSourceCollectionResearchProject', 'agentSummaryQuery', 'assessSourceQualityMutation', 'extractSourceCollectionCandidatesMutation', 'knowledgeExpansionWorkflowTeamSelected', 'lang', 'navigate', 'openSourceCollectionStageAgentChat', 'planPaperNoteChunksMutation', 'recordSourceCollectionOutputMutation', 'repairSelectedWorkflowTeamAgentsIfNeeded', 'resetResearchProjectSourceCollectionMutation', 'seedSourceCollectionAgentSessionContextMutation', 'selectedSourceCollectionCandidateId', 'selectedSourceCollectionRun', 'selectedSourceCollectionRunEffectiveId', 'selectedSourceCollectionStageId', 'selectedTeam', 'selectedTeamReturnRoute', 'setSelectedSourceCollectionRunId', 'setSourceCollectionDraft', 'setSourceCollectionExpandedPanelId', 'setSourceCollectionOutputDraft', 'setSourceCollectionResultPageByStage', 'setSourceCollectionSourceFilter', 'setSourceCollectionStageAdvanceFailure', 'sourceCollectionControlPanelRef', 'sourceCollectionDraft', 'sourceCollectionDraftHydratedRunIdRef', 'sourceCollectionDraftHydratedSearchPlanRef', 'sourceCollectionExpandedPanelId', 'sourceCollectionFocusedPanelId', 'sourceCollectionFreshProjectDraftIdRef', 'sourceCollectionHistoricalRunWithRecords', 'sourceCollectionOutputDraft', 'sourceCollectionOwnerAgentId', 'sourceCollectionResultPageByStage', 'sourceCollectionRuns', 'sourceCollectionShowingHistoricalRunByDefault', 'sourceCollectionSourceFilter', 'sourceCollectionStageAdvanceFailure', 'sourceCollectionStageAgentBindings', 'sourceCollectionStageAgentChatState', 'sourceCollectionStageChatReturnLabel', 'sourceCollectionStagePrimaryAgentBinding', 'sourceCollectionStageReturnRoute', 'sourceCollectionStageTaskClickKey', 'startResearchStageRoundMutation', 'startSourceCollectionRunMutation', 'startSourceCollectionStageSessionTaskMutation', 'teamWorkflowCandidateGraph', 'teamWorkflowCandidateGraphQuery', 'teamWorkflowKnowledgeIngestionStatus', 'teamWorkflowKnowledgeIngestionStatusQuery', 'teamWorkflowSourceQualityStatus', 'teamWorkflowSourceQualityStatusQuery', 'workflowIngestionToneBound', 'workflowQualityToneBound'] as const;

export function useTeamsScComposition(ctx: TeamsScCompositionContext) {
  const runtimeSummaryQuery = { data: undefined as RuntimeSummary | undefined };

  // pickCtx yields a runtime bag; presentation input is the large SC contract (enforced by contracts, not static spread).
  const presentation = useSourceCollectionPresentation({
    ...pickCtx(ctx, PRESENTATION_CTX_KEYS),
    runtimeSummaryQuery,
    requestedSourceCollectionStage: (ctx.requestedSourceCollectionStage ?? null) as UseSourceCollectionPresentationInput["requestedSourceCollectionStage"],
  } as unknown as UseSourceCollectionPresentationInput);

  // R2-k/R2-o: shell + presentation bag → stage modules / board chrome / controller.
  // The pickCtx spread drops index keys at the type level (TS limitation), so the
  // precise compose contract is asserted through unknown; key lists are enforced
  // by the composition contract tests.
  const stageSurfaces = composeSourceCollectionStageSurfaces({
    ...presentation,
    ...pickCtx(ctx, STAGE_SHELL_CTX_KEYS),
    sourceCollectionStageUserSummary,
  } as unknown as ComposeSourceCollectionStageSurfacesInput);

  return {
    ...presentation,
    ...stageSurfaces,
    lang: ctx.lang,
    // Shell helpers needed by completion-flow / stage chat chrome (not owned by presentation).
    openSourceCollectionStageAgentChat: ctx.openSourceCollectionStageAgentChat,
    sourceCollectionStagePrimaryAgentBinding: ctx.sourceCollectionStagePrimaryAgentBinding,
    sourceCollectionStageReturnRoute: ctx.sourceCollectionStageReturnRoute,
    workflowIngestionToneBound: ctx.workflowIngestionToneBound,
  };
}
