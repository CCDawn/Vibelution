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
  fetchResearchWorkflowDefinition: vi.fn(),
  createResearchWorkflowRun: vi.fn(),
  resolveResearchWorkflowHumanTask: vi.fn(),
  researchWorkflowStreamUrl: vi.fn(
    (options: { runId: string; teamId: string; afterSequence?: number }) => {
      const qs = new URLSearchParams({ teamId: options.teamId });
      if (options.afterSequence != null) {
        qs.set("afterSequence", String(options.afterSequence));
      }
      return `/api/research/workflow-runs/${options.runId}/stream?${qs.toString()}`;
    },
  ),
}));

vi.mock("../../../api/research-workflow/runs", () => ({
  fetchResearchWorkflowSnapshot: api.fetchResearchWorkflowSnapshot,
}));

vi.mock("../../../api/research-workflow/events", () => ({
  researchWorkflowStreamUrl: api.researchWorkflowStreamUrl,
}));

vi.mock("../../../api/researchWorkflow", () => ({
  fetchResearchWorkflowDefinition: api.fetchResearchWorkflowDefinition,
  createResearchWorkflowRun: api.createResearchWorkflowRun,
  resolveResearchWorkflowHumanTask: api.resolveResearchWorkflowHumanTask,
}));

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

type HookValue = ReturnType<typeof useResearchWorkflowRun>;

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener() {}
}

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
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latest = null;
    api.fetchResearchWorkflowDefinition.mockResolvedValue({
      definition: makeSnapshot("", 0).definition,
      workflowId: "challenge-cup-research",
      workflowVersionId: "wv-x",
    });
  });

  afterEach(async () => {
    await act(async () => {
      root.unmount();
    });
    container.remove();
    vi.unstubAllGlobals();
  });

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
    await act(async () => {
      await Promise.resolve();
    });
  }

  it("initial snapshot hydrates lastSequence without duplicating events", async () => {
    api.fetchResearchWorkflowSnapshot.mockResolvedValue(makeSnapshot("run-a", 3));
    await renderWith("run-a");
    expect(latest?.run?.runId).toBe("run-a");
    expect(latest?.run?.events).toHaveLength(0);
    expect(latest?.lastSequence).toBe(3);
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
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      resolveA(makeSnapshot("run-a", 5));
      await Promise.resolve();
    });
    expect(latest?.run?.runId).toBe("run-b");
    expect(latest?.lastSequence).toBe(1);
  });
});
