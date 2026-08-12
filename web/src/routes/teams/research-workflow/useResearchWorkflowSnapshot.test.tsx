/**
 * Behavioral tests for useResearchWorkflowSnapshot.
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import type { ResearchWorkflowSnapshot } from "../../../api/types/research-workflow/core";

const api = vi.hoisted(() => ({
  fetchResearchWorkflowSnapshot: vi.fn(),
}));

vi.mock("../../../api/research-workflow/runs", () => api);

import { useResearchWorkflowSnapshot } from "./useResearchWorkflowSnapshot";

function makeSnapshot(runId: string, sequence: number): ResearchWorkflowSnapshot {
  return {
    run: {
      runId,
      teamId: "research-team",
      workflowId: "challenge-cup-research",
      workflowVersionId: "wv-x",
      threadId: "thread-1",
      projectId: "project-1",
      questionId: "question-1",
      status: "running",
      runVersion: sequence,
      inputSnapshotHash: "a".repeat(64),
      bindingSnapshotSetId: "binding-set-1",
      activeNodeId: "source_finding",
      parentRunId: null,
      forkedFromCheckpointId: null,
      completionKind: null,
      terminalReason: null,
      createdAtMs: 1,
      updatedAtMs: 1,
      completedAtMs: null,
    },
    definition: { workflowId: "challenge-cup-research" },
    nodeAttempts: {},
    activeNodeIds: ["source_finding"],
    pendingHumanTasks: [],
    commandOffers: [],
    handoffSummary: { countsByStatus: {}, refs: [], count: 0 },
    agentBindingSummary: {
      bindingSnapshotSetId: "binding-set-1",
      bindingSnapshotIds: [],
      count: 0,
    },
    budgetSummary: { safetyLimits: {}, receiptRefs: [], receiptCount: 0 },
    latestEventSequence: sequence,
    generatedAt: "2026-08-12T14:00:00.000Z",
  };
}

type HookValue = ReturnType<typeof useResearchWorkflowSnapshot>;

function HookProbe({
  runId,
  onValue,
}: {
  runId: string;
  onValue: (value: HookValue) => void;
}) {
  const value = useResearchWorkflowSnapshot("research-team", runId);
  onValue(value);
  return null;
}

describe("useResearchWorkflowSnapshot", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: HookValue | null = null;

  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latest = null;
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  async function renderWith(runId: string) {
    await act(async () => {
      root.render(
        <HookProbe
          runId={runId}
          onValue={(value) => {
            latest = value;
          }}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
  }

  it("loads snapshot and exposes lastSequence from latestEventSequence", async () => {
    api.fetchResearchWorkflowSnapshot.mockResolvedValue(makeSnapshot("run-a", 7));
    await renderWith("run-a");
    expect(api.fetchResearchWorkflowSnapshot).toHaveBeenCalledWith({
      teamId: "research-team",
      runId: "run-a",
    });
    expect(latest?.snapshot?.run.runId).toBe("run-a");
    expect(latest?.lastSequence).toBe(7);
    expect(latest?.error).toBeNull();
  });

  it("ignores stale snapshot responses after run switch", async () => {
    let resolveA: (value: ResearchWorkflowSnapshot) => void = () => {};
    api.fetchResearchWorkflowSnapshot.mockImplementation(async ({ runId }) => {
      if (runId === "run-a") {
        return new Promise<ResearchWorkflowSnapshot>((resolve) => {
          resolveA = resolve;
        });
      }
      return makeSnapshot("run-b", 1);
    });

    await act(async () => {
      root.render(<HookProbe runId="run-a" onValue={(value) => { latest = value; }} />);
    });
    await act(async () => {
      root.render(<HookProbe runId="run-b" onValue={(value) => { latest = value; }} />);
    });
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      resolveA(makeSnapshot("run-a", 99));
      await Promise.resolve();
    });

    expect(latest?.snapshot?.run.runId).toBe("run-b");
    expect(latest?.lastSequence).toBe(1);
  });
});
