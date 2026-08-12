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

export type HandoffSummary = {
  countsByStatus: Record<string, number>;
  refs: Array<{
    handoffId?: string | null;
    toNodeId?: string | null;
    status: string;
    inputSnapshotHash?: string | null;
  }>;
  count: number;
};

export type AgentBindingSummary = {
  bindingSnapshotSetId: string;
  bindingSnapshotIds: string[];
  count: number;
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
