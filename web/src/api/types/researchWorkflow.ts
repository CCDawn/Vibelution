/**
 * Research workflow domain DTOs (Task 1 contract).
 * Mirrors core/research/workflow — server is authority for run state.
 * selectedNodeId is UI-only and must not appear on server projections.
 */

export type ActorKind = "agent" | "system" | "human";

export type WorkflowStageId =
  | "knowledge_collection"
  | "experiment_design"
  | "execution_iteration";

export type WorkflowRunStatus =
  | "queued"
  | "running"
  | "waiting_human"
  | "blocked"
  | "succeeded"
  | "failed"
  | "cancelled";

export type NodeRunStatus =
  | "pending"
  | "ready"
  | "running"
  | "waiting_human"
  | "succeeded"
  | "failed"
  | "blocked"
  | "skipped"
  | "stale"
  | "cancelled";

export type HandoffStatus =
  | "pending"
  | "ready"
  | "waiting_human"
  | "accepted"
  | "rejected"
  | "superseded"
  | "failed";

export type GateKind =
  | "auto"
  | "human"
  | "knowledge_package"
  | "frozen_protocol"
  | "smoke"
  | "promotion";

export type ArtifactRef = {
  artifactId: string;
  kind: string;
  version: string;
  contentHash: string;
  uri?: string;
  summary?: string;
};

export type WorkflowNodeSpec = {
  nodeId: string;
  stageId: WorkflowStageId;
  label: string;
  actorKind: ActorKind;
  primaryRoleKey: string;
  description?: string;
  collaboratorRoleKeys?: string[];
  acceptsGateKinds?: GateKind[];
  producesArtifactKinds?: string[];
};

export type WorkflowStageSpec = {
  stageId: WorkflowStageId;
  index: number;
  label: string;
  nodeIds: string[];
};

export type WorkflowEdgeSpec = {
  edgeId: string;
  fromNodeId: string;
  toNodeId: string;
  label: string;
  gateKind: GateKind;
  requiredArtifactKinds?: string[];
  requiresHumanAccept?: boolean;
};

export type WorkflowDefinition = {
  workflowId: string;
  schemaVersion: string;
  label: string;
  structureHash: string;
  stages: WorkflowStageSpec[];
  nodes: WorkflowNodeSpec[];
  edges: WorkflowEdgeSpec[];
};

export type WorkflowNodeRunProjection = {
  nodeId: string;
  status: NodeRunStatus;
  nodeRunId?: string | null;
  attempt?: number;
  primaryAgentId?: string;
  actorKind?: ActorKind | "";
};

export type HumanTaskSummary = {
  taskId: string;
  nodeId: string;
  status: string;
  prompt?: string;
};

/** Server canvas projection — never includes selectedNodeId. */
export type WorkflowCanvasProjection = {
  definition: WorkflowDefinition;
  run: {
    runId: string | null;
    status: WorkflowRunStatus | null;
    runtimeCurrentNodeIds: string[];
    nodeRuns: Record<string, WorkflowNodeRunProjection>;
    pendingHumanTasks: HumanTaskSummary[];
  };
};

export type RunAgentBindingSnapshot = {
  snapshotId: string;
  workflowId: string;
  workflowVersionId: string;
  runId: string;
  nodeId: string;
  agentId: string;
  roleKey: string;
  actorKind: ActorKind;
  resolvedFrom: string;
  displayName?: string;
  modelProfileId?: string;
  capturedAt?: string;
};

export type NodeAgentSessionBinding = {
  bindingId: string;
  workflowId: string;
  workflowVersionId: string;
  runId: string;
  nodeId: string;
  nodeRunId: string;
  nodeAttempt: number;
  agentId: string;
  roleKey: string;
  sessionId: string;
  sessionAttempt: number;
  taskId: string;
  turnId: string;
  checkpointId: string;
  status: string;
  boundAt: string;
  supersedesBindingId?: string;
};

export type NodeHandoffRecord = {
  handoffId: string;
  workflowId: string;
  workflowVersionId: string;
  runId: string;
  fromNodeId: string;
  fromNodeRunId: string;
  toNodeId: string;
  toNodeRunId?: string;
  gateKind: GateKind;
  outputArtifactRefs: ArtifactRef[];
  inputSnapshotHash: string;
  status: HandoffStatus;
  offeredAt: string;
  acceptedAt?: string;
  acceptedBy?: string;
  rejectionReason?: string;
  supersedesHandoffId?: string;
  humanTaskId?: string;
};

/** Canonical Challenge Cup fixed node ids (v1 topology). */
export const CHALLENGE_CUP_NODE_IDS = [
  "source_finding",
  "source_extraction",
  "evidence_relations",
  "knowledge_ingestion",
  "knowledge_handoff",
  "hypothesis_design",
  "protocol_design",
  "protocol_review",
  "protocol_freeze",
  "smoke_gate",
  "controlled_run",
  "result_evaluation",
  "iteration_decision",
  "candidate_promotion",
  "result_package",
] as const;

export type ChallengeCupNodeId = (typeof CHALLENGE_CUP_NODE_IDS)[number];

export const CHALLENGE_CUP_WORKFLOW_ID = "challenge-cup-research";
