import type { CollectionRequestRecord } from "../../../api/types/hypothesisFirst";

/**
 * The collection request record is the durable request, while
 * collectionRunStatus is the child-run state.  The latter is authoritative
 * once present because the backend updates it when a child run reaches a
 * terminal state without rewriting the request status.
 */
export function effectiveCollectionRequestStatus(
  request: Pick<CollectionRequestRecord, "status" | "collectionRunStatus"> | null | undefined,
  override?: string | null,
): string {
  const childStatus = String(request?.collectionRunStatus || "").trim().toLowerCase();
  if (childStatus) return childStatus;
  return String(override || request?.status || "").trim().toLowerCase();
}

const TERMINAL_CHILD_STATUSES = new Set([
  "failed",
  "needs_continue",
  "error",
  "blocked",
  "completed",
  "succeeded",
  "handoff_pending",
  "handed_off",
  "cancelled",
  "canceled",
  "stopped",
]);

/**
 * A terminal child run needs a user action or handoff retry, not another
 * background poll.  Unknown statuses remain pollable for forward compatibility.
 */
export function collectionRequestNeedsPolling(
  request: CollectionRequestRecord,
): boolean {
  if (request.handoffRef || request.handedOffAt) return false;
  return !TERMINAL_CHILD_STATUSES.has(effectiveCollectionRequestStatus(request));
}
