/**
 * Behavioral tests for useWorkflowAutoLayout (layout design §6.2/§6.3, §9.4).
 *
 * Covers: hash reuse (zero extra ELK calls on status-only updates), relayout
 * on topology change, at-most-one size calibration relayout, stale promise
 * dropping, engine terminate on unmount (incl. StrictMode remount), initial
 * fit exactly once, last-good + degraded on failure.
 *
 * @vitest-environment happy-dom
 */
import React, { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ElkNode } from "elkjs/lib/elk-api";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import type {
  WorkflowCanvasEdgeInput,
  WorkflowCanvasNodeInput,
  WorkflowCanvasStageInput,
  WorkflowLayoutInput,
} from "../../../product/workflow/workflowCanvasTypes";
import type { WorkflowLayoutEngine } from "./workflowElkClient";
import { useWorkflowAutoLayout } from "./useWorkflowAutoLayout";

function makeNode(overrides: Partial<WorkflowCanvasNodeInput>): WorkflowCanvasNodeInput {
  return {
    nodeId: "knowledge_collection",
    stageId: "knowledge_collection",
    label: "文献调研",
    actorKind: "agent",
    visualKind: "agent_task",
    status: "pending",
    ...overrides,
  };
}

function makeEdge(overrides: Partial<WorkflowCanvasEdgeInput>): WorkflowCanvasEdgeInput {
  return {
    edgeId: "e1",
    fromNodeId: "knowledge_collection",
    toNodeId: "experiment_design",
    label: "交接",
    gateKind: "auto",
    semanticKind: "main",
    pathState: "idle",
    labelAlwaysVisible: false,
    ...overrides,
  };
}

function makeGraph(stageIds: string[], overrides: Partial<WorkflowLayoutInput> = {}): WorkflowLayoutInput {
  const stages: WorkflowCanvasStageInput[] = stageIds.map((stageId, index) => ({
    stageId,
    label: `stage-${index}`,
    nodeIds: stageIds.length > 1 ? [stageId] : [],
  }));
  const nodes: WorkflowCanvasNodeInput[] = stageIds.map((stageId) =>
    makeNode({ nodeId: stageId, stageId }),
  );
  const edges: WorkflowCanvasEdgeInput[] =
    stageIds.length > 1 ? [makeEdge({ fromNodeId: stageIds[0], toNodeId: stageIds[1] })] : [];
  return { stages, nodes, edges, run: null, ...overrides };
}

/** Fake layout: maps every stage to an absolute column; encodes stage count into y. */
function fakeLayout(graph: ElkNode): ElkNode {
  const stageNodes = (graph.children ?? []).map((stage, si) => ({
    ...stage,
    x: si * 400,
    y: 0,
    width: 350,
    height: 250,
    children: (stage.children ?? []).map((task, ti) => ({
      ...task,
      x: 12,
      y: 56 + ti * 110,
      width: task.width ?? 248,
      height: task.height ?? 88,
      labels:
        task.labels?.map((label) => ({
          ...label,
          x: 12,
          y: 56,
          width: label.width ?? 100,
          height: label.height ?? 20,
        })) ?? [],
    })),
  }));
  const rootEdges = (graph.edges ?? []).map((edge, ei) => ({
    ...edge,
    sections: [
      {
        id: `s-${edge.id}`,
        startPoint: { x: 0, y: 0 },
        endPoint: { x: 100, y: 100 },
        bendPoints: [],
        incomingSections: [],
        outgoingSections: [],
      },
    ],
    labels: edge.labels?.map((label) => ({ ...label, x: 50, y: 50 })) ?? [],
  }));
  const stageEdges = (stageNodes as Array<ElkNode & { edges?: ElkNode["edges"] }>).map((stage) => ({
    ...stage,
    edges:
      ((stage.edges ?? []) as Array<ElkNode["edges"][number]>).map((edge, ei) => ({
        ...edge,
        sections: [
          {
            id: `s-${edge.id}`,
            startPoint: { x: 0, y: 0 },
            endPoint: { x: 100, y: 100 },
            bendPoints: [],
            incomingSections: [],
            outgoingSections: [],
          },
        ],
        labels: edge.labels?.map((label) => ({ ...label, x: 50, y: 50 })) ?? [],
      })) ?? [],
  }));
  return { ...graph, children: stageEdges, edges: rootEdges };
}

function makeEngine() {
  const layout = vi.fn(async (graph: ElkNode) => fakeLayout(graph));
  const terminate = vi.fn();
  return { layout, terminate } satisfies WorkflowLayoutEngine;
}

type HookValue = ReturnType<typeof useWorkflowAutoLayout>;

function HookProbe({
  graph,
  createEngine,
  onValue,
  onFitCommitted,
}: {
  graph: WorkflowLayoutInput;
  createEngine: () => WorkflowLayoutEngine;
  onValue: (v: HookValue) => void;
  onFitCommitted?: () => void;
}) {
  const value = useWorkflowAutoLayout(graph, createEngine);
  useEffect(() => {
    onValue(value);
  }, [value, onValue]);
  // Canvas-side initial fit consumer: fits only while the initial fit
  // revision is outstanding and the committed layout is the current one.
  useEffect(() => {
    if (value.initialFitRevision === null || value.initialFitRevision !== value.layoutRevision) {
      return;
    }
    onFitCommitted?.();
    value.acknowledgeInitialFit();
  }, [value, onFitCommitted]);
  return null;
}

describe("useWorkflowAutoLayout behavior", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: HookValue | null = null;

  beforeEach(() => {
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

  async function renderWith(graph: WorkflowLayoutInput, engine: WorkflowLayoutEngine) {
    await act(async () => {
      root.render(
        <HookProbe
          graph={graph}
          createEngine={() => engine}
          onValue={(v) => {
            latest = v;
          }}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });
  }

  it("runs ELK once on first layout and reports committed nodes/edges", async () => {
    const engine = makeEngine();
    await renderWith(makeGraph(["knowledge_collection", "experiment_design"]), engine);

    expect(engine.layout).toHaveBeenCalledTimes(1);
    expect(latest?.layoutRevision).toBe(1);
    expect(latest?.nodes).toHaveLength(4);
    expect(latest?.nodes.filter((node) => node.kind === "stage")).toHaveLength(2);
    expect(latest?.nodes.filter((node) => node.kind === "task")).toHaveLength(2);
    expect(latest?.edges).toHaveLength(1);
    expect(latest?.degraded).toBeNull();
  });

  it("does not re-run ELK for status-only updates", async () => {
    const engine = makeEngine();
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);
    await renderWith(graph, engine);
    expect(engine.layout).toHaveBeenCalledTimes(1);

    const statusOnly: WorkflowLayoutInput = {
      ...graph,
      nodes: graph.nodes.map((node, index) => ({
        ...node,
        status: index === 0 ? "running" : "succeeded",
        isRuntimeCurrent: index === 0,
      })),
      edges: graph.edges.map((edge) => ({ ...edge, pathState: "active" })),
    };
    await renderWith(statusOnly, engine);

    expect(engine.layout).toHaveBeenCalledTimes(1);
    expect(latest?.layoutRevision).toBe(1);
    // Nodes keep their geometry from the first layout (no re-run) but carry
    // the refreshed runtime fields.
    const liveTask = latest?.nodes.find(
      (node) => node.kind === "task" && node.id === "knowledge_collection",
    );
    expect(liveTask?.status).toBe("running");
    expect(latest?.edges[0].pathState).toBe("active");
  });

  it("re-runs ELK when topology changes and bumps layoutRevision", async () => {
    const engine = makeEngine();
    await renderWith(makeGraph(["knowledge_collection", "experiment_design"]), engine);
    expect(engine.layout).toHaveBeenCalledTimes(1);

    await renderWith(
      makeGraph(["knowledge_collection", "experiment_design", "execution_iteration"]),
      engine,
    );
    expect(engine.layout).toHaveBeenCalledTimes(2);
    expect(latest?.layoutRevision).toBe(2);
    expect(latest?.nodes).toHaveLength(6);
    expect(latest?.nodes.filter((node) => node.kind === "stage")).toHaveLength(3);
  });

  it("re-runs ELK at most once for measured size calibration, then converges", async () => {
    const engine = makeEngine();
    await renderWith(makeGraph(["knowledge_collection", "experiment_design"]), engine);
    expect(engine.layout).toHaveBeenCalledTimes(1);
    const firstRevision = latest?.layoutRevision;

    // Canvas measures real rendered nodes and reports bigger sizes.
    await act(async () => {
      latest?.reportMeasuredSize("knowledge_collection", { width: 300, height: 120 });
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(engine.layout).toHaveBeenCalledTimes(2);
    expect(latest?.layoutRevision).toBe((firstRevision ?? 0) + 1);

    // Second measurement reports the same size -> hash unchanged, no re-run.
    await act(async () => {
      latest?.reportMeasuredSize("knowledge_collection", { width: 300, height: 120 });
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(engine.layout).toHaveBeenCalledTimes(2);
  });

  it("drops stale promises so a slow old run cannot overwrite a newer run", async () => {
    const engine = makeEngine();
    const resolvers: Array<(value: ElkNode) => void> = [];
    engine.layout.mockImplementation(
      (graph: ElkNode) =>
        new Promise<ElkNode>((resolve) => {
          resolvers.push(resolve);
          // Resolved later by the test with a synthetic layout.
          void graph;
        }),
    );

    await renderWith(makeGraph(["knowledge_collection", "experiment_design"]), engine);
    expect(resolvers).toHaveLength(1);

    await renderWith(
      makeGraph(["knowledge_collection", "experiment_design", "execution_iteration"]),
      engine,
    );
    expect(resolvers).toHaveLength(2);

    // Old run resolves AFTER the new run was requested: must be dropped.
    // Neither layout committed yet, so the revision stays at 0.
    const staleGraph = fakeLayout({
      id: "workflow:root",
      children: [
        {
          id: "stage:knowledge_collection",
          width: 400,
          height: 400,
          children: [],
          layoutOptions: {},
        },
      ],
    });
    await act(async () => {
      resolvers[0](staleGraph);
      await Promise.resolve();
    });
    expect(latest?.layoutRevision).toBe(0);

    const freshGraph = fakeLayout({
      id: "workflow:root",
      children: [
        {
          id: "stage:knowledge_collection",
          width: 400,
          height: 400,
          children: [],
          layoutOptions: {},
        },
        {
          id: "stage:experiment_design",
          width: 400,
          height: 400,
          children: [],
          layoutOptions: {},
        },
        {
          id: "stage:execution_iteration",
          width: 400,
          height: 400,
          children: [],
          layoutOptions: {},
        },
      ],
    });
    await act(async () => {
      resolvers[1](freshGraph);
      await Promise.resolve();
    });
    expect(latest?.layoutRevision).toBe(1);
    expect(latest?.nodes.filter((node) => node.kind === "stage")).toHaveLength(3);
  });

  it("terminates the engine on unmount", async () => {
    const engine = makeEngine();
    await renderWith(makeGraph(["knowledge_collection", "experiment_design"]), engine);
    expect(engine.terminate).not.toHaveBeenCalled();

    await act(async () => {
      root.unmount();
    });
    expect(engine.terminate).toHaveBeenCalledTimes(1);
  });

  it("StrictMode remount creates a fresh engine and leaves no orphan worker", async () => {
    const engines: WorkflowLayoutEngine[] = [];
    const createEngine = () => {
      const engine = makeEngine();
      engines.push(engine);
      return engine;
    };

    function StrictHookProbe({ graph }: { graph: WorkflowLayoutInput }) {
      const value = useWorkflowAutoLayout(graph, createEngine);
      useEffect(() => {
        onValue(value);
      });
      return null;
    }
    let onValue = (v: HookValue) => {
      latest = v;
    };

    // Simulate React StrictMode double-effect: mount -> unmount -> remount.
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);
    await act(async () => {
      root.render(<StrictHookProbe graph={graph} />);
    });
    await act(async () => {
      root.unmount();
    });
    expect(engines).toHaveLength(1);
    expect(engines[0].terminate).toHaveBeenCalledTimes(1);

    const remountRoot = createRoot(container);
    try {
      await act(async () => {
        remountRoot.render(<StrictHookProbe graph={graph} />);
      });
      await act(async () => {
        await Promise.resolve();
      });
      expect(engines).toHaveLength(2);
      expect(engines[1].terminate).not.toHaveBeenCalled();
      expect(latest?.layoutRevision).toBeGreaterThanOrEqual(1);
    } finally {
      await act(async () => {
        remountRoot.unmount();
      });
    }
  });

  it("fits exactly once on the initial layout, not on updates", async () => {
    const engine = makeEngine();
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);
    const fitCommitted = vi.fn();
    await act(async () => {
      root.render(
        <HookProbe
          graph={graph}
          createEngine={() => engine}
          onValue={(v) => {
            latest = v;
          }}
          onFitCommitted={fitCommitted}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      await Promise.resolve();
    });

    // The initial fit revision was set exactly once; the canvas consumer
    // fitted and acknowledged it.
    expect(latest?.initialFitRevision).toBeNull();
    expect(fitCommitted).toHaveBeenCalledTimes(1);

    // Status-only update: no new fit.
    const statusOnly: WorkflowLayoutInput = {
      ...graph,
      nodes: graph.nodes.map((node) => ({ ...node, status: "succeeded" })),
      edges: graph.edges.map((edge) => ({ ...edge, pathState: "traversed" })),
    };
    await act(async () => {
      root.render(
        <HookProbe
          graph={statusOnly}
          createEngine={() => engine}
          onValue={(v) => {
            latest = v;
          }}
          onFitCommitted={fitCommitted}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(fitCommitted).toHaveBeenCalledTimes(1);

    // Topology change: layout runs, but no automatic fit (only explicit fitAll).
    await act(async () => {
      root.render(
        <HookProbe
          graph={makeGraph(["knowledge_collection", "experiment_design", "execution_iteration"])}
          createEngine={() => engine}
          onValue={(v) => {
            latest = v;
          }}
          onFitCommitted={fitCommitted}
        />,
      );
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(fitCommitted).toHaveBeenCalledTimes(1);
    expect(latest?.layoutRevision).toBe(2);
  });

  it("exposes fitAll for explicit controls without auto-fitting", async () => {
    const engine = makeEngine();
    const fitView = vi.fn();
    const fitAllDelegates: Array<() => void> = [];

    function FitProbe({ graph }: { graph: WorkflowLayoutInput }) {
      const value = useWorkflowAutoLayout(graph, () => engine, { fitAll: fitView });
      useEffect(() => {
        latest = value;
        fitAllDelegates.push(value.fitAll);
      });
      return null;
    }

    await act(async () => {
      root.render(<FitProbe graph={makeGraph(["knowledge_collection", "experiment_design"])} />);
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(fitView).not.toHaveBeenCalled();

    await act(async () => {
      fitAllDelegates[fitAllDelegates.length - 1]();
    });
    expect(fitView).toHaveBeenCalledTimes(1);
  });

  it("keeps last-good layout and flags degraded when a layout fails", async () => {
    const engine = makeEngine();
    await renderWith(makeGraph(["knowledge_collection", "experiment_design"]), engine);
    expect(latest?.layoutRevision).toBe(1);
    const goodNodes = latest?.nodes;

    engine.layout.mockRejectedValueOnce(new Error("layout engine crashed"));
    await renderWith(
      makeGraph(["knowledge_collection", "experiment_design", "execution_iteration"]),
      engine,
    );

    expect(latest?.degraded).not.toBeNull();
    expect(latest?.degraded?.reason).toContain("layout engine crashed");
    // last-good nodes stay committed.
    expect(latest?.nodes).toEqual(goodNodes);
    expect(latest?.layoutRevision).toBe(1);

    // Next successful run clears degraded.
    await renderWith(
      makeGraph(["knowledge_collection", "experiment_design", "execution_iteration"]),
      engine,
    );
    expect(latest?.degraded).toBeNull();
    expect(latest?.layoutRevision).toBe(2);
  });

  it("derives decision capability ids without fabricating revise edges", async () => {
    const engine = makeEngine();
    const graph: WorkflowLayoutInput = {
      stages: [
        { stageId: "execution_iteration", label: "执行", nodeIds: ["controlled_run", "iteration_decision"] },
      ],
      nodes: [
        makeNode({ nodeId: "controlled_run", stageId: "execution_iteration" }),
        makeNode({
          nodeId: "iteration_decision",
          stageId: "execution_iteration",
          visualKind: "decision",
        }),
      ],
      edges: [
        makeEdge({
          edgeId: "e_rerun",
          fromNodeId: "iteration_decision",
          toNodeId: "controlled_run",
          semanticKind: "rerun",
          sourceHandle: "rerun",
          labelAlwaysVisible: true,
        }),
      ],
      run: null,
    };
    await renderWith(graph, engine);

    const decision = latest?.nodes.find((node) => node.id === "iteration_decision");
    expect(decision?.decisionOutcomeIds).toEqual(["rerun", "revise", "promote", "rollback", "stop"]);
    // Only the real current-run edge exists; revise has no edge.
    expect(latest?.edges).toHaveLength(1);
    expect(latest?.edges[0].sourceHandle).toBe("rerun");
  });
});
