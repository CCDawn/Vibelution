import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../app/browserTelemetry", () => ({
  collectBrowserPageSnapshot: () => ({
    pageInstanceId: "page-test",
    href: "http://localhost/",
    pathname: "/teams",
    search: "",
    hash: "",
    title: "test",
    telemetrySurface: "vite_dev",
    browserRole: "primary",
  }),
  postBrowserTelemetry: vi.fn(),
}));

import { postBrowserTelemetry } from "../../app/browserTelemetry";
import { resetUserActionTelemetryForTests, type UserActionTracker } from "../../app/userActionTelemetry";
import {
  observeQuestionOutputSchemaRejected,
  observeRealBatchAuthorizeShapeInvalid,
  observeRealBatchPollLoopStopped,
  observeWorkflowReplayFailed,
  observeWorkflowReplayResync,
  observeWorkflowStreamFrameInvalid,
  observeWorkflowStreamInterrupted,
  observeWorkflowStreamReconnected,
  trackDevBatchRun,
  trackDevReadinessRun,
  trackExperimentActivation,
  trackHypothesisCandidateGenerationOpen,
  trackHypothesisSelectionRecord,
  trackQuestionPublishSubmit,
  trackQuestionRegisterSubmit,
  trackQuestionReviewSubmit,
  trackQuestionRunReset,
  trackRealBatchAuthorize,
  trackRealBatchCancel,
  trackRealBatchStart,
  trackResearchRunCreate,
  trackWorkflowHumanGateResolve,
} from "./challengeCupTelemetry";

const TRACKER_CASES: Array<[string, () => UserActionTracker]> = [
  ["challenge_question_review_submit", () => trackQuestionReviewSubmit({ teamId: "research-team" })],
  ["challenge_question_register_submit", () => trackQuestionRegisterSubmit({ teamId: "research-team" })],
  ["challenge_question_publish_submit", () => trackQuestionPublishSubmit({ teamId: "research-team" })],
  ["challenge_question_run_reset", () => trackQuestionRunReset({ teamId: "research-team" })],
  ["challenge_hypothesis_selection_record", () => trackHypothesisSelectionRecord({ teamId: "research-team" })],
  ["challenge_hypothesis_candidate_generation_open", () => trackHypothesisCandidateGenerationOpen({ teamId: "research-team" })],
  ["challenge_research_run_create", () => trackResearchRunCreate({ teamId: "research-team" })],
  ["challenge_experiment_activation", () => trackExperimentActivation({ teamId: "research-team" })],
  ["challenge_real_batch_authorize", () => trackRealBatchAuthorize({ teamId: "research-team" })],
  ["challenge_real_batch_start", () => trackRealBatchStart({ teamId: "research-team" })],
  ["challenge_real_batch_cancel", () => trackRealBatchCancel({ teamId: "research-team" })],
  ["challenge_dev_readiness_run", () => trackDevReadinessRun({ teamId: "research-team" })],
  ["challenge_dev_batch_run", () => trackDevBatchRun({ teamId: "research-team" })],
  ["challenge_workflow_human_gate_resolve", () => trackWorkflowHumanGateResolve({ teamId: "research-team" })],
];

function postedPayloads(): Array<Record<string, unknown>> {
  return vi.mocked(postBrowserTelemetry).mock.calls.map((call) => call[0] as Record<string, unknown>);
}

afterEach(() => {
  vi.clearAllMocks();
  resetUserActionTelemetryForTests();
});

describe("challengeCupTelemetry user-action trackers", () => {
  it.each(TRACKER_CASES)("%s emits started then terminal outcome", (action, start) => {
    const tracker = start();
    tracker.succeeded({ questionId: "Q001" });
    const payloads = postedPayloads();
    expect(payloads).toHaveLength(2);
    expect(payloads[0]).toMatchObject({
      phase: "user_action",
      eventCode: `browser.user_action.${action}_started`,
      level: "info",
    });
    expect(payloads[0].fields).toMatchObject({ action, outcome: "started", teamId: "research-team" });
    expect(payloads[1]).toMatchObject({
      eventCode: `browser.user_action.${action}_succeeded`,
      level: "info",
    });
    expect(payloads[1].fields).toMatchObject({ action, outcome: "succeeded", questionId: "Q001" });
  });

  it("emits failed with error name and truncated message", () => {
    const tracker = trackQuestionReviewSubmit({ teamId: "research-team", questionId: "Q002" });
    tracker.failed(new Error(`x`.repeat(400)), { stateConflict: false });
    const payloads = postedPayloads();
    expect(payloads[1]).toMatchObject({
      eventCode: "browser.user_action.challenge_question_review_submit_failed",
      level: "error",
    });
    const fields = payloads[1].fields as Record<string, unknown>;
    expect(fields.errorName).toBe("Error");
    expect(String(fields.errorMessage).length).toBeLessThanOrEqual(240);
    expect(fields.stateConflict).toBe(false);
  });

  it("keeps destructive gate actions off the control-signal suppression path", () => {
    const cancel = trackRealBatchCancel({ teamId: "research-team", planId: "real-5" });
    cancel.succeeded();
    const reset = trackQuestionRunReset({ teamId: "research-team", questionId: "Q003" });
    reset.succeeded();
    const readiness = trackDevReadinessRun({ teamId: "research-team", mode: "dev" });
    readiness.succeeded();
    const payloads = postedPayloads();
    for (const payload of payloads) {
      const fields = payload.fields as Record<string, unknown>;
      if (fields.action === "challenge_real_batch_cancel" || fields.action === "challenge_question_run_reset") {
        expect(fields.controlSignal).toBeUndefined();
      }
    }
  });
});

describe("challengeCupTelemetry anomaly observations", () => {
  it("reports stream interruption once with warning level and bounded reason", () => {
    observeWorkflowStreamInterrupted({
      teamId: "research-team",
      runId: "run-1",
      reason: `中断`.repeat(200),
    });
    const payloads = postedPayloads();
    expect(payloads).toHaveLength(1);
    expect(payloads[0]).toMatchObject({
      eventCode: "browser.user_action.challenge_workflow_stream_interrupted_observed",
      level: "warning",
    });
    const fields = payloads[0].fields as Record<string, unknown>;
    expect(String(fields.reason).length).toBeLessThanOrEqual(160);
    expect(fields.runId).toBe("run-1");
  });

  it("reports stream recovery with attempt and downtime counters", () => {
    observeWorkflowStreamReconnected({
      teamId: "research-team",
      runId: "run-1",
      reconnectAttempts: 3,
      downtimeMs: 4200,
    });
    const payloads = postedPayloads();
    expect(payloads[0]).toMatchObject({
      eventCode: "browser.user_action.challenge_workflow_stream_reconnected_observed",
      level: "info",
    });
    expect(payloads[0].fields).toMatchObject({ reconnectAttempts: 3, downtimeMs: 4200 });
  });

  it("reports invalid frames without raw frame content", () => {
    observeWorkflowStreamFrameInvalid({ teamId: "research-team", runId: "run-1", eventType: "node_delta" });
    observeWorkflowStreamFrameInvalid({ teamId: "research-team", runId: "run-1" });
    const payloads = postedPayloads();
    expect(payloads[0].fields).toMatchObject({ eventType: "node_delta" });
    expect(payloads[1].fields).not.toHaveProperty("eventType");
  });

  it("reports replay resync and replay failure", () => {
    observeWorkflowReplayResync({ teamId: "research-team", runId: "run-1", lastSequence: 42 });
    observeWorkflowReplayFailed({
      teamId: "research-team",
      runId: "run-1",
      error: new Error("replay blew up"),
    });
    const payloads = postedPayloads();
    expect(payloads[0]).toMatchObject({
      eventCode: "browser.user_action.challenge_workflow_replay_resync_observed",
      level: "info",
    });
    expect(payloads[0].fields).toMatchObject({ lastSequence: 42 });
    expect(payloads[1]).toMatchObject({
      eventCode: "browser.user_action.challenge_workflow_replay_failed_observed",
      level: "warning",
    });
    expect(payloads[1].fields).toMatchObject({ errorName: "Error", errorMessage: "replay blew up" });
  });

  it("reports real-batch poll stop and authorize shape anomalies", () => {
    observeRealBatchPollLoopStopped({
      teamId: "research-team",
      planId: "real-125",
      error: "status unavailable",
    });
    observeRealBatchAuthorizeShapeInvalid({ teamId: "research-team", planId: "real-1" });
    const payloads = postedPayloads();
    expect(payloads[0].eventCode).toBe("browser.user_action.challenge_real_batch_poll_loop_stopped_observed");
    expect(payloads[0].fields).toMatchObject({ planId: "real-125", errorMessage: "status unavailable" });
    expect(payloads[1].eventCode).toBe("browser.user_action.challenge_real_batch_authorize_shape_invalid_observed");
    expect(payloads[1]).toMatchObject({ level: "warning" });
  });

  it("reports schema rejection with truncated parse error", () => {
    observeQuestionOutputSchemaRejected({
      teamId: "research-team",
      questionId: "Q004",
      outputLength: 1200,
      parseError: `坏`.repeat(300),
    });
    const payloads = postedPayloads();
    expect(payloads[0].eventCode).toBe("browser.user_action.challenge_question_output_schema_rejected_observed");
    const fields = payloads[0].fields as Record<string, unknown>;
    expect(String(fields.parseError).length).toBeLessThanOrEqual(160);
    expect(fields.outputLength).toBe(1200);
  });
});
