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
  | "reconcile_run"
  /** Knowledge sideflow (contracts/knowledge_sideflow.py): request/inspect
   * knowledge collection for a main-chain node; handlers land with the
   * knowledge-sideflow capability module. */
  | "ensure_knowledge_collection"
  | "inspect_knowledge_collection";

/**
 * Server-signed executability facts merged into every serialized offer.
 * `requiresOperator` mirrors the command service's operator-only enforcement
 * set so the UI can render a disabled action with its reason instead of
 * letting the user hit the 403; the signature binds the offer to
 * (run, idempotency key, command, node, run version) and a validity window.
 */
export type CommandOfferAuthorization = {
  requiresOperator?: boolean;
  authorizationStatus?: "authorized" | "operator_required" | string;
  authorizationReason?: string | null;
  signedAt?: number;
  expiresAt?: number;
};

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
  /** Additive authorization envelope (server-merged, absent on old payloads). */
  requiresOperator?: boolean;
  authorizationStatus?: CommandOfferAuthorization["authorizationStatus"];
  authorizationReason?: string | null;
  signedAt?: number;
  expiresAt?: number;
};

export function isOperatorGatedOffer(
  offer: Pick<CommandOffer, "requiresOperator" | "authorizationStatus"> | null | undefined,
): boolean {
  if (!offer) return false;
  return Boolean(offer.requiresOperator) || offer.authorizationStatus === "operator_required";
}

export type CommandReceipt = {
  commandId: string;
  runId: string;
  status: string;
  acceptedRunVersion: number | null;
  idempotencyKey: string;
  latestEventSequence: number;
  problem: unknown | null;
};
