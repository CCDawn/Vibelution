/**
 * SC run query payload types shared by TeamsRoute and useSourceCollectionRunQueries.
 */
import type {
  DataProcessingRecord,
  DataProcessingRunListPayload,
  DataProcessingStatus,
  WorkRunSnapshot,
} from "../../api/types";
import type { SourceCollectionStorageArtifacts } from "./source-collection/presentationModel";
import type {
  ResearchStageRound,
  SourceCollectionPhaseCloseGate,
  SourceCollectionStageCardProjection,
} from "./source-collection/stageProjection";

export type DataProcessingRecordListPayload = {
  schemaVersion: number;
  runId: string;
  records: DataProcessingRecord[];
  summary: Record<string, unknown> & {
    recordCount?: number;
    sourceTypeCounts?: Record<string, number>;
    recordStatusCounts?: Record<string, number>;
  };
};

export type SourceCollectionSummaryPayload = {
  schemaVersion: number;
  teamId: string;
  runId: string;
  status: string;
  run?: DataProcessingRunListPayload["runs"][number] | Record<string, unknown>;
  runStatus?: DataProcessingStatus;
  scope?: {
    kind?: string;
    runId?: string;
    includesHistorical?: boolean;
    eligibleForPhaseCloseGate?: boolean;
  };
  summary?: {
    recordCount?: number;
    rawRecordCount?: number;
    excludedSourceCount?: number;
    assignmentCount?: number;
    openAssignmentCount?: number;
    outputCount?: number;
    sourceCandidateCount?: number;
    assessedSourceCandidateCount?: number;
    approvedSourceCandidateCount?: number;
    graphNodeCount?: number;
    stewardPackCount?: number;
    formalKnowledgeSyncCount?: number;
  };
  stageCards?: SourceCollectionStageCardProjection[];
  stageCardSummary?: ResearchStageRound["sourceCollectionStageCardSummary"];
  phaseCloseGate?: SourceCollectionPhaseCloseGate;
  latestTasks?: Record<string, SourceCollectionStageCardProjection["latestTask"]>;
  stageRound?: Partial<ResearchStageRound>;
  activeWorkRun?: WorkRunSnapshot | Record<string, unknown>;
  storageArtifacts?: Partial<SourceCollectionStorageArtifacts>;
  updatedAt?: string;
};
