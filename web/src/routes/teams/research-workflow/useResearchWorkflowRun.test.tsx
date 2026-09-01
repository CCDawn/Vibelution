/**
 * Behavioral tests for useResearchWorkflowRun orchestration (not source-string checks).
 * Reducer/SSE edge cases live in their dedicated test files.
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import type { ResearchWorkflowSnapshot } from "../../../api/types/research-workflow/core";

const api = vi.hoisted(() => ({
  fetchResearchWorkflowSnapshot: vi.fn(),
  replayResearchWorkflowEvents: vi.fn(),
  consumeResearchWorkflowEventStream: vi.fn(),
  fetchResearchWorkflowDefinition: vi.fn(),
  createResearchWorkflowRun: vi.fn(),
}));

vi.mock("../../../api/research-workflow/runs", () => ({
  fetchResearchWorkflowSnapshot: api.fetchResearchWorkflowSnapshot,
}));

vi.mock("../../../api/research-workflow/events", () => ({
  replayResearchWorkflowEvents: api.replayResearchWorkflowEvents,
  consumeResearchWorkflowEventStream: api.consumeResearchWorkflowEventStream,
}));

vi.mock("../../../api/researchWorkflow", () => ({
  fetchResearchWorkflowDefinition: api.fetchResearchWorkflowDefinition,
  createResearchWorkflowRun: api.createResearchWorkflowRun,
}));

import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import { useResearchWorkflowRun } from "./useResearchWorkflowRun";

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
      status: "waiting_human",
      runVersion: 3,
      inputSnapshotHash: "a".repeat(64),
      bindingSnapshotSetId: "binding-set-1",
      activeNodeId: "knowledge_handoff",
      parentRunId: null,
      forkedFromCheckpointId: null,
      completionKind: null,
      terminalReason: null,
      createdAtMs: 1,
      updatedAtMs: 1,
      completedAtMs: null,
    },
    definition: {
      workflowId: "challenge-cup-research",
      schemaVersion: "1.0.0",
      label: "x",
      structureHash: "h",
      stages: [],
      nodes: [],
      edges: [],
    },
    nodeAttempts: {},
    activeNodeIds: ["knowledge_handoff"],
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

function makeEnvelope(runId: string, sequence: number): WorkflowEventEnvelope {
  return {
    eventId: `evt-${runId}-${sequence}`,
    sequence,
    runId,
    teamId: "research-team",
    runVersion: 3,
    type: sequence === 1 ? "run_created" : "command_accepted",
    correlationId: "corr",
    occurredAt: "2026-08-12T14:00:00.000Z",
    payload: {},
  };
}

function makeEventPage(runId: string, sequence: number) {
  const events = Array.from({ length: sequence }, (_, index) =>
    makeEnvelope(runId, index + 1),
  );
  return {
    runId,
    teamId: "research-team",
    runVersion: 3,
    latestEventSequence: sequence,
    afterSequence: 0,
    lastReturnedSequence: sequence,
    hasMore: false,
    nextAfterSequence: null,
    events,
  };
}

type HookValue = ReturnType<typeof useResearchWorkflowRun>;

function HookProbe({
  runId,
  onValue,
}: {
  runId: string;
  onValue: (v: HookValue) => void;
}) {
  const value = useResearchWorkflowRun("research-team", runId);
  onValue(value);
  return null;
}

describe("useResearchWorkflowRun behavior", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: HookValue | null = null;

  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latest = null;
    api.fetchResearchWorkflowDefinition.mockResolvedValue({
      definition: makeSnapshot("", 0).definition,
      workflowId: "challenge-cup-research",
      workflowVersionId: "wv-x",
    });
    api.replayResearchWorkflowEvents.mockImplementation(async ({ runId }) =>
      makeEventPage(runId, runId === "run-a" ? 3 : 1).events,
    );
    api.consumeResearchWorkflowEventStream.mockImplementation(async (options) => {
      options.onOpen?.();
      await new Promise<void>((_resolve, reject) => {
        options.signal.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
          { once: true },
        );
      });
    });
  });

  afterEach(async () => {
    vi.useRealTimers();
    await act(async () => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
  });

  async function flush() {
    await act(async () => {
      await Promise.resolve();
    });
  }

  async function waitUntil(predicate: () => boolean) {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      if (predicate()) return;
      await flush();
    }
    throw new Error("hook did not settle");
  }

  async function renderWith(runId: string) {
    await act(async () => {
      root.render(
        <HookProbe
          runId={runId}
          onValue={(v) => {
            latest = v;
          }}
        />,
      );
    });
    await waitUntil(() => Boolean(latest?.run?.runId === runId && latest.lastSequence > 0));
  }

  it("replays committed events into the timeline before opening SSE", async () => {
    api.fetchResearchWorkflowSnapshot.mockResolvedValue(makeSnapshot("run-a", 3));
    await renderWith("run-a");
    expect(latest?.run?.runId).toBe("run-a");
    expect(latest?.run?.events).toHaveLength(3);
    expect(latest?.lastSequence).toBe(3);
    expect(api.replayResearchWorkflowEvents).toHaveBeenCalledWith(
      expect.objectContaining({ runId: "run-a", teamId: "research-team" }),
    );
    expect(api.consumeResearchWorkflowEventStream).toHaveBeenLastCalledWith(
      expect.objectContaining({
        runId: "run-a",
        teamId: "research-team",
        afterSequence: 3,
      }),
    );
    expect(
      api.consumeResearchWorkflowEventStream.mock.calls.at(-1)?.[0].lastEventId,
    ).toBeUndefined();
  });

  it("run switch resets sequence cursor for run B", async () => {
    api.fetchResearchWorkflowSnapshot.mockImplementation(async ({ runId }) =>
      makeSnapshot(runId, runId === "run-a" ? 100 : 1),
    );

    await renderWith("run-a");
    expect(latest?.lastSequence).toBe(100);

    await renderWith("run-b");
    expect(latest?.run?.runId).toBe("run-b");
    expect(latest?.lastSequence).toBe(1);
    expect(api.consumeResearchWorkflowEventStream).toHaveBeenLastCalledWith(
      expect.objectContaining({
        runId: "run-b",
        teamId: "research-team",
        afterSequence: 1,
      }),
    );
    expect(
      api.consumeResearchWorkflowEventStream.mock.calls.at(-1)?.[0].lastEventId,
    ).toBeUndefined();
  });

  it("slow previous run refresh does not overwrite new run", async () => {
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
      root.render(<HookProbe runId="run-a" onValue={(v) => { latest = v; }} />);
    });
    await act(async () => {
      root.render(<HookProbe runId="run-b" onValue={(v) => { latest = v; }} />);
    });
    await waitUntil(() => latest?.run?.runId === "run-b" && latest.lastSequence === 1);
    await act(async () => {
      resolveA(makeSnapshot("run-a", 5));
      await Promise.resolve();
    });
    expect(latest?.run?.runId).toBe("run-b");
    expect(latest?.lastSequence).toBe(1);
  });

  it("unknown SSE event types trigger a snapshot refetch instead of being dropped", async () => {
    api.fetchResearchWorkflowSnapshot.mockResolvedValue(makeSnapshot("run-a", 3));
    api.consumeResearchWorkflowEventStream.mockImplementation(async (options) => {
      options.onOpen?.();
      options.onFrame({
        id: "run-a:4",
        event: "workflow.brand_new.future_event",
        data: JSON.stringify({
          eventId: "evt-unknown-4",
          sequence: 4,
          runId: "run-a",
          teamId: "research-team",
          runVersion: 4,
          type: "workflow.brand_new.future_event",
          correlationId: "corr",
          occurredAt: "2026-08-12T14:00:00.000Z",
          payload: {},
        }),
      });
      await new Promise<void>((_resolve, reject) => {
        options.signal.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
          { once: true },
        );
      });
    });

    await renderWith("run-a");
    const callsAfterSettle = api.fetchResearchWorkflowSnapshot.mock.calls.length;
    for (
      let attempt = 0;
      attempt < 40 && api.fetchResearchWorkflowSnapshot.mock.calls.length <= callsAfterSettle;
      attempt += 1
    ) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 20));
      });
    }
    expect(api.fetchResearchWorkflowSnapshot.mock.calls.length).toBeGreaterThan(
      callsAfterSettle,
    );
    expect(latest?.lastSequence).toBe(4);
  });

  it("polls the snapshot while the run is non-terminal as an SSE fallback", async () => {
    // Install fake timers before mount so the fallback interval is faked too.
    vi.useFakeTimers();
    api.fetchResearchWorkflowSnapshot.mockResolvedValue(makeSnapshot("run-a", 3));
    await renderWith("run-a");
    const callsAfterSettle = api.fetchResearchWorkflowSnapshot.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_200);
    });
    expect(api.fetchResearchWorkflowSnapshot.mock.calls.length).toBeGreaterThan(
      callsAfterSettle,
    );
    vi.useRealTimers();
  });

  it("stops the fallback poll once the run reaches a terminal status", async () => {
    vi.useFakeTimers();
    const settled = makeSnapshot("run-a", 3);
    api.fetchResearchWorkflowSnapshot.mockResolvedValue({
      ...settled,
      run: { ...settled.run, status: "succeeded" },
    });
    await renderWith("run-a");
    const callsAfterSettle = api.fetchResearchWorkflowSnapshot.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120_000);
    });
    expect(api.fetchResearchWorkflowSnapshot.mock.calls.length).toBe(callsAfterSettle);
    vi.useRealTimers();
  });
});
