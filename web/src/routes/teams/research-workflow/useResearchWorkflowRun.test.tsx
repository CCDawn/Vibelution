/**
 * Behavioral tests for useResearchWorkflowRun orchestration (not source-string checks).
 * Reducer/SSE edge cases live in their dedicated test files.
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import type { WorkflowRunRecord } from "../../../api/researchWorkflow";

const api = vi.hoisted(() => ({
  fetchResearchWorkflowRun: vi.fn(),
  fetchResearchWorkflowCanvas: vi.fn(),
  fetchResearchWorkflowEvents: vi.fn(),
  fetchResearchWorkflowDefinition: vi.fn(),
  createResearchWorkflowRun: vi.fn(),
  resolveResearchWorkflowHumanTask: vi.fn(),
  researchWorkflowStreamUrl: vi.fn(
    (runId: string, options: { teamId: string }) =>
      `/api/research/workflow-runs/${runId}/stream?teamId=${options.teamId}`,
  ),
}));

vi.mock("../../../api/researchWorkflow", () => api);

import { useResearchWorkflowRun } from "./useResearchWorkflowRun";

function makeEvents(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    eventId: `evt-${i + 1}`,
    sequence: i + 1,
    type: "node.waiting_human",
  }));
}

function makeRun(runId: string, events = makeEvents(3)): WorkflowRunRecord {
  return {
    runId,
    workflowId: "challenge-cup-research",
    workflowVersionId: "wv-x",
    teamId: "research-team",
    projectId: "project-1",
    questionId: "question-1",
    runVersion: 3,
    status: "waiting_human",
    runtimeCurrentNodeIds: ["knowledge_handoff"],
    events: events as WorkflowRunRecord["events"],
    humanTasks: [],
    handoffs: [],
    bindingSnapshots: [],
    sessionBindings: {},
  } as WorkflowRunRecord;
}

function makeCanvas(runId: string) {
  return {
    definition: {
      workflowId: "challenge-cup-research",
      schemaVersion: "1.0.0",
      label: "x",
      structureHash: "h",
      stages: [],
      nodes: [],
      edges: [],
    },
    run: {
      runId,
      teamId: "research-team",
      runVersion: 3,
      status: "waiting_human" as const,
      runtimeCurrentNodeIds: ["knowledge_handoff"],
      nodeRuns: {},
      pendingHumanTasks: [],
    },
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
    api.fetchResearchWorkflowEvents.mockResolvedValue({ events: [], snapshot: null });
    api.fetchResearchWorkflowDefinition.mockResolvedValue({
      definition: makeCanvas("").definition,
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
    // flush microtasks from effects
    await act(async () => {
      await Promise.resolve();
    });
  }

  it("initial load of 3 events stays 3 not 6", async () => {
    const events = makeEvents(3);
    api.fetchResearchWorkflowRun.mockResolvedValue(makeRun("run-a", events));
    api.fetchResearchWorkflowCanvas.mockResolvedValue(makeCanvas("run-a"));
    await renderWith("run-a");
    expect(latest?.run?.events).toHaveLength(3);
    expect(latest?.lastSequence).toBe(3);
  });

  it("run switch resets sequence cursor for run B", async () => {
    api.fetchResearchWorkflowRun.mockImplementation(async (id: string) =>
      makeRun(id, id === "run-a" ? makeEvents(100).slice(99) : makeEvents(1)),
    );
    api.fetchResearchWorkflowCanvas.mockImplementation(async (id: string) => makeCanvas(id));

    await renderWith("run-a");
    expect(latest?.lastSequence).toBe(100);

    await renderWith("run-b");
    expect(latest?.run?.runId).toBe("run-b");
    expect(latest?.lastSequence).toBe(1);
  });

  it("slow previous run refresh does not overwrite new run", async () => {
    let resolveA: (v: WorkflowRunRecord) => void = () => {};
    api.fetchResearchWorkflowRun.mockImplementation((id: string) => {
      if (id === "run-a") {
        return new Promise<WorkflowRunRecord>((resolve) => {
          resolveA = resolve;
        });
      }
      return Promise.resolve(makeRun("run-b", makeEvents(1)));
    });
    api.fetchResearchWorkflowCanvas.mockImplementation(async (id: string) => makeCanvas(id));

    await act(async () => {
      root.render(
        <HookProbe runId="run-a" onValue={(v) => { latest = v; }} />,
      );
    });
    await act(async () => {
      root.render(
        <HookProbe runId="run-b" onValue={(v) => { latest = v; }} />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      resolveA(makeRun("run-a", makeEvents(5)));
      await Promise.resolve();
    });
    expect(latest?.run?.runId).toBe("run-b");
    expect(latest?.run?.events).toHaveLength(1);
  });
});
