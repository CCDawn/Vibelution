/** Formal CommandOffer / CommandReceipt contracts (T6). */

export type WorkflowCommandKind =
  | "start_node"
  | "retry_node"
  | "cancel_node"
  | "resolve_human_task"
  | "rebind_node"
  | "fork_revision"
  | "extend_budget"
  | "cancel_run"
  | "reconcile_run";

export type CommandOffer = {
  command: WorkflowCommandKind;
  nodeId: string | null;
  available: boolean;
  label: string;
  reasonCode: string;
  blockerIds: string[];
  idempotencyKey: string;
  expectedRunVersion: number;
  payload: Record<string, unknown>;
  destructive?: boolean;
  confirmation?: {
    title: string;
    body: string;
    confirmLabel: string;
    cancelLabel: string;
  } | null;
};

export type CommandReceipt = {
  commandId: string;
  runId: string;
  status: string;
  acceptedRunVersion: number | null;
  idempotencyKey: string;
  latestEventSequence: number;
  problem: unknown | null;
};
