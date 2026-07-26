/**
 * Source-collection write mutations for Teams (search/extract/quality/graph/ingestion).
 * EventSource-free; Route remains draft/view/session-task orchestration boundary.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  DataProcessingCollectionAssignmentListPayload,
  DataProcessingCollectionOutputPayload,
  TeamWorkflowCandidateGraphBuildPayload,
  TeamWorkflowDataRecordSourceCandidateImportPayload,
  TeamWorkflowKnowledgeCollectionIngestionPayload,
  TeamWorkflowSourceCollectionExtractionPayload,
} from "../../api/types";
import { SOURCE_COLLECTION_RUN_PREVIEW_LIMIT } from "./source-collection/presentationModel";
import type { SourceCollectionStorageOpenTarget } from "./source-collection/presentationModel";
import {
  sourceCollectionRunRecordsQueryKey,
  sourceCollectionSummaryQueryPrefix,
} from "./teamWorkflowQueryKeys";
import {
  paperNoteChunkStatusQueryKey,
  researchStageRoundStatusQueryKey,
  sourceQualityStatusQueryKey,
  TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT,
} from "./useResearchWorkflowResources";
import type {
  SourceCollectionOutputDraft,
  TeamWorkflowKnowledgeIngestionPrecheckPayload,
  TeamWorkflowPaperNoteChunkPlanPayload,
  TeamWorkflowSourceCollectionSearchExecutionPayload,
  TeamWorkflowSourceCollectionStorageOpenPayload,
  TeamWorkflowSourceQualityAssessmentPayload,
  TeamWorkflowSourceQualityBatchAssessmentPayload,
} from "./sourceCollectionMutationModel";

export type UseTeamSourceCollectionMutationsOptions = {
  sourceCollectionOwnerAgentId: string;
  sourceCollectionExtractorAgentId: string;
  sourceCollectionRelationMapperAgentId: string;
  sourceCollectionDraftTopic: string;
  sourceCollectionDraftMaxResultsPerQuery: number;
  setSelectedSourceCollectionRunId: Dispatch<SetStateAction<string>>;
  setSourceCollectionOutputDraft: Dispatch<SetStateAction<SourceCollectionOutputDraft>>;
  scrollSourceCollectionPanelIntoView: (panelId: string) => void;
};

export function useTeamSourceCollectionMutations(options: UseTeamSourceCollectionMutationsOptions) {
  const queryClient = useQueryClient();

  const recordSourceCollectionOutputMutation = useMutation({
    mutationFn: async (payload: { teamId: string; runId: string; draft: SourceCollectionOutputDraft }) => {
      const output = await fetchJson<DataProcessingCollectionOutputPayload>(
        `/api/data-processing/runs/${encodeURIComponent(payload.runId)}/collection-assignments/${encodeURIComponent(payload.draft.assignmentId)}/outputs`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            status: "completed",
            notes: payload.draft.notes.trim(),
            records: [
              {
                sourceType: payload.draft.sourceType,
                title: payload.draft.title.trim(),
                sourceRef: payload.draft.sourceRef.trim(),
                rawLocation: payload.draft.rawLocation.trim(),
                summary: payload.draft.summary.trim(),
                status: "collected",
                metadata: {
                  allowedForAnalysis: true,
                  enteredFrom: "teams_research_source_collection_panel",
                },
                qualitySignals: {
                  manualEntry: true,
                  needsIntakeReview: true,
                },
              },
            ],
          }),
        },
      );
      const imported = await Promise.all(
        output.createdRecords.map((record) =>
          fetchJson<TeamWorkflowDataRecordSourceCandidateImportPayload>(
            `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/data-processing/runs/${encodeURIComponent(payload.runId)}/records/${encodeURIComponent(record.recordId)}/source-candidate`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                createdByAgent: options.sourceCollectionOwnerAgentId,
                tags: ["source_collection", "manual_writeback"],
                metadata: {
                  sourceCollectionPanel: true,
                  assignmentId: payload.draft.assignmentId,
                },
              }),
            },
          ),
        ),
      );
      return { output, imported };
    },
    onSuccess: (payload, variables) => {
      options.setSourceCollectionOutputDraft((current) => ({
        ...current,
        title: "",
        sourceRef: "",
        rawLocation: "",
        summary: "",
        notes: "",
      }));
      if (payload.imported[0]?.workflow) {
        queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.imported[0].workflow);
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(variables.runId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(variables.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(variables.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
    },
  });

  const executeSourceCollectionSearchMutation = useMutation({
    mutationFn: (payload: { teamId: string; runId: string; assignmentId?: string; maxQueries?: number; maxResultsPerQuery?: number }) =>
      fetchJson<TeamWorkflowSourceCollectionSearchExecutionPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs/${encodeURIComponent(payload.runId)}/search/execute`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assignmentIds: payload.assignmentId ? [payload.assignmentId] : [],
            maxQueries: payload.maxQueries ?? 4,
            maxResultsPerQuery: payload.maxResultsPerQuery ?? 2,
            provider: "crossref_rest_api",
            backgroundExecution: true,
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      options.setSelectedSourceCollectionRunId(payload.runId);
      queryClient.setQueryData(queryKeys.dataProcessingRunStatus(payload.runId), {
        ...payload.runStatus,
        summary: {
          ...payload.runStatus.summary,
          ...(payload.sourceCollectionSummary ?? {}),
        },
      });
      queryClient.setQueryData(queryKeys.dataProcessingCollectionAssignments(payload.runId), {
        schemaVersion: payload.schemaVersion,
        runId: payload.runId,
        assignments: payload.assignments,
        summary: {
          assignmentCount: payload.assignments.length,
          assignmentStatusCounts: payload.assignments.reduce<Record<string, number>>((counts, assignment) => {
            counts[assignment.status] = (counts[assignment.status] ?? 0) + 1;
            return counts;
          }, {}),
        },
      } satisfies DataProcessingCollectionAssignmentListPayload);
      if (payload.imported[0]?.workflow) {
        queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.imported[0].workflow);
      }
      void queryClient.invalidateQueries({ queryKey: researchStageRoundStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(payload.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const extractSourceCollectionCandidatesMutation = useMutation({
    mutationFn: (payload: { teamId: string; runId: string; extractionAgentId: string; maxRecords?: number; force?: boolean; notes?: string }) =>
      fetchJson<TeamWorkflowSourceCollectionExtractionPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/knowledge-collection/extract`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            runId: payload.runId,
            extractionAgentId: payload.extractionAgentId,
            maxRecords: payload.maxRecords ?? 100,
            force: payload.force ?? false,
            notes: payload.notes ?? "",
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      options.setSelectedSourceCollectionRunId(payload.runId);
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      queryClient.setQueryData(queryKeys.dataProcessingRunStatus(payload.runId), {
        ...payload.runStatus,
        summary: {
          ...payload.runStatus.summary,
          ...(payload.sourceCollectionSummary ?? {}),
        },
      });
      queryClient.setQueryData(queryKeys.dataProcessingCollectionAssignments(payload.runId), {
        schemaVersion: payload.schemaVersion,
        runId: payload.runId,
        assignments: payload.assignments,
        summary: {
          assignmentCount: payload.assignments.length,
          assignmentStatusCounts: payload.assignments.reduce<Record<string, number>>((counts, assignment) => {
            counts[assignment.status] = (counts[assignment.status] ?? 0) + 1;
            return counts;
          }, {}),
        },
      } satisfies DataProcessingCollectionAssignmentListPayload);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(variables.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(payload.runId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const openSourceCollectionStorageMutation = useMutation({
    mutationFn: (payload: { teamId: string; runId: string; target: SourceCollectionStorageOpenTarget }) =>
      fetchJson<TeamWorkflowSourceCollectionStorageOpenPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-collection-runs/${encodeURIComponent(payload.runId)}/storage/open`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ target: payload.target }),
        },
      ),
  });

  const assessSourceQualityMutation = useMutation({
    mutationFn: (payload: { teamId: string; candidateId: string; decision: "approved" | "needs_revision" }) =>
      fetchJson<TeamWorkflowSourceQualityAssessmentPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/candidates/${encodeURIComponent(payload.candidateId)}/source-quality/assess`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assessedByAgent: options.sourceCollectionExtractorAgentId,
            decision: payload.decision,
            notes: payload.decision === "approved"
              ? "Source Extractor Agent approved this source for downstream paper_note extraction."
              : "Source Extractor Agent returned this source for repair before downstream extraction.",
            requiredFixes: payload.decision === "needs_revision"
              ? ["补充来源路径/权限/sha256/摘要/页码锚点或相关性说明后重新筛选。"]
              : [],
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      queryClient.setQueryData(sourceQualityStatusQueryKey(variables.teamId), payload.status);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const assessSourceQualityBatchMutation = useMutation({
    mutationFn: (payload: { teamId: string; assessedByAgent: string; maxCandidates?: number; force?: boolean; notes?: string }) =>
      fetchJson<TeamWorkflowSourceQualityBatchAssessmentPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/source-quality/assess-batch`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            assessedByAgent: payload.assessedByAgent,
            maxCandidates: payload.maxCandidates ?? 100,
            force: payload.force ?? false,
            notes: payload.notes ?? "",
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      queryClient.setQueryData(sourceQualityStatusQueryKey(variables.teamId), payload.sourceQualityStatus);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
      options.scrollSourceCollectionPanelIntoView("source-collection-screening-panel");
    },
  });

  const planPaperNoteChunksMutation = useMutation({
    mutationFn: (payload: { teamId: string; candidateId: string }) =>
      fetchJson<TeamWorkflowPaperNoteChunkPlanPayload>(
        `/api/teams/${encodeURIComponent(payload.teamId)}/workflow-orchestration/candidates/${encodeURIComponent(payload.candidateId)}/paper-note-chunks/plan`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            createdByAgent: options.sourceCollectionOwnerAgentId,
            maxPagesPerChunk: 4,
            maxCharsPerChunk: 12000,
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: paperNoteChunkStatusQueryKey(variables.teamId) });
    },
  });

  const buildCandidateGraphMutation = useMutation({
    mutationFn: (variables: {
      teamId: string;
      title?: string;
      createdByAgent?: string;
      sourceQualityAgentId?: string;
      curationMode?: string;
      maxCandidates?: number;
      forceReview?: boolean;
      forceRebuild?: boolean;
    }) =>
      fetchJson<TeamWorkflowCandidateGraphBuildPayload>(`/api/teams/${encodeURIComponent(variables.teamId)}/workflow-orchestration/candidate-graph`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: variables.title || "Agent curated candidate graph",
          createdByAgent: variables.createdByAgent || options.sourceCollectionRelationMapperAgentId,
          sourceQualityAgentId: variables.sourceQualityAgentId || options.sourceCollectionExtractorAgentId,
          curationMode: variables.curationMode || "",
          maxCandidates: variables.maxCandidates || 80,
          forceReview: variables.forceReview ?? false,
          forceRebuild: variables.forceRebuild ?? false,
        }),
      }),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidateGraph(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
    },
  });

  const runKnowledgeIngestionPrecheckMutation = useMutation({
    mutationFn: (variables: { teamId: string; stewardAgentId: string; targetDomain?: string; maxCandidates?: number }) =>
      fetchJson<TeamWorkflowKnowledgeIngestionPrecheckPayload>(
        `/api/teams/${encodeURIComponent(variables.teamId)}/workflow-orchestration/knowledge-ingestion/precheck`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            stewardAgentId: variables.stewardAgentId,
            targetDomain: variables.targetDomain || options.sourceCollectionDraftTopic || "神经机制启发神经网络算法",
            maxCandidates: variables.maxCandidates || 32,
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      queryClient.setQueryData(queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId), payload.status);
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
    },
  });

  const runKnowledgeCollectionCompletionMutation = useMutation({
    mutationFn: (variables: {
      teamId: string;
      runId?: string;
      extractionAgentId?: string;
      sourceQualityAgentId: string;
      candidateGraphAgentId: string;
      stewardAgentId: string;
      knowledgeBaseId?: string;
      targetDomain?: string;
      maxCandidates?: number;
      maxSearchBatches?: number;
      maxQueriesPerBatch?: number;
      maxResultsPerQuery?: number;
      maxRecords?: number;
      forceReview?: boolean;
      forceRebuild?: boolean;
    }) =>
      fetchJson<TeamWorkflowKnowledgeCollectionIngestionPayload>(
        `/api/teams/${encodeURIComponent(variables.teamId)}/workflow-orchestration/knowledge-collection/complete`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            runId: variables.runId || "",
            extractionAgentId: variables.extractionAgentId || "",
            sourceQualityAgentId: variables.sourceQualityAgentId,
            candidateGraphAgentId: variables.candidateGraphAgentId,
            stewardAgentId: variables.stewardAgentId,
            knowledgeBaseId: variables.knowledgeBaseId || "",
            targetDomain: variables.targetDomain || options.sourceCollectionDraftTopic || "神经机制启发神经网络算法",
            maxCandidates: variables.maxCandidates || 80,
            maxSearchBatches: variables.maxSearchBatches ?? 20,
            maxQueriesPerBatch: variables.maxQueriesPerBatch ?? 4,
            maxResultsPerQuery: variables.maxResultsPerQuery || Math.max(1, Math.min(5, options.sourceCollectionDraftMaxResultsPerQuery || 3)),
            maxRecords: variables.maxRecords ?? 500,
            forceReview: variables.forceReview ?? false,
            forceRebuild: variables.forceRebuild ?? false,
            autoCreateKnowledgeBase: true,
            // 一键入库走同步闭环：提交→来源审核→知识提案→审批→正式 KnowledgeItem。
            // 职责分离：steward 提案，由后端解析的 coordinator/lead 审批，不再依赖唤醒 agent 的异步交接。
            autoSubmit: true,
            autoReviewSource: true,
            autoApprove: true,
            notifyStewardAgent: false,
            wakeStewardAgent: false,
            // 首次入库需现场生成 steward pack（分钟级）；后台执行让点击立即返回，状态由 activeWorkRun 轮询。
            backgroundExecution: true,
            requesterAgentId: options.sourceCollectionOwnerAgentId,
          }),
        },
      ),
    onSuccess: (payload, variables) => {
      // 后台执行时响应是 accepted（无 workflow/statusSnapshot）：只失效查询，让 activeWorkRun 轮询接管。
      if (payload.workflow) {
        queryClient.setQueryData(queryKeys.teamWorkflow(variables.teamId), payload.workflow);
      }
      if (payload.statusSnapshot) {
        queryClient.setQueryData(queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId), payload.statusSnapshot);
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidates(variables.teamId, TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCandidateGraph(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryPrefix(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: sourceQualityStatusQueryKey(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(variables.teamId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowCoordinationStatus(variables.teamId) });
    },
  });



  return {
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
  };
}
