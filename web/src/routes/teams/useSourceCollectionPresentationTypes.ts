/**
 * Input contract for SC presentation core (R2-q typed bag).
 *
 * Field types are derived from the real owning hooks (resources/run-queries/
 * workspace/secondary-queries/mutation bundle) so this contract stays in sync
 * with the route data layer instead of drifting as a parallel `any` list.
 */
import type { MutableRefObject, Dispatch, SetStateAction } from "react";
import type { NavigateFunction, SetURLSearchParams } from "react-router-dom";
import type { QueryClient } from "@tanstack/react-query";
import type {
  DataProcessingRun,
  RuntimeSummary,
  Team,
  TeamWorkflowCandidate,
  TeamWorkflowOrchestration,
} from "../../api/types";
import type { SourceCollectionSourceFilter } from "./source-collection/evidenceModel";
import type {
  ResearchStageRoundStatusPayload,
  ResearchStageType,
  SourceCollectionStageModuleId,
} from "./source-collection/stageProjection";
import type { SourceCollectionDraft } from "./source-collection/presentationModel";
import type { SourceCollectionOutputDraft } from "./sourceCollectionMutationModel";
import type { ResearchWorkspaceView } from "./researchWorkspaceModel";
import type {
  TeamWorkflowPaperNoteChunkStatus,
  TeamWorkflowSourceQualityStatus,
  useResearchWorkflowResources,
} from "./useResearchWorkflowResources";
import type { useSourceCollectionRunQueries } from "./useSourceCollectionRunQueries";
import type { useSourceCollectionWorkspace } from "./useSourceCollectionWorkspace";
import type { useTeamResearchSecondaryQueries } from "./useTeamResearchSecondaryQueries";
import type { useTeamsSecondaryDataQueries } from "./useTeamsSecondaryDataQueries";
import type { useTeamsMutationBundle } from "./useTeamsMutationBundle";

type ResearchWorkflowResources = ReturnType<typeof useResearchWorkflowResources>;
type SourceCollectionRunQueries = ReturnType<typeof useSourceCollectionRunQueries>;
type SourceCollectionWorkspace = ReturnType<typeof useSourceCollectionWorkspace>;
type TeamResearchSecondaryQueries = ReturnType<typeof useTeamResearchSecondaryQueries>;
type TeamsSecondaryDataQueries = ReturnType<typeof useTeamsSecondaryDataQueries>;
type TeamsMutationBundle = ReturnType<typeof useTeamsMutationBundle>;

export type UseSourceCollectionPresentationInput = {
  lang: "zh" | "en";
  selectedTeam: Team | null;
  effectiveTeamId: string;
  researchWorkflowTeamSelected: boolean;
  pageVisible: boolean;
  researchStagePhases: ResearchStageRoundStatusPayload["phases"];
  researchStageRoundStatus: ResearchStageRoundStatusPayload | null;
  researchStageProjectAgentTasks: { isStarting: boolean; error: unknown };
  teamWorkflowCandidates: TeamWorkflowCandidate[];
  teamWorkflowCandidatesQuery: ResearchWorkflowResources["candidates"];
  teamWorkflowCandidateListEnabled: boolean;
  teamWorkflowSourceQualityStatus: TeamWorkflowSourceQualityStatus | null;
  teamWorkflowSourceQualityStatusQuery: ResearchWorkflowResources["sourceQuality"];
  teamWorkflowCandidateGraphQuery: ResearchWorkflowResources["candidateGraph"];
  teamWorkflowKnowledgeIngestionStatusQuery: ResearchWorkflowResources["knowledgeIngestion"];
  teamWorkflowPaperNoteChunkStatus: TeamWorkflowPaperNoteChunkStatus | null;
  teamWorkflow: TeamWorkflowOrchestration | null;
  runtimeSummaryQuery: { data?: RuntimeSummary };
  sourceCollectionSummaryQuery: SourceCollectionRunQueries["sourceCollectionSummaryQuery"];
  sourceCollectionRecordsQuery: SourceCollectionRunQueries["sourceCollectionRecordsQuery"];
  sourceCollectionAssignmentsQuery: SourceCollectionRunQueries["sourceCollectionAssignmentsQuery"];
  sourceCollectionRunStatusQuery: SourceCollectionRunQueries["sourceCollectionRunStatusQuery"];
  sourceCollectionFindingDetailsVisible: boolean;
  sourceCollectionRuns: DataProcessingRun[];
  sourceCollectionRunsQuery: SourceCollectionWorkspace["sourceCollectionRunsQuery"];
  sourceCollectionWorkspaceSelected: boolean;
  teamWorkflowSourceQualityEnabled: boolean;
  teamWorkflowGraphEnabled: boolean;
  teamWorkflowKnowledgeIngestionEnabled: boolean;
  selectedSourceCollectionRun: DataProcessingRun | null;
  selectedSourceCollectionRunEffectiveId: string;
  sourceCollectionDraft: SourceCollectionDraft;
  sourceCollectionOutputDraft: SourceCollectionOutputDraft;
  setSourceCollectionOutputDraft: Dispatch<SetStateAction<SourceCollectionOutputDraft>>;
  selectedSourceCollectionCandidateId: string;
  setSelectedSourceCollectionCandidateId: Dispatch<SetStateAction<string>>;
  sourceCollectionSourceFilter: SourceCollectionSourceFilter;
  setSourceCollectionSourceFilter: Dispatch<SetStateAction<SourceCollectionSourceFilter>>;
  sourceCollectionResultPageByStage: Record<SourceCollectionStageModuleId, number>;
  setSourceCollectionResultPageByStage: Dispatch<SetStateAction<Record<SourceCollectionStageModuleId, number>>>;
  selectedSourceCollectionStageId: SourceCollectionStageModuleId;
  setSelectedSourceCollectionStageId: Dispatch<SetStateAction<SourceCollectionStageModuleId>>;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: Dispatch<SetStateAction<string>>;
  sourceCollectionFocusedPanelId: string;
  setSourceCollectionFocusedPanelId: Dispatch<SetStateAction<string>>;
  activeSourceCollectionResearchProjectId: string;
  sourceCollectionNeedsCandidateList: boolean;
  experimentPlanningStatusQuery: TeamResearchSecondaryQueries["experimentPlanningStatusQuery"];
  researchLoopTemplatesQuery: TeamResearchSecondaryQueries["researchLoopTemplatesQuery"];
  researchLoopStatusQuery: TeamResearchSecondaryQueries["researchLoopStatusQuery"];
  aiSearchRunsQuery: TeamsSecondaryDataQueries["aiSearchRunsQuery"];
  aiSearchRunTopic: string;
  resetResearchProjectSourceCollectionMutation: TeamsMutationBundle["resetResearchProjectSourceCollectionMutation"];
  startResearchStageRoundMutation: TeamsMutationBundle["startResearchStageRoundMutation"];
  createExperimentPlanMutation: TeamsMutationBundle["createExperimentPlanMutation"];
  materializeEngineeringProxyHypothesisMutation: TeamsMutationBundle["materializeEngineeringProxyHypothesisMutation"];
  completeScientificHypothesisFromDesignMutation: TeamsMutationBundle["completeScientificHypothesisFromDesignMutation"];
  reviewExperimentHypothesisMutation: TeamsMutationBundle["reviewExperimentHypothesisMutation"];
  createExperimentHypothesisRevisionMutation: TeamsMutationBundle["createExperimentHypothesisRevisionMutation"];
  freezeExperimentDesignMutation: TeamsMutationBundle["freezeExperimentDesignMutation"];
  resumeExperimentHypothesisMutation: TeamsMutationBundle["resumeExperimentHypothesisMutation"];
  registerExperimentBaselineArtifactMutation: TeamsMutationBundle["registerExperimentBaselineArtifactMutation"];
  runExperimentSmokeMutation: TeamsMutationBundle["runExperimentSmokeMutation"];
  registerExperimentSmokeResultMutation: TeamsMutationBundle["registerExperimentSmokeResultMutation"];
  registerExperimentFullRunResultMutation: TeamsMutationBundle["registerExperimentFullRunResultMutation"];
  requestExperimentKnowledgeIngestionMutation: TeamsMutationBundle["requestExperimentKnowledgeIngestionMutation"];
  createResearchLoopMutation: TeamsMutationBundle["createResearchLoopMutation"];
  recordResearchLoopEvidenceMutation: TeamsMutationBundle["recordResearchLoopEvidenceMutation"];
  recordResearchLoopDecisionMutation: TeamsMutationBundle["recordResearchLoopDecisionMutation"];
  startSourceCollectionRunMutation: TeamsMutationBundle["startSourceCollectionRunMutation"];
  startSourceCollectionStageSessionTaskMutation: TeamsMutationBundle["startSourceCollectionStageSessionTaskMutation"];
  recordSourceCollectionOutputMutation: TeamsMutationBundle["recordSourceCollectionOutputMutation"];
  executeSourceCollectionSearchMutation: TeamsMutationBundle["executeSourceCollectionSearchMutation"];
  extractSourceCollectionCandidatesMutation: TeamsMutationBundle["extractSourceCollectionCandidatesMutation"];
  openSourceCollectionStorageMutation: TeamsMutationBundle["openSourceCollectionStorageMutation"];
  startAiSearchRunMutation: TeamsMutationBundle["startAiSearchRunMutation"];
  buildCandidateGraphMutation: TeamsMutationBundle["buildCandidateGraphMutation"];
  runKnowledgeIngestionPrecheckMutation: TeamsMutationBundle["runKnowledgeIngestionPrecheckMutation"];
  runKnowledgeCollectionCompletionMutation: TeamsMutationBundle["runKnowledgeCollectionCompletionMutation"];
  planPaperNoteChunksMutation: TeamsMutationBundle["planPaperNoteChunksMutation"];
  assessSourceQualityMutation: TeamsMutationBundle["assessSourceQualityMutation"];
  assessSourceQualityBatchMutation: TeamsMutationBundle["assessSourceQualityBatchMutation"];
  queryClient: QueryClient;
  requestedSourceCollectionStage: SourceCollectionStageModuleId | null;
  setSourceCollectionStageSyncUntilMs: Dispatch<SetStateAction<number>>;
  setSourceCollectionPendingStageTaskIds: Dispatch<SetStateAction<Partial<Record<SourceCollectionStageModuleId, string[]>>>>;
  searchParams: URLSearchParams;
  setSearchParams: SetURLSearchParams;
  navigate: NavigateFunction;
  scrollSourceCollectionPanelIntoViewRef: MutableRefObject<(panelId: string) => void>;
  sourceCollectionControlPanelRef: MutableRefObject<HTMLElement | null>;
  sourceCollectionRelationMapperAgentId: string;
  sourceCollectionExtractorAgentId: string;
  sourceCollectionOwnerAgentId: string;
  sourceCollectionIngestorAgentId: string;
  sourceCollectionStandalone: boolean;
  sourceCollectionStageWritebackSyncActive: boolean;
  sourceCollectionPendingStageTaskIds: Partial<Record<SourceCollectionStageModuleId, string[]>>;
  selectResearchWorkspaceView: (view: ResearchWorkspaceView) => void;
  launchResearchStage: (stageType: ResearchStageType, mode?: "continue_or_start" | "new_round") => void | Promise<void>;
  /** CSS module map for SC step badge classes (route styles). */
  styles: Record<string, string>;
};
