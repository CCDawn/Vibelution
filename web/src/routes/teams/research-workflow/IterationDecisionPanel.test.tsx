/**
 * IterationDecisionPanel contracts:
 * - payload construction offers exactly the five structured decision kinds and
 *   only kind-specific fields (terminalReason / selectedCandidateRef);
 * - the panel renders decision history and submits through the run-level
 *   iteration_decision command with an idempotency key.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  DECISION_KINDS,
  IterationDecisionPanel,
  buildIterationDecisionPayload,
} from "./IterationDecisionPanel";

const RUN = {
  runId: "run-1",
  workflowId: "challenge-cup-research",
  workflowVersionId: "v1",
  status: "waiting_human",
  runtimeCurrentNodeIds: ["iteration_decision"],
  humanTasks: [],
  iterationDecisions: [
    {
      decisionId: "dec-1",
      decisionKind: "rerun_same_protocol",
      iterationAttempt: 1,
      reason: "improve precision",
    },
  ],
};

describe("buildIterationDecisionPayload", () => {
  it("rejects empty kind or reason", () => {
    expect(buildIterationDecisionPayload({ decisionKind: "", reason: "x" })).toBeNull();
    expect(buildIterationDecisionPayload({ decisionKind: "stop", reason: "  " })).toBeNull();
  });

  it("builds a bare decision with operator attribution", () => {
    const payload = buildIterationDecisionPayload({ decisionKind: "rerun_same_protocol", reason: " retry " });
    expect(payload).toEqual({
      decisionKind: "rerun_same_protocol",
      reason: "retry",
      decidedBy: "operator",
    });
  });

  it("adds terminalReason only for stop", () => {
    const stop = buildIterationDecisionPayload({
      decisionKind: "stop",
      reason: "enough",
      terminalReason: "enough_evidence",
    });
    expect(stop?.terminalReason).toBe("enough_evidence");
    const rerun = buildIterationDecisionPayload({
      decisionKind: "rerun_same_protocol",
      reason: "retry",
      terminalReason: "unused",
    });
    expect(rerun?.terminalReason).toBeUndefined();
  });

  it("adds selectedCandidateRef only for promote/rollback", () => {
    const promote = buildIterationDecisionPayload({
      decisionKind: "promote_candidate",
      reason: "best",
      candidateRef: "candidate:9",
    });
    expect(promote?.selectedCandidateRef).toBe("candidate:9");
    expect(promote?.terminalReason).toBeUndefined();
    const stop = buildIterationDecisionPayload({
      decisionKind: "stop",
      reason: "enough",
      candidateRef: "candidate:9",
    });
    expect(stop?.selectedCandidateRef).toBeUndefined();
  });
});

describe("IterationDecisionPanel", () => {
  it("renders decision history from the run record", () => {
    const markup = renderToStaticMarkup(
      <IterationDecisionPanel runId="run-1" run={RUN} busy={false} onRefresh={vi.fn()} />,
    );
    expect(markup).toContain("同协议重跑");
    expect(markup).toContain("improve precision");
    expect(markup).toContain("决策历史（1）");
  });

  it("offers exactly the five structured kinds and no free-form strings", () => {
    expect(DECISION_KINDS.map((item) => item.id)).toEqual([
      "rerun_same_protocol",
      "revise_protocol",
      "promote_candidate",
      "rollback_candidate",
      "stop",
    ]);
    const markup = renderToStaticMarkup(
      <IterationDecisionPanel runId="run-1" run={RUN} busy={false} onRefresh={vi.fn()} />,
    );
    expect(markup).not.toContain("do_whatever");
  });

  it("renders an empty state when no run exists", () => {
    const markup = renderToStaticMarkup(
      <IterationDecisionPanel runId="" run={null} busy={false} onRefresh={vi.fn()} />,
    );
    expect(markup).toContain("创建运行后");
  });

  it("surfaces blocked state and completion info", () => {
    const blocked = renderToStaticMarkup(
      <IterationDecisionPanel
        runId="run-1"
        run={{ ...RUN, status: "blocked", blockedReason: "iteration_budget_exhausted" }}
        busy={false}
        onRefresh={vi.fn()}
      />,
    );
    expect(blocked).toContain("iteration_budget_exhausted");
    const done = renderToStaticMarkup(
      <IterationDecisionPanel
        runId="run-1"
        run={{ ...RUN, status: "succeeded", completionKind: "stopped", terminalReason: "enough_evidence" }}
        busy={false}
        onRefresh={vi.fn()}
      />,
    );
    expect(done).toContain("stopped");
    expect(done).toContain("enough_evidence");
  });
});
