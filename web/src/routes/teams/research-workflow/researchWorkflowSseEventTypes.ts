/**
 * Registry mirroring the backend `WorkflowEventType` enum
 * (core/research/workflow/contracts/workflow_event.py).
 *
 * This is no longer a drop-gate: the SSE hook accepts every well-formed
 * workflow event frame, including types that are missing from this list
 * (forward compatibility). Keeping the list in sync documents the known
 * contract and lets new surfaces switch on typed values.
 */
export const RESEARCH_WORKFLOW_SSE_EVENT_TYPES = [
  "run_created",
  "command_accepted",
  "command_failed",
  "node_starting",
  "node_running",
  "node_waiting_human",
  "node_succeeded",
  "node_failed",
  "node_blocked",
  "handoff_ready",
  "handoff_accepted",
  "handoff_rejected",
  "budget_reserved",
  "budget_settled",
  "execution_anchor_bound",
  "artifact_verified",
  "workflow.session_scope.resolved",
  "workflow.child_session.created",
  "workflow.child_session.resumed",
  "workflow.scope_attempt.retried",
  "workflow.hypothesis_fragment.recorded",
  "workflow.hypothesis_aggregation.blocked",
  "workflow.hypothesis_aggregation.completed",
  "run_forked",
  "revision_forked",
  "run_blocked",
  "run_succeeded",
  "reconciliation_required",
  "delivery_orchestration_completed",
  "delivery_orchestration_blocked",
  "delivery_orchestration_failed",
] as const;

export type ResearchWorkflowSseEventType =
  typeof RESEARCH_WORKFLOW_SSE_EVENT_TYPES[number];
