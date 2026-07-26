/**
 * Source-collection mutation payload types shared by TeamsRoute and write hooks.
 * Promoted out of TeamsRoute to unlock EventSource-free mutation extraction.
 */
import type {
  DataProcessingCollectionOutputPayload,
  DataProcessingStatus,
  TeamWorkflowCandidate,
  TeamWorkflowKnowledgeIngestionStatus,
  TeamWorkflowOrchestration,
  TeamWorkflowSourceCollectionRunStartPayload,
  TeamWorkflowDataRecordSourceCandidateImportPayload,
} from "../../api/types";
import type { SourceCollectionStorageArtifacts, SourceCollectionStorageOpenTarget } from "./source-collection/presentationModel";
import type { TeamWorkflowSourceQualityStatus } from "./useResearchWorkflowResources";

export type TeamWorkflowKnowledgeIngestionPrecheckPayload = {
  candidate: TeamWorkflowCandidate;
  validation: { valid: boolean; issues: Array<Record<string, unknown>> };
  precheck: {
    status: string;
    generatedByAgent: string;
    selectedCandidateCount: number;
    filteredCandidateCount?: number;
    candidateIds?: string[];
    candidateGraphId?: string;
    officialBoundary: {
      writesOfficialKnowledge: boolean;
      writesOfficialRag: boolean;
      writesOfficialGraph: boolean;
      requiresReviewBeforeOfficialSync?: boolean;
    };
  };
  status: TeamWorkflowKnowledgeIngestionStatus;
  workflow: TeamWorkflowOrchestration;
};

export type SourceCollectionOutputDraft = {
  assignmentId: string;
  sourceType: string;
  title: string;
  sourceRef: string;
  rawLocation: string;
  summary: string;
  notes: string;
};

export type TeamWorkflowSourceCollectionStorageOpenPayload = {
  schemaVersion: number;
  teamId: string;
  runId: string;
  target: SourceCollectionStorageOpenTarget;
  path: string;
  openedPath: string;
  targetExists: boolean;
  storageArtifacts: SourceCollectionStorageArtifacts;
};

export type SourceCollectionSearchExecutionEvent = {
  eventId: string;
  eventType: string;
  status: string;
  title: string;
  summary: string;
  agentRole: string;
  agentId: string;
  assignmentId: string;
  queryId: string;
  query: string;
  sourceType: string;
  refs: string[];
  rawLocation: string;
  storageRefs: string[];
  createdAt: string;
};

export type TeamWorkflowSourceCollectionSearchExecutionPayload = {
  schemaVersion: number;
  teamId: string;
  runId: string;
  status: string;
  executionMode?: "background" | string;
  accepted?: boolean;
  provider: string;
  executedQueryCount: number;
  skippedQueryCount: number;
  failedQueryCount: number;
  resultCount: number;
  recordCount: number;
  createdUniqueRecordCount?: number;
  outputCount: number;
  importedCount: number;
  skippedDuplicateCount?: number;
  filteredExcludedCount?: number;
  duplicateSourceKeys?: string[];
  excludedSourceKeys?: string[];
  remainingQueryCount?: number;
  nextRunnableQueryIds?: string[];
  hasMore?: boolean;
  run: TeamWorkflowSourceCollectionRunStartPayload["run"];
  runStatus: DataProcessingStatus;
  sourceCollectionSummary?: {
    assignmentCount: number;
    openAssignmentCount: number;
    searchAssignmentCount: number;
    searchOpenAssignmentCount: number;
    collectionAssignmentCount: number;
    collectionOpenAssignmentCount: number;
    downstreamAssignmentCount: number;
    downstreamOpenAssignmentCount: number;
  };
  storageArtifacts: SourceCollectionStorageArtifacts;
  assignments: TeamWorkflowSourceCollectionRunStartPayload["assignments"];
  outputs: Array<DataProcessingCollectionOutputPayload["output"]>;
  createdRecords: DataProcessingCollectionOutputPayload["createdRecords"];
  imported: TeamWorkflowDataRecordSourceCandidateImportPayload[];
  executionEvents: SourceCollectionSearchExecutionEvent[];
  activeWorkRun?: {
    runId: string;
    status: string;
    currentPhase: string;
    currentTask?: string;
    summary?: string;
    openAssignmentCount?: number;
    searchAssignmentCount?: number;
    searchOpenAssignmentCount?: number;
    collectionAssignmentCount?: number;
    collectionOpenAssignmentCount?: number;
    downstreamAssignmentCount?: number;
    downstreamOpenAssignmentCount?: number;
    recordCount?: number;
    queryCount?: number;
    error?: string;
    errorType?: string;
    storagePath?: string;
    updatedAt?: string;
  };
  boundaries: {
    externalSearchTriggered: boolean;
    externalSearchQueued?: boolean;
    metadataOnlyDownload: boolean;
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
  };
  nextActions: string[];
};

export type TeamWorkflowPaperNoteChunkPlanPayload = {
  candidate: TeamWorkflowCandidate;
  chunkPlan: {
    planId: string;
    status: string;
    chunkCount: number;
  };
  workflow: TeamWorkflowOrchestration;
  nextActions: string[];
};

export type TeamWorkflowSourceQualityAssessmentPayload = {
  candidate: TeamWorkflowCandidate;
  assessment: {
    assessmentId: string;
    decision: string;
    scores: {
      relevance: number;
      reliability: number;
      accessibility: number;
      extractionReadiness: number;
      overall: number;
    };
  };
  status: TeamWorkflowSourceQualityStatus;
  workflow: TeamWorkflowOrchestration;
  nextActions: string[];
};

export type TeamWorkflowSourceQualityBatchAssessmentPayload = {
  schemaVersion: number;
  teamId: string;
  workflowId: string;
  batchRunId: string;
  executionMode: string;
  status: string;
  assessedByAgent: string;
  summary: {
    targetCandidateCount: number;
    assessedCandidateCount: number;
    approvedCandidateCount: number;
    needsRevisionCandidateCount: number;
    rejectedCandidateCount: number;
    failedCandidateCount: number;
    skippedCandidateCount: number;
  };
  assessments: Array<{
    candidateId: string;
    title: string;
    assessmentId: string;
    decision: string;
    overallScore: number;
    requiredFixes: string[];
    riskFlags: string[];
    currentState: string;
    qualityStatus: string;
    assessedAt: string;
  }>;
  skippedCandidates: Array<{ candidateId: string; title?: string; reason: string }>;
  failedCandidates: Array<{ candidateId: string; error: string }>;
  sourceQualityStatus: TeamWorkflowSourceQualityStatus;
  workflow: TeamWorkflowOrchestration;
  officialBoundary: {
    writesFormalKnowledge: boolean;
    writesRag: boolean;
    writesOfficialGraph: boolean;
    candidateOnly: boolean;
  };
  nextActions: string[];
  updatedAt: string;
};
