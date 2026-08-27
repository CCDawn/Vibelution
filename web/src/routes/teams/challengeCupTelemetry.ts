import {
  postUserActionObservation,
  startUserAction,
  type UserActionTracker,
} from "../../app/userActionTelemetry";

// Challenge-cup chain telemetry: action literals live only in this module so
// event codes stay greppable from one place; components call the thin wrappers.

export type ChallengeCupActionFields = { teamId: string } & Record<string, unknown>;

function truncateTelemetryText(value: string, limit: number): string {
  const text = String(value ?? "");
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, Math.max(0, limit - 3))}...`;
}

function errorSummaryFields(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    return {
      errorName: error.name,
      errorMessage: truncateTelemetryText(error.message, 240),
    };
  }
  if (error !== undefined && error !== null) {
    return { errorMessage: truncateTelemetryText(String(error), 240) };
  }
  return {};
}

// ---- user actions ----

export function trackQuestionReviewSubmit(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_question_review_submit", fields);
}

export function trackQuestionRegisterSubmit(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_question_register_submit", fields);
}

export function trackQuestionPublishSubmit(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_question_publish_submit", fields);
}

export function trackQuestionRunReset(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_question_run_reset", fields);
}

export function trackHypothesisSelectionRecord(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_hypothesis_selection_record", fields);
}

export function trackHypothesisCandidateGenerationOpen(
  fields: ChallengeCupActionFields,
): UserActionTracker {
  return startUserAction("challenge_hypothesis_candidate_generation_open", fields);
}

export function trackResearchRunCreate(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_research_run_create", fields);
}

export function trackExperimentActivation(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_experiment_activation", fields);
}

export function trackRealBatchAuthorize(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_real_batch_authorize", fields);
}

export function trackRealBatchStart(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_real_batch_start", fields);
}

export function trackRealBatchCancel(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_real_batch_cancel", fields, { destructive: true });
}

export function trackDevReadinessRun(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_dev_readiness_run", fields);
}

export function trackDevBatchRun(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_dev_batch_run", fields);
}

export function trackWorkflowHumanGateResolve(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_workflow_human_gate_resolve", fields);
}

export function trackWorkflowOfferSubmit(fields: ChallengeCupActionFields): UserActionTracker {
  return startUserAction("challenge_workflow_offer_submit", fields);
}

// ---- anomaly observations (all bounded: ref-guarded or inherently rare) ----

export function observeWorkflowStreamInterrupted(input: {
  teamId: string;
  runId: string;
  reason: string;
}): void {
  postUserActionObservation(
    "challenge_workflow_stream_interrupted",
    {
      teamId: input.teamId,
      runId: input.runId,
      reason: truncateTelemetryText(input.reason, 160),
    },
    { level: "warning", forceTimeline: true },
  );
}

export function observeWorkflowStreamReconnected(input: {
  teamId: string;
  runId: string;
  reconnectAttempts: number;
  downtimeMs: number;
}): void {
  postUserActionObservation(
    "challenge_workflow_stream_reconnected",
    {
      teamId: input.teamId,
      runId: input.runId,
      reconnectAttempts: input.reconnectAttempts,
      downtimeMs: input.downtimeMs,
    },
    { forceTimeline: true },
  );
}

export function observeWorkflowStreamFrameInvalid(input: {
  teamId: string;
  runId: string;
  eventType?: string;
}): void {
  postUserActionObservation(
    "challenge_workflow_stream_frame_invalid",
    {
      teamId: input.teamId,
      runId: input.runId,
      ...(input.eventType ? { eventType: truncateTelemetryText(input.eventType, 60) } : {}),
    },
    { level: "warning", forceTimeline: true },
  );
}

export function observeWorkflowReplayResync(input: {
  teamId: string;
  runId: string;
  lastSequence?: number;
}): void {
  postUserActionObservation(
    "challenge_workflow_replay_resync",
    {
      teamId: input.teamId,
      runId: input.runId,
      ...(input.lastSequence !== undefined ? { lastSequence: input.lastSequence } : {}),
    },
    { forceTimeline: true },
  );
}

export function observeWorkflowReplayFailed(input: {
  teamId: string;
  runId: string;
  error: unknown;
}): void {
  postUserActionObservation(
    "challenge_workflow_replay_failed",
    {
      teamId: input.teamId,
      runId: input.runId,
      ...errorSummaryFields(input.error),
    },
    { level: "warning", forceTimeline: true },
  );
}

export function observeRealBatchPollLoopStopped(input: {
  teamId: string;
  planId: string;
  error: unknown;
}): void {
  postUserActionObservation(
    "challenge_real_batch_poll_loop_stopped",
    {
      teamId: input.teamId,
      planId: input.planId,
      ...errorSummaryFields(input.error),
    },
    { level: "warning", forceTimeline: true },
  );
}

export function observeRealBatchAuthorizeShapeInvalid(input: {
  teamId: string;
  planId: string;
}): void {
  postUserActionObservation(
    "challenge_real_batch_authorize_shape_invalid",
    { teamId: input.teamId, planId: input.planId },
    { level: "warning", forceTimeline: true },
  );
}

export function observeQuestionOutputSchemaRejected(input: {
  teamId: string;
  questionId?: string;
  outputLength: number;
  parseError: string;
}): void {
  postUserActionObservation(
    "challenge_question_output_schema_rejected",
    {
      teamId: input.teamId,
      questionId: input.questionId ?? "",
      outputLength: input.outputLength,
      parseError: truncateTelemetryText(input.parseError, 160),
    },
    { level: "warning", forceTimeline: true },
  );
}

const REAL_BATCH_ALERT_PHASES = new Set(["cancelled", "circuit_breaker", "degraded"]);

export function observeRealBatchPhaseChanged(input: {
  teamId: string;
  planId: string;
  previousPhase: string;
  phase: string;
  succeededCount: number;
  failedCount: number;
  blockedCount: number;
  pendingCount: number;
  totalAttempts: number;
}): void {
  postUserActionObservation(
    "challenge_real_batch_phase_changed",
    {
      teamId: input.teamId,
      planId: input.planId,
      previousPhase: input.previousPhase,
      phase: input.phase,
      succeededCount: input.succeededCount,
      failedCount: input.failedCount,
      blockedCount: input.blockedCount,
      pendingCount: input.pendingCount,
      totalAttempts: input.totalAttempts,
    },
    { level: REAL_BATCH_ALERT_PHASES.has(input.phase) ? "warning" : "info", forceTimeline: true },
  );
}

export function observeCatalogActiveWorkChanged(input: {
  teamId: string;
  active: boolean;
  succeeded: number;
  failed: number;
  running: number;
  queued: number;
  awaitingApprovalCount: number;
}): void {
  postUserActionObservation(
    "challenge_catalog_active_work_changed",
    {
      teamId: input.teamId,
      active: input.active,
      succeeded: input.succeeded,
      failed: input.failed,
      running: input.running,
      queued: input.queued,
      awaitingApprovalCount: input.awaitingApprovalCount,
    },
    { level: !input.active && input.failed > 0 ? "warning" : "info", forceTimeline: true },
  );
}

export function observeHypothesisLegacyFallback(input: {
  teamId: string;
  questionId: string;
}): void {
  postUserActionObservation(
    "challenge_hypothesis_legacy_fallback",
    { teamId: input.teamId, questionId: input.questionId },
    { level: "warning", forceTimeline: true },
  );
}

export function observeChallengeTeamAgentsAutoRepair(input: {
  teamId: string;
  error?: unknown;
}): void {
  postUserActionObservation(
    "challenge_team_agents_auto_repair",
    {
      teamId: input.teamId,
      outcome: input.error ? "failed" : "repaired",
      ...errorSummaryFields(input.error),
    },
    { level: input.error ? "warning" : "info", forceTimeline: true },
  );
}
