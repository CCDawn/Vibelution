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

/** Server-owned formal runtime task; UI selection is intentionally absent. */
export type ResearchWorkflowTaskState =
  | "auto_running"
  | "waiting_user"
  | "blocked_retryable"
  | "blocked_terminal"
  | "completed";

export type ResearchWorkflowBlockedReason = {
  code: string | null;
  detail: string | null;
  retryable: boolean;
  failureClass: string | null;
  message: string | null;
  blockerIds: string[];
};

export type ResearchWorkflowTaskRecovery = {
  status: "none" | "retryable" | "terminal";
  retryable: boolean;
  code: string | null;
  detail: string | null;
  retryScope: "task" | "run" | "original_version" | "current_version" | "none";
  recoveryPoint: string | null;
  nextRetryAt: string | null;
  requiresOperator: boolean;
  afterSubmit: string | null;
};

export type ResearchWorkflowCurrentTask = {
  key: string;
  nodeId: ChallengeCupNodeId | null;
  stageId: string | null;
  nodeRunId: string | null;
  attempt: number | null;
  actorKind: string | null;
  taskId: string | null;
  status: string;
  state: ResearchWorkflowTaskState;
  kind: "node" | "human_gate" | "run";
  label: string | null;
  detail: string | null;
  responsibility: "system" | "user" | "operator";
  maxAttempts: number | null;
  automaticNextStep: {
    nodeId?: ChallengeCupNodeId | null;
    effectCode: string;
  } | null;
  blockedReason: ResearchWorkflowBlockedReason | null;
  recovery: ResearchWorkflowTaskRecovery;
  authority: "formal_runtime";
};

export type ResearchWorkflowProgress = {
  completedNodes: number;
  totalNodes: number;
  blockedNodes: number;
  currentStageId: string | null;
  stages: Array<{
    id: string;
    completed: number;
    total: number;
    blocked: number;
    state: "completed" | "current" | "upcoming" | "blocked";
  }>;
  completedNodeIds: ChallengeCupNodeId[];
  blockedNodeIds: ChallengeCupNodeId[];
  completed: number;
  total: number;
  percent: number;
  currentNodeId: ChallengeCupNodeId | null;
  status: string;
};

export type ResearchWorkflowRetry = {
  available: boolean;
  command: string | null;
  nodeId: ChallengeCupNodeId | null;
  reasonCode: string;
  idempotencyKey: string | null;
  expectedRunVersion: number | null;
};

export type ResearchWorkflowRecovery = ResearchWorkflowTaskRecovery;

export type ResearchWorkflowArtifactSummary = {
  count: number;
  materializedCount: number;
  kinds: string[];
  finalArtifactId: string | null;
  finalArtifactLocator: string | null;
  refs: Array<{
    receiptId: string | null;
    nodeRunId: string | null;
    kind: string;
    version: string;
    canonicalRef: string | null;
    sha256: string;
    domainRevision: string;
    materialized: boolean;
    verifiedAtMs: number;
  }>;
};

/** Server-authored identity for the one active Challenge Cup discussion. */
export type ResearchWorkflowActiveDiscussionAnchor = {
  scope: Record<string, unknown> | null;
  scopeHash: string;
  roomId: string;
  meetingRoundId: string;
  questionId: string;
  selectionId: string;
  candidateId: string;
  deepLink: string;
  status: "ready" | "degraded";
  degradedReason: string;
};

export type ResearchWorkflowLaunchContext = {
  questionId: string | null;
  hypothesisSelectionId: string | null;
  catalogAuthorizationId: string | null;
  readinessReportSha256: string | null;
  chainCorrelationId: string | null;
  source?: string | null;
  sourceCollectionRunId?: string | null;
  authorizationId?: string | null;
  planId?: string | null;
  scopeHash?: string | null;
  recordHash?: string | null;
  approvedBy?: string | null;
  approvedAtMs?: number | null;
  inputSnapshotHash?: string | null;
  /** Never inferred from the team's legacy linkedChatRoomId. */
  activeDiscussionAnchor?: ResearchWorkflowActiveDiscussionAnchor | null;
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

/** One recent knowledge-collection invocation (canvas lineage row). */
export type KnowledgeInvocationRecentSummary = {
  invocationId: string;
  parentNodeId: string;
  status: string | null;
  handoffState: string | null;
  currentKnowledgeNodeId: string | null;
  knowledgeChildRunId?: string | null;
  knowledgePackageRef?: string | null;
  packageContentHash?: string | null;
  errorSummary?: string | null;
  createdAtMs?: number;
  updatedAtMs?: number;
  /** Real per-sideflow-node status of the child run's latest attempt
   * (sideflow nodeId → raw status). Empty on legacy snapshots. */
  childNodeStates?: Record<string, string>;
};

/** Per-main-node knowledge invocation aggregate (canvas badge facts). */
export type KnowledgeInvocationBadge = {
  nodeId: string;
  totalCount: number;
  runningCount: number;
  awaitingHandoffCount: number;
  absorbedCount: number;
  failedCount?: number;
  latest?: KnowledgeInvocationRecentSummary | null;
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
  /** Optional for legacy clients/fixtures; present on v2 server snapshots. */
  schemaVersion?: 2;
  currentTask?: ResearchWorkflowCurrentTask | null;
  progress?: ResearchWorkflowProgress;
  retry?: ResearchWorkflowRetry;
  recovery?: ResearchWorkflowRecovery;
  artifactSummary?: ResearchWorkflowArtifactSummary;
  deliveryStatus?: string | null;
  launchContext?: ResearchWorkflowLaunchContext;
  /** Knowledge-sideflow badge aggregates keyed by parent node id (additive). */
  invocationBadges?: Record<string, KnowledgeInvocationBadge>;
  /** How the read layer resolved this run's pinned definition:
   * "pinned" | "legacy_default" | "degraded". */
  definitionResolution?: "pinned" | "legacy_default" | "degraded" | string;
  /** Server-authored Stage 1 topology roles and terminal authority. */
  stageOne?: {
    authority: "challenge_program";
    completionState: "pending" | "STAGE1_G1_ACCEPTED";
    formalTopology: {
      workflowId: string;
      workflowVersionId: string;
      definitionResolution: string;
      role: "execution_authority";
    };
    hypothesisView: {
      nodePrefix: "hf_";
      role: "operator_projection";
    };
    knowledgeFlow: {
      topology: "embedded" | "child_workflow";
      rolloutMode: string;
      role: "formal_graph_nodes" | "optional_child_workflow";
    };
  };
};
