/**
 * Workflow start + SC stage-session mutations for Teams.
 * EventSource-free; Route remains draft/view/navigation orchestration boundary.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  AiSearchRun,
  Team,
  TeamWorkflowSourceCollectionAgentSessionContextPayload,
  TeamWorkflowSourceCollectionRunStartPayload,
  TeamWorkflowSourceCollectionStageSessionTaskPayload,
} from "../../api/types";
import { AI_SEARCH_RUN_PREVIEW_LIMIT } from "./aiSearchPresentation";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import { experimentPlanningStatusQueryKey } from "./experimentLoopModel";
import type { ResearchWorkspaceView } from "./researchWorkspaceModel";
import { researchSourceCollectionRoute } from "./researchWorkspaceModel";
import {
  SOURCE_COLLECTION_PROMPT_CACHE_POLICY,
  SOURCE_COLLECTION_RUN_PREVIEW_LIMIT,
  SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS,
  compactSourceCollectionQuerySeeds,
  sourceCollectionLocalScanScopeForDraft,
  sourceCollectionModeForTeam,
  splitDraftList,
  type SourceCollectionDraft,
} from "./source-collection/presentationModel";
import type {
  ResearchStageType,
  SourceCollectionStageModuleId,
} from "./source-collection/stageProjection";
import type { SourceCollectionOutputDraft } from "./sourceCollectionMutationModel";
import {
  SOURCE_COLLECTION_DEFAULT_ROLES,
  sourceCollectionAgentRolesForTeam,
  sourceCollectionWorkflowKindForTeam,
  sourceCollectionWorkflowPurposeForTeam,
} from "./teamKindModel";
import {
  sourceCollectionRunRecordsQueryKey,
  sourceCollectionSummaryQueryPrefix,
} from "./teamWorkflowQueryKeys";
import {
  paperNoteChunkStatusQueryKey,
  researchStageRoundStatusQueryKey,
  sourceQualityStatusQueryKey,
} from "./useResearchWorkflowResources";
import type { ResearchStageRoundStartPayload } from "./workflowStartMutationModel";

export type { ResearchStageRoundStartPayload } from "./workflowStartMutationModel";

type TeamShellChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;

export type UseTeamWorkflowStartMutationsOptions = {
  selectedTeam: Team | null | undefined;
  knowledgeExpansionWorkflowTeamSelected: boolean;
  sourceCollectionOwnerAgentId: string;
  sourceCollectionAgentIds: Record<string, string>;
  sourceCollectionStandalone: boolean;
  chatWorkspaceCache: TeamShellChatWorkspaceCache;
  setSelectedSourceCollectionRunId: Dispatch<SetStateAction<string>>;
  setSourceCollectionStageSyncUntilMs: Dispatch<SetStateAction<number>>;
  setSourceCollectionPendingStageTaskIds: Dispatch<SetStateAction<Partial<Record<SourceCollectionStageModuleId, string[]>>>>;
  setSourceCollectionOutputDraft: Dispatch<SetStateAction<SourceCollectionOutputDraft>>;
  setResearchWorkspaceView: Dispatch<SetStateAction<ResearchWorkspaceView>>;
  navigateToSourceCollection: (teamId: string) => void;
};

export function useTeamWorkflowStartMutations(options: UseTeamWorkflowStartMutationsOptions) {
  const queryClient = useQueryClient();
  const { chatWorkspaceCache } = options;

  const seedSourceCollectionAgentSessionContextMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      runId: string;
      stageId: SourceCollectionStageModuleId;
      agentId: string;
      agentRole: string;
    }) =>
      fetchJson<TeamWorkflowSourceCollectionAgentSessionContextPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs/${encodeURIComponent(payload.runId)}/agent-session-context`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stageId: payload.stageId,
            agentId: payload.agentId,
            agentRole: payload.agentRole,
          }),
        },
      ),
  });

  const startSourceCollectionStageSessionTaskMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      runId: string;
      stageId: SourceCollectionStageModuleId;
      agentId: string;
      agentRole: string;
      returnTo: string;
      returnLabel: string;
      requestedByAgent: string;
      idempotencyKey: string;
    }) =>
      fetchJson<TeamWorkflowSourceCollectionStageSessionTaskPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs/${encodeURIComponent(payload.runId)}/stage-session-tasks`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stageId: payload.stageId,
            agentId: payload.agentId,
            agentRole: payload.agentRole,
            returnTo: payload.returnTo,
            returnLabel: payload.returnLabel,
            requestedByAgent: payload.requestedByAgent,
            idempotencyKey: payload.idempotencyKey,
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      options.setSelectedSourceCollectionRunId(payload.runId);
      options.setSourceCollectionStageSyncUntilMs(Date.now() + SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS);
      if (payload.taskId) {
        options.setSourceCollectionPendingStageTaskIds((current) => {
          const currentStageTaskIds = current[variables.stageId] ?? [];
          if (currentStageTaskIds.includes(payload.taskId)) {
            return current;
          }
          return {
            ...current,
            [variables.stageId]: [...currentStageTaskIds, payload.taskId],
          };
        });
      }
      void chatWorkspaceCache.afterDirectTurnAccepted(payload.sessionId);
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(payload.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(payload.runId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(payload.runId) });
    },
  });

  const startAiSearchRunMutation = useMutation({
    mutationFn: (payload: { teamId: string; topic: string }) =>
      fetchJson<AiSearchRun>(`/api/teams/${encodeURIComponent(payload.teamId)}/ai-search-runs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: payload.topic.trim() || "AI 最新动态",
          sourceLimit: 8,
          maxResultsPerQuery: 3,
          includeSignals: false,
        }),
      }),
    onSuccess: (_run, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamAiSearchRuns(variables.teamId, AI_SEARCH_RUN_PREVIEW_LIMIT) });
    },
  });

  const startSourceCollectionRunMutation = useMutation({
    mutationFn: (payload: { teamId: string; draft: SourceCollectionDraft }) => {
      const querySeeds = compactSourceCollectionQuerySeeds(payload.draft.topic, payload.draft.querySeeds);
      const workflowKind = sourceCollectionWorkflowKindForTeam(options.selectedTeam);
      const workflowPurpose = sourceCollectionWorkflowPurposeForTeam(options.selectedTeam);
      const collectionMode = sourceCollectionModeForTeam(options.selectedTeam, payload.draft);
      return fetchJson<TeamWorkflowSourceCollectionRunStartPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title:
              payload.draft.title.trim()
              || (options.knowledgeExpansionWorkflowTeamSelected
                ? "Knowledge expansion source intake"
                : "Challenge Cup source collection"),
            topic: payload.draft.topic.trim(),
            goal: payload.draft.goal.trim(),
            ownerAgentId: options.sourceCollectionOwnerAgentId,
            requestedByAgent: options.sourceCollectionOwnerAgentId,
            workflowPurpose,
            workflowKind,
            collectionMode,
            agentRoles: sourceCollectionAgentRolesForTeam(options.selectedTeam),
            agentIds: options.sourceCollectionAgentIds,
            inputRefs: splitDraftList(payload.draft.inputRefs, 24),
            querySeeds,
            searchLanguages: splitDraftList(payload.draft.searchLanguages, 8),
            sourceTypes: splitDraftList(payload.draft.sourceTypes, 12),
            maxResultsPerQuery: payload.draft.maxResultsPerQuery,
            localScanScope: sourceCollectionLocalScanScopeForDraft(collectionMode, payload.draft),
            promptCachePolicy: SOURCE_COLLECTION_PROMPT_CACHE_POLICY,
            scope: {
              domain: options.knowledgeExpansionWorkflowTeamSelected
                ? "team knowledge expansion"
                : "neuroscience-inspired algorithm discovery",
              workflowStage: "knowledge_collection",
              workflowKind,
              workflowPurpose,
              collectionMode,
              uiEntry: options.knowledgeExpansionWorkflowTeamSelected
                ? "teams_knowledge_expansion_source_collection_panel"
                : "teams_research_source_collection_panel",
            },
          }),
        },
      );
    },
    onSuccess: (payload, variables) => {
      options.setSelectedSourceCollectionRunId(payload.run.runId);
      const firstAssignmentId = payload.assignments[0]?.assignmentId ?? "";
      options.setSourceCollectionOutputDraft((current) => ({
        ...current,
        assignmentId: firstAssignmentId || current.assignmentId,
      }));
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT),
      });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(payload.run.runId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(payload.run.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(payload.run.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const startResearchStageRoundMutation = useMutation({
    mutationFn: (payload: {
      teamId: string;
      stageType: ResearchStageType;
      mode?: "continue_or_start" | "new_round";
      draft: SourceCollectionDraft;
    }) => {
      const querySeeds = compactSourceCollectionQuerySeeds(payload.draft.topic, payload.draft.querySeeds);
      return fetchJson<ResearchStageRoundStartPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/stage-rounds/start`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stageType: payload.stageType,
            mode: payload.mode || "continue_or_start",
            title: payload.draft.title.trim() || "",
            topic: payload.draft.topic.trim(),
            goal: payload.draft.goal.trim(),
            ownerAgentId: options.sourceCollectionOwnerAgentId,
            requestedByAgent: options.sourceCollectionOwnerAgentId,
            agentRoles: SOURCE_COLLECTION_DEFAULT_ROLES,
            agentIds: options.sourceCollectionAgentIds,
            inputRefs: splitDraftList(payload.draft.inputRefs, 24),
            querySeeds,
            searchLanguages: splitDraftList(payload.draft.searchLanguages, 8),
            sourceTypes: splitDraftList(payload.draft.sourceTypes, 12),
            maxResultsPerQuery: payload.draft.maxResultsPerQuery,
            promptCachePolicy: SOURCE_COLLECTION_PROMPT_CACHE_POLICY,
            scope: {
              domain: "neuroscience-inspired algorithm discovery",
              workflowStage: payload.stageType,
              uiEntry: "teams_research_stage_launcher",
            },
          }),
        },
      );
    },
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(researchStageRoundStatusQueryKey(variables.teamId), payload.status);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: experimentPlanningStatusQueryKey(variables.teamId) });
      const sourceRunId = payload.run?.runId || payload.stageRound.sourceRunIds?.[0] || "";
      const searchExecution = payload.sourceCollectionSearchExecution;
      if (sourceRunId) {
        options.setSelectedSourceCollectionRunId(sourceRunId);
        const firstAssignmentId = payload.assignments?.[0]?.assignmentId ?? "";
        if (firstAssignmentId) {
          options.setSourceCollectionOutputDraft((current) => ({
            ...current,
            assignmentId: firstAssignmentId,
          }));
        }
        if (searchExecution?.runStatus) {
          queryClient.setQueryData(queryKeys.dataProcessingRunStatus(sourceRunId), {
            ...searchExecution.runStatus,
            summary: {
              ...searchExecution.runStatus.summary,
              ...(searchExecution.sourceCollectionSummary ?? {}),
            },
          });
        } else if (payload.run) {
          queryClient.setQueryData(queryKeys.dataProcessingRunStatus(sourceRunId), {
            schemaVersion: 1,
            runId: payload.run.runId,
            profileId: payload.run.profileId,
            runStatus: payload.run.status,
            summary: payload.run.summary ?? {
              recordCount: 0,
              assignmentCount: payload.assignmentCount ?? payload.assignments?.length ?? 0,
              openAssignmentCount: payload.continuedSourceRunRef?.openAssignmentCount ?? 0,
              searchOpenAssignmentCount: payload.continuedSourceRunRef?.searchOpenAssignmentCount ?? 0,
              collectionOpenAssignmentCount: payload.continuedSourceRunRef?.collectionOpenAssignmentCount ?? 0,
              downstreamOpenAssignmentCount: payload.continuedSourceRunRef?.downstreamOpenAssignmentCount ?? 0,
              outputCount: 0,
              recordStatusCounts: {},
              sourceTypeCounts: {},
              assignmentStatusCounts: {},
            },
            nextActions: [],
            boundaries: {
              generic: true,
              writesFormalKnowledge: false,
              writesRag: false,
              writesKnowledgeGraph: false,
              requiresDownstreamPublisher: true,
            },
          });
        }
        const stageAssignments = searchExecution?.assignments ?? payload.assignments;
        if (stageAssignments) {
          queryClient.setQueryData(queryKeys.dataProcessingCollectionAssignments(sourceRunId), {
            schemaVersion: 1,
            runId: sourceRunId,
            assignments: stageAssignments,
            summary: {
              assignmentCount: stageAssignments.length,
              assignmentStatusCounts: stageAssignments.reduce<Record<string, number>>((counts, assignment) => {
                counts[assignment.status] = (counts[assignment.status] ?? 0) + 1;
                return counts;
              }, {}),
            },
          });
        }
        if (options.sourceCollectionStandalone) {
          options.setResearchWorkspaceView("knowledge_collection");
        } else {
          options.navigateToSourceCollection(variables.teamId);
        }
        void queryClient.invalidateQueries({
          queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT),
        });
        void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(sourceRunId) });
        void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(sourceRunId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(sourceRunId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      } else if (variables.stageType === "experiment") {
        options.setResearchWorkspaceView("experiment");
      } else if (variables.stageType === "iteration") {
        options.setResearchWorkspaceView("iteration");
      }
    },
  });

  return {
    seedSourceCollectionAgentSessionContextMutation,
    startSourceCollectionStageSessionTaskMutation,
    startAiSearchRunMutation,
    startSourceCollectionRunMutation,
    startResearchStageRoundMutation,
  };
}

// Keep route helper import surface stable for navigate wiring docs.
export { researchSourceCollectionRoute };
