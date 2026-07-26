/**
 * Payload types for Teams workflow start / stage-session mutations.
 * Promoted out of TeamsRoute so start hooks stay free of route-local types.
 */
import type {
  TeamWorkflowOrchestration,
  TeamWorkflowSourceCollectionRunStartPayload,
} from "../../api/types";
import type {
  ResearchStagePhaseStatus,
  ResearchStageRound,
  ResearchStageRoundStatusPayload,
} from "./source-collection/stageProjection";
import type { TeamWorkflowSourceCollectionSearchExecutionPayload } from "./sourceCollectionMutationModel";

export type ResearchStageRoundStartPayload = {
  created: boolean;
  continued?: boolean;
  stageRound: ResearchStageRound;
  phase: ResearchStagePhaseStatus;
  status: ResearchStageRoundStatusPayload;
  workflow: TeamWorkflowOrchestration;
  sourceCollectionRun?: TeamWorkflowSourceCollectionRunStartPayload;
  sourceCollectionSearchExecution?: TeamWorkflowSourceCollectionSearchExecutionPayload;
  run?: TeamWorkflowSourceCollectionRunStartPayload["run"];
  searchPlan?: TeamWorkflowSourceCollectionRunStartPayload["searchPlan"];
  assignments?: TeamWorkflowSourceCollectionRunStartPayload["assignments"];
  assignmentCount?: number;
  promptCachePolicy?: TeamWorkflowSourceCollectionRunStartPayload["promptCachePolicy"];
  continuedSourceRunRef?: {
    runId: string;
    status: string;
    recordCount: number;
    assignmentCount: number;
    openAssignmentCount: number;
    searchOpenAssignmentCount?: number;
    collectionOpenAssignmentCount?: number;
    downstreamOpenAssignmentCount?: number;
    queryCount?: number;
    planId?: string;
    externalSearchTriggered?: boolean;
    message?: string;
  };
  boundaries: ResearchStageRoundStatusPayload["boundaries"];
  nextActions?: string[];
};
