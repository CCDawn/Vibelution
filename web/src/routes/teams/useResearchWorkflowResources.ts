import { useQuery } from "@tanstack/react-query";

import { resolvePollingInterval } from "../../app/pollingPolicy";
import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  TeamWorkflowCandidateListPayload,
  TeamWorkflowCoordinationStatus,
  TeamWorkflowKnowledgeIngestionStatus,
  TeamWorkflowOrchestration,
} from "../../api/types";
import {
  sourceCollectionStageCardsFromStatus,
  sourceCollectionStageWritebackObservedTaskIds,
  type ResearchStageRoundStatusPayload,
  type SourceCollectionStageCardsStatus,
} from "./source-collection/stageProjection";

export const TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT = 80;
const TEAM_WORKFLOW_CANDIDATE_GRAPH_LIMIT = 20;

export const researchStageRoundStatusQueryKey = (id: string) => [
  "teams",
  id,
  "workflow-orchestration",
  "stage-rounds",
  "status",
] as const;

export const officialModelEvidenceStatusQueryKey = (id: string) => [
  "teams",
  id,
  "workflow-orchestration",
  "official-model-evidence",
  "status",
] as const;

export const paperNoteChunkStatusQueryKey = (id: string) => [
  "teams",
  id,
  "workflow-orchestration",
  "paper-note-chunks",
  "status",
] as const;

export const sourceQualityStatusQueryKey = (id: string) => [
  "teams",
  id,
  "workflow-orchestration",
  "source-quality",
  "status",
] as const;

export type TeamWorkflowOfficialModelEvidenceCoverage = {
  taskType: string;
  workflowNode: string;
  label: string;
  status: "covered" | "missing" | string;
  evidenceCount: number;
  providers: Record<string, number>;
  latestEvidenceId: string;
};

export type TeamWorkflowOfficialModelEvidenceStatus = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  workflowKind: string;
  status: "empty" | "needs_evidence" | "ready" | string;
  summary: {
    evidenceCount: number;
    storedEvidenceCount: number;
    candidateOutputEvidenceCount: number;
    requiredNodeCount: number;
    coveredNodeCount: number;
    missingNodeCount: number;
    qwenEvidenceCount: number;
    bailianEvidenceCount: number;
    localEvidenceCount: number;
    linkedCandidateCount: number;
    linkedStageRoundCount: number;
    actionItemCount: number;
  };
  coverage: TeamWorkflowOfficialModelEvidenceCoverage[];
  providerCounts: Record<string, number>;
  evidenceKindCounts: Record<string, number>;
  recentEvidence: Array<{
    evidenceId: string;
    taskType: string;
    workflowNode: string;
    candidateId: string;
    modelProvider: string;
    modelId: string;
    evidenceKind: string;
    status: string;
    createdAt: string;
  }>;
  actionItems: Array<{
    code: string;
    severity: string;
    message: string;
    nextAction: string;
    workflowNode: string;
    taskType: string;
  }>;
  officialBoundary: {
    candidateOnly: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    requiresStewardApproval: boolean;
    boundary: string;
  };
  storage: {
    workflowPath: string;
    candidateStorePath: string;
    evidenceStorePath: string;
  };
  updatedAt: string;
};

export type TeamWorkflowPaperNoteChunkStatus = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  workflowKind: string;
  status: "empty" | "needs_plan" | "in_progress" | "ready" | string;
  summary: {
    sourceCandidateCount: number;
    readySourceCandidateCount: number;
    plannedSourceCandidateCount: number;
    missingPlanSourceCandidateCount: number;
    planCount: number;
    chunkCount: number;
    draftedChunkCount: number;
    needsRevisionChunkCount: number;
    openChunkCount: number;
    actionItemCount: number;
  };
  plans: Array<{
    planId: string;
    status: string;
    sourceCandidateId: string;
    sourceTitle: string;
    chunkCount: number;
    draftedChunkCount: number;
    needsRevisionChunkCount: number;
    openChunkCount: number;
    pageScope: string;
    chunks: Array<{
      chunkId: string;
      chunkIndex: number;
      status: string;
      pageScope: string;
      excerptChars: number;
      paperNoteCandidateId: string;
      taskId: string;
    }>;
    createdAt: string;
    updatedAt: string;
  }>;
  missingPlanSources: Array<{
    candidateId: string;
    title: string;
    pageScope: string;
  }>;
  actionItems: Array<{
    code: string;
    severity: string;
    message: string;
    nextAction: string;
    candidateId: string;
  }>;
  officialBoundary: {
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    candidateOnly: boolean;
  };
  storage: {
    candidateStorePath: string;
  };
  updatedAt: string;
};

export type TeamWorkflowSourceQualityStatus = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  workflowKind: string;
  status: "empty" | "needs_screening" | "in_progress" | "ready" | "blocked" | string;
  summary: {
    sourceCandidateCount: number;
    assessedSourceCandidateCount: number;
    approvedSourceCandidateCount: number;
    needsRevisionSourceCandidateCount: number;
    rejectedSourceCandidateCount: number;
    unassessedSourceCandidateCount: number;
    extractionReadySourceCandidateCount: number;
    actionItemCount: number;
  };
  candidates: Array<{
    candidateId: string;
    title: string;
    sourceKind: string;
    currentState: string;
    qualityStatus: string;
    bucket: string;
    decision: string;
    overallScore: number;
    scores: {
      relevance: number;
      reliability: number;
      accessibility: number;
      extractionReadiness: number;
    };
    hasReadyExtraction: boolean;
    requiredFixes: string[];
    riskFlags: string[];
    updatedAt: string;
    assessedAt: string;
  }>;
  actionItems: Array<{
    code: string;
    severity: string;
    message: string;
    nextAction: string;
    candidateId: string;
  }>;
  screeningContract: {
    agentRole: string;
    targetCandidateType: string;
    decisions: string[];
    writesCandidateStore: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
  };
  officialBoundary: {
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    candidateOnly: boolean;
  };
  storage: {
    candidateStorePath: string;
  };
  updatedAt: string;
};

export type ResearchWorkflowResourceDemand = {
  workflow: boolean;
  stageRound: boolean;
  candidates: boolean;
  candidateGraph: boolean;
  coordination: boolean;
  knowledgeIngestion: boolean;
  modelEvidence: boolean;
  sourceQuality: boolean;
  paperNoteChunks: boolean;
};

export type ResearchWorkflowResourcesInput = {
  teamId: string;
  demand: ResearchWorkflowResourceDemand;
  pageVisible: boolean;
  stageWritebackSync: {
    active: boolean;
    pendingTaskIds: readonly string[];
  };
};

export function sourceCollectionStageWritebackRefetchInterval(
  pageVisible: boolean,
  status: SourceCollectionStageCardsStatus | null | undefined,
  forceSync = false,
  pendingTaskIds: readonly string[] = [],
) {
  const cards = sourceCollectionStageCardsFromStatus(status);
  const observedTaskIds = sourceCollectionStageWritebackObservedTaskIds(cards);
  const hasUnobservedPendingTask = pendingTaskIds.some((taskId) => taskId && !observedTaskIds.has(taskId));
  const hasRunningAgentTask = cards.some((card) => {
    const latestTaskStatus = String(card.latestTask?.status || "").toLowerCase();
    const cardStatus = String(card.status || "").toLowerCase();
    return cardStatus === "agent_running" || latestTaskStatus === "queued" || latestTaskStatus === "running";
  });
  const hasCompletedTaskAwaitingArtifact = cards.some((card) => {
    const latestTaskStatus = String(card.latestTask?.status || "").toLowerCase();
    return Boolean(card.latestTask?.taskId)
      && latestTaskStatus === "completed"
      && String(card.status || "").toLowerCase() === "agent_done_artifact_pending";
  });
  return resolvePollingInterval(
    pageVisible,
    hasRunningAgentTask || forceSync || hasUnobservedPendingTask ? 2000 : hasCompletedTaskAwaitingArtifact ? 5000 : false,
  );
}

export function useResearchWorkflowResources({
  teamId,
  demand,
  pageVisible,
  stageWritebackSync,
}: ResearchWorkflowResourcesInput) {
  const workflow = useQuery({
    queryKey: queryKeys.teamWorkflow(teamId || "none"),
    queryFn: ({ signal }) => fetchJson<TeamWorkflowOrchestration>(
      `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration`,
      { signal },
    ),
    enabled: Boolean(teamId && demand.workflow),
  });
  const stageRound = useQuery({
    queryKey: researchStageRoundStatusQueryKey(teamId || "none"),
    queryFn: ({ signal }) => fetchJson<ResearchStageRoundStatusPayload>(
      `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/stage-rounds/status`,
      { signal },
    ),
    enabled: Boolean(teamId && demand.stageRound),
    refetchInterval: (query) => sourceCollectionStageWritebackRefetchInterval(
      pageVisible,
      query.state.data as ResearchStageRoundStatusPayload | null | undefined,
      stageWritebackSync.active,
      stageWritebackSync.pendingTaskIds,
    ),
  });
  const candidates = useQuery({
    queryKey: queryKeys.teamWorkflowCandidates(teamId || "none", TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT),
    queryFn: ({ signal }) => fetchJson<TeamWorkflowCandidateListPayload>(
      `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/candidates?limit=${TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT}&includeValidation=false&includeStore=false`,
      { signal },
    ),
    enabled: Boolean(teamId && demand.candidates),
    refetchInterval: () => sourceCollectionStageWritebackRefetchInterval(
      pageVisible,
      stageRound.data,
      stageWritebackSync.active,
      stageWritebackSync.pendingTaskIds,
    ),
  });
  const candidateGraph = useQuery({
    queryKey: queryKeys.teamWorkflowCandidateGraph(teamId || "none"),
    queryFn: ({ signal }) => fetchJson<TeamWorkflowCandidateListPayload>(
      `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/candidates?candidateType=candidate_graph&limit=${TEAM_WORKFLOW_CANDIDATE_GRAPH_LIMIT}&includeStore=false`,
      { signal },
    ),
    enabled: Boolean(teamId && demand.candidateGraph),
  });
  const coordination = useQuery({
    queryKey: queryKeys.teamWorkflowCoordinationStatus(teamId || "none"),
    queryFn: ({ signal }) => fetchJson<TeamWorkflowCoordinationStatus>(
      `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/coordination/status`,
      { signal },
    ),
    enabled: Boolean(teamId && demand.coordination),
  });
  const knowledgeIngestion = useQuery({
    queryKey: queryKeys.teamWorkflowKnowledgeIngestionStatus(teamId || "none"),
    queryFn: ({ signal }) => fetchJson<TeamWorkflowKnowledgeIngestionStatus>(
      `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/knowledge-ingestion/status`,
      { signal },
    ),
    enabled: Boolean(teamId && demand.knowledgeIngestion),
    refetchInterval: (query) => {
      const data = query.state.data as TeamWorkflowKnowledgeIngestionStatus | undefined;
      return resolvePollingInterval(pageVisible, data?.activeWorkRun ? 2000 : false);
    },
  });
  const modelEvidence = useQuery({
    queryKey: officialModelEvidenceStatusQueryKey(teamId || "none"),
    queryFn: ({ signal }) => fetchJson<TeamWorkflowOfficialModelEvidenceStatus>(
      `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/official-model-evidence/status`,
      { signal },
    ),
    enabled: Boolean(teamId && demand.modelEvidence),
  });
  const sourceQuality = useQuery({
    queryKey: sourceQualityStatusQueryKey(teamId || "none"),
    queryFn: ({ signal }) => fetchJson<TeamWorkflowSourceQualityStatus>(
      `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/source-quality/status`,
      { signal },
    ),
    enabled: Boolean(teamId && demand.sourceQuality),
    refetchInterval: () => sourceCollectionStageWritebackRefetchInterval(
      pageVisible,
      stageRound.data,
      stageWritebackSync.active,
      stageWritebackSync.pendingTaskIds,
    ),
  });
  const paperNoteChunks = useQuery({
    queryKey: paperNoteChunkStatusQueryKey(teamId || "none"),
    queryFn: ({ signal }) => fetchJson<TeamWorkflowPaperNoteChunkStatus>(
      `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/paper-note-chunks/status`,
      { signal },
    ),
    enabled: Boolean(teamId && demand.paperNoteChunks),
  });

  return {
    workflow,
    stageRound,
    candidates,
    candidateGraph,
    coordination,
    knowledgeIngestion,
    modelEvidence,
    sourceQuality,
    paperNoteChunks,
  };
}
