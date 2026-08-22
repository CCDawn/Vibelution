/** Formal research workflow snapshot / core DTOs (T6). No UI-only fields. */

export type ChallengeCupNodeId = string;

export type WorkflowRunSummary = {
  runId: string;
  teamId: string;
  workflowId: string;
  workflowVersionId: string;
  threadId: string;
  projectId: string;
  questionId: string;
  status: string;
  runVersion: number;
  inputSnapshotHash: string;
  bindingSnapshotSetId: string;
  activeNodeId: string | null;
  parentRunId: string | null;
  forkedFromCheckpointId: string | null;
  completionKind: string | null;
  terminalReason: string | null;
  createdAtMs: number;
  updatedAtMs: number;
  completedAtMs: number | null;
  blockedReason?: string | null;
};

export type NodeAttemptSummary = {
  nodeRunId: string;
  nodeId: string;
  attempt: number;
  actorKind: string;
  status: string;
  commandId: string;
  bindingSnapshotId: string | null;
  inputSnapshotHash: string;
  executionAnchorId: string | null;
  startedAtMs: number;
  updatedAtMs: number;
  finishedAtMs: number | null;
  problem?: Record<string, unknown> | null;
};

export type HumanTaskSummary = {
  taskId: string;
  runId: string;
  nodeRunId: string;
  nodeId?: string | null;
  handoffId?: string | null;
  taskKind: string;
  status: string;
  createdAtMs: number;
  resolvedAtMs?: number | null;
};

/**
 * A candidate-scoped child-session summary returned with node detail.
 *
 * The node root remains represented by the legacy session fields on
 * `ResearchWorkflowNodeDetail`; these anchors are ordered by the server's
 * current selection and must not be re-sorted by the Inspector.
 */
export type NodeSessionAnchor = {
  scopeKind?: "workflow_node_root" | "workflow_candidate";
  nodeId?: string | null;
  nodeRunId?: string | null;
  selectionId?: string | null;
  candidateId?: string | null;
  subtaskId?: string | null;
  sessionId?: string | null;
  attempt?: number | null;
  sessionAttempt?: number | null;
  taskId?: string | null;
  turnId?: string | null;
  status?: string | null;
  chatDeepLink?: string | null;
  /** Older fan-out responses call this field `chatRoute`. */
  chatRoute?: string | null;
  fragmentRef?: string | null;
  fragmentRefs?: string[];
  parentSessionId?: string | null;
  rootSessionId?: string | null;
  sessionAnchorDegraded?: boolean;
  sessionAnchorDegradedReason?: string | null;
};

export type ScopedSessionAnchor = NodeSessionAnchor & {
  scopeKind: "workflow_candidate";
  candidateId: string;
};

export type HandoffSummary = {
  countsByStatus: Record<string, number>;
  refs: Array<{
    handoffId?: string | null;
    fromNodeId?: string | null;
    fromNodeRunId?: string | null;
    toNodeId?: string | null;
    status: string;
    inputSnapshotHash?: string | null;
    outputArtifactRefs?: Array<Record<string, unknown>>;
    offeredAtMs?: number | null;
    acceptedAtMs?: number | null;
  }>;
  count: number;
};

export type AgentBindingRef = {
  nodeId: string;
  agentId: string;
  roleKey: string;
  resolvedFrom: string;
  snapshotId?: string;
};

export type AgentBindingSummary = {
  bindingSnapshotSetId: string;
  bindingSnapshotIds: string[];
  count: number;
  bindings?: AgentBindingRef[];
};

export type BudgetSummary = {
  safetyLimits: unknown;
  receiptRefs: Array<{
    receiptId?: string | null;
    nodeRunId?: string | null;
    status?: string | null;
    policyHash?: string | null;
  }>;
  receiptCount: number;
};

export type ResearchWorkflowNodeDetail = {
  runId: string;
  teamId: string;
  nodeId: ChallengeCupNodeId;
  runVersion: number;
  actorKind: string;
  primaryRoleKey: string;
  label: string;
  runtimeCurrent: boolean;
  status: string | null;
  bindingSnapshotId?: string | null;
  latestAttempt?: NodeAttemptSummary | null;
  attempts: NodeAttemptSummary[];
  commandOffers: import("./commands").CommandOffer[];
  latestEventSequence: number;
  generatedAt: string;
  agentId?: string | null;
  displayName?: string;
  resolvedFrom?: string;
  sessionId?: string | null;
  taskId?: string | null;
  turnId?: string | null;
  sessionAttempt?: number | null;
  chatDeepLink?: string | null;
  sessionAnchorDegraded?: boolean;
  rootSession?: NodeSessionAnchor | null;
  scopedSessions?: ScopedSessionAnchor[];
  blockedReason?: string;
  nodeAttempt?: number;
};

export type ResearchWorkflowSnapshot = {
  run: WorkflowRunSummary;
  definition: Record<string, unknown>;
  nodeAttempts: Record<string, NodeAttemptSummary[]>;
  activeNodeIds: ChallengeCupNodeId[];
  pendingHumanTasks: HumanTaskSummary[];
  commandOffers: import("./commands").CommandOffer[];
  handoffSummary: HandoffSummary;
  agentBindingSummary: AgentBindingSummary;
  budgetSummary: BudgetSummary;
  latestEventSequence: number;
  generatedAt: string;
};
