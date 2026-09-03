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
import {
  createDeterministicWorkflowLayout,
  layoutDiagnostic,
  mergeRuntimeFields,
  useWorkflowAutoLayout,
} from "./useWorkflowAutoLayout";
import { toElkGraph } from "./workflowElkGraphAdapter";

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

export function makeGraph(stageIds: string[], overrides: Partial<WorkflowLayoutInput> = {}): WorkflowLayoutInput {
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

/**
 * Fake layout for the TWO-LEVEL pipeline:
 *  - stage subgraphs (id "stage:*", children = tasks) -> vertical column;
 *  - outer meta graph (id "workflow:root:outer", children = stage meta nodes
 *    + label spacers) -> simple RIGHT row with a fixed gap; every edge gets
 *    one fake section so the two-leg recombination still works.
 */
export function fakeLayout(graph: ElkNode): ElkNode {
  const isStageSubgraph = String(graph.id).startsWith("stage:");
  const isOuterGraph = String(graph.id).startsWith("workflow:root:outer");
  const taskNodes = (graph.children ?? []).map((task, ti) => ({
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
  }));
  const sectionedEdges = (edges: ElkNode["edges"]) =>
    (edges ?? []).map((edge, ei) => ({
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
  if (isStageSubgraph) {
    return { ...graph, children: taskNodes, edges: sectionedEdges(graph.edges) };
  }
  if (isOuterGraph) {
    // Simple RIGHT row: stages and spacers placed by width with a fixed gap.
    let cursor = 12;
    const children = (graph.children ?? []).map((node) => {
      const placed = { ...node, x: cursor, y: 12 };
      cursor += (node.width ?? 0) + 40;
      return placed;
    });
    // Every leg section must START/END at the stage gateway border, like the
    // real engine: leg1 runs from the source stage's EAST edge to the
    // midpoint, leg2 continues from the midpoint to the target stage's WEST
    // edge, so the composer's gateway stubs join geometrically.
    const portStage = new Map<string, string>();
    for (const child of children) {
      for (const port of child.ports ?? []) {
        portStage.set(String(port.id), String(child.id));
      }
    }
    const stageOfPort = (portId: string | undefined) => {
      const nodeId = portId ? portStage.get(portId) : undefined;
      return nodeId && !String(nodeId).startsWith("__label_spacer__")
        ? children.find((c) => String(c.id) === nodeId)
        : undefined;
    };
    const edges = (graph.edges ?? []).map((edge) => {
      const srcPort = String(edge.sources?.[0] ?? "");
      const tgtPort = String(edge.targets?.[0] ?? "");
      const isLeg1 = String(edge.id).includes("leg1");
      // The two legs of one domain edge must meet at the SAME point: the
      // spacer's center X (both legs touch the spacer's WEST/EAST ports).
      const spacerNodeId = portStage.get(isLeg1 ? tgtPort : srcPort);
      const spacerNode = children.find((c) => String(c.id) === spacerNodeId);
      const midX = (spacerNode?.x ?? 0) + (spacerNode?.width ?? 0) / 2;
      const srcRight = (stageOfPort(srcPort)?.x ?? 0) + (stageOfPort(srcPort)?.width ?? 0);
      const tgtLeft = stageOfPort(tgtPort)?.x ?? srcRight + 80;
      // One section per leg; consumeOuterLayout re-links leg1 end -> leg2
      // start at midX, so the chain stays continuous.
      return {
        ...edge,
        sections: [
          {
            id: `s-${edge.id}`,
            startPoint: { x: isLeg1 ? srcRight : midX, y: 40 },
            endPoint: { x: isLeg1 ? midX : tgtLeft, y: 40 },
            bendPoints: [],
            incomingSections: [],
            outgoingSections: [],
          },
        ],
        labels: edge.labels?.map((label) => ({ ...label, x: 50, y: 40 })) ?? [],
      };
    });
    return { ...graph, children, edges };
  }
  // Legacy compound shape (used by tests that still call toElkGraph): map
  // every stage to an absolute column; encode stage count into y.
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
  const stageEdges2 = (stageNodes as Array<ElkNode & { edges?: ElkNode["edges"] }>).map((stage) => ({
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
  return { ...graph, children: stageEdges2, edges: rootEdges(graph.edges ?? []) };
}

function rootEdges(edges: ElkNode["edges"]): ElkNode["edges"] {
  return (edges ?? []).map((edge) => ({
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
    // The two-level pipeline awaits one engine call per stage subgraph plus
    // one outer ELK call, serially; flush enough microtasks for the whole
    // round to commit.
    for (let i = 0; i < 20; i += 1) {
      await act(async () => {
        await Promise.resolve();
      });
    }
  }

  it("runs one two-level layout round on first layout and reports committed nodes/edges", async () => {
    const engine = makeEngine();
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);
    const fallback = createDeterministicWorkflowLayout(graph);
    await renderWith(graph, engine);

    // Two-level layout: one engine call per stage subgraph (meta row is
    // deterministic and engine-free).
    expect(engine.layout).toHaveBeenCalledTimes(3);
    expect(latest?.layoutRevision).toBe(1);
    expect(latest?.nodes).toHaveLength(4);
    expect(latest?.nodes.filter((node) => node.kind === "stage")).toHaveLength(2);
    expect(latest?.nodes.filter((node) => node.kind === "task")).toHaveLength(2);
    expect(latest?.edges).toHaveLength(1);
    expect(latest?.degraded).toBeNull();
    expect(latest?.nodes.find((node) => node.id === "knowledge_collection"))
      .not.toEqual(fallback.nodes.find((node) => node.id === "knowledge_collection"));
  });

  it("exposes every business node immediately while ELK is still pending", async () => {
    const engine = makeEngine();
    engine.layout.mockImplementation(() => new Promise<ElkNode>(() => {}));
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);

    await act(async () => {
      root.render(
        <HookProbe
          graph={graph}
          createEngine={() => engine}
          onValue={(value) => {
            latest = value;
          }}
        />,
      );
      await Promise.resolve();
    });

    expect(latest?.nodes.filter((node) => node.kind === "task").map((node) => node.id))
      .toEqual(["knowledge_collection", "experiment_design"]);
    expect(latest?.nodes.every((node) => [node.x, node.y, node.width, node.height].every(Number.isFinite)))
      .toBe(true);
  });

  it("keeps the deterministic fallback and marks degraded when ELK never resolves", async () => {
    vi.useFakeTimers();
    try {
      const engine = makeEngine();
      engine.layout.mockImplementation(() => new Promise<ElkNode>(() => {}));
      const graph = makeGraph(["knowledge_collection", "experiment_design"]);

      await act(async () => {
        root.render(
          <HookProbe
            graph={graph}
            createEngine={() => engine}
            onValue={(value) => {
              latest = value;
            }}
          />,
        );
        await Promise.resolve();
      });
      expect(latest?.degraded).toBeNull();

      await act(async () => {
        vi.advanceTimersByTime(3_001);
        await Promise.resolve();
      });

      expect(latest?.nodes).toHaveLength(4);
      expect(latest?.degraded?.reason).toContain("timed out");
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps the deterministic fallback when the first ELK run rejects", async () => {
    const engine = makeEngine();
    engine.layout.mockRejectedValue(new Error("layout engine unavailable"));
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);

    await act(async () => {
      root.render(
        <HookProbe
          graph={graph}
          createEngine={() => engine}
          onValue={(value) => {
            latest = value;
          }}
        />,
      );
      await Promise.resolve();
    });
    for (let i = 0; i < 20; i += 1) {
      await act(async () => {
        await Promise.resolve();
      });
    }

    expect(latest?.nodes.filter((node) => node.kind === "task")).toHaveLength(2);
    expect(latest?.degraded?.reason).toContain("layout engine unavailable");
  });

  it("rejects non-finite ELK geometry without dropping business nodes", async () => {
    const engine = makeEngine();
    engine.layout.mockImplementation(async (graph: ElkNode) => {
      const laidOut = fakeLayout(graph);
      const firstChild = laidOut.children?.[0];
      if (firstChild) firstChild.x = Number.NaN;
      return laidOut;
    });
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);

    await act(async () => {
      root.render(
        <HookProbe
          graph={graph}
          createEngine={() => engine}
          onValue={(value) => {
            latest = value;
          }}
        />,
      );
      await Promise.resolve();
    });
    for (let i = 0; i < 20; i += 1) {
      await act(async () => {
        await Promise.resolve();
      });
    }

    expect(latest?.nodes.filter((node) => node.kind === "task")).toHaveLength(2);
    expect(latest?.nodes.every((node) => [node.x, node.y, node.width, node.height].every(Number.isFinite)))
      .toBe(true);
    expect(latest?.degraded?.reason).toContain("non-finite");
  });

  it("builds a stable fallback from graph topology without changing membership", () => {
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);
    const first = createDeterministicWorkflowLayout(graph, "serpentine");
    const second = createDeterministicWorkflowLayout(graph, "serpentine");

    expect(first).toEqual(second);
    expect(first.nodes.filter((node) => node.kind === "task").map((node) => ({
      id: node.id,
      stageId: node.stageId,
    }))).toEqual(graph.nodes.map((node) => ({ id: node.nodeId, stageId: node.stageId })));
    expect(first.nodes.every((node) => [node.x, node.y, node.width, node.height].every(Number.isFinite)))
      .toBe(true);
  });

  it("does not re-run ELK for status-only updates", async () => {
    const engine = makeEngine();
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);
    await renderWith(graph, engine);
    expect(engine.layout).toHaveBeenCalledTimes(3);

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

    expect(engine.layout).toHaveBeenCalledTimes(3);
    expect(latest?.layoutRevision).toBe(1);
    // Nodes keep their geometry from the first layout (no re-run) but carry
    // the refreshed runtime fields.
    const liveTask = latest?.nodes.find(
      (node) => node.kind === "task" && node.id === "knowledge_collection",
    );
    expect(liveTask?.status).toBe("running");
    expect(latest?.edges[0].pathState).toBe("active");
  });

  it("keeps routine labels suppressed when serpentine runtime fields refresh", () => {
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);
    const layoutEdge = {
      id: "e1",
      source: "knowledge_collection",
      target: "experiment_design",
      label: "",
      semanticKind: "main" as const,
      pathState: "idle" as const,
      labelAlwaysVisible: false,
      sections: [],
    };

    const merged = mergeRuntimeFields(
      { nodes: [], edges: [layoutEdge] },
      {
        ...graph,
        edges: graph.edges.map((edge) => ({
          ...edge,
          label: "普通自动交接",
          pathState: "active" as const,
        })),
      },
      "serpentine",
    );

    expect(merged.edges[0].label).toBe("");
    expect(merged.edges[0].pathState).toBe("active");
  });

  it("refreshes Agent bindings without re-running ELK", async () => {
    const engine = makeEngine();
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);
    await renderWith(graph, engine);
    expect(engine.layout).toHaveBeenCalledTimes(3);

    const bindingOnly: WorkflowLayoutInput = {
      ...graph,
      nodes: graph.nodes.map((node, index) => ({
        ...node,
        primaryAgentId: index === 0 ? "agent-source-finder" : undefined,
      })),
    };
    await renderWith(bindingOnly, engine);

    expect(engine.layout).toHaveBeenCalledTimes(3);
    const boundTask = latest?.nodes.find(
      (node) => node.kind === "task" && node.id === "knowledge_collection",
    );
    expect(boundTask?.primaryAgentId).toBe("agent-source-finder");
  });

  it("re-runs ELK when topology changes and bumps layoutRevision", async () => {
    const engine = makeEngine();
    await renderWith(makeGraph(["knowledge_collection", "experiment_design"]), engine);
    expect(engine.layout).toHaveBeenCalledTimes(3);

    await renderWith(
      makeGraph(["knowledge_collection", "experiment_design", "execution_iteration"]),
      engine,
    );
    // 2 stage subgraphs on the first round + 3 on the second.
    expect(engine.layout).toHaveBeenCalledTimes(7);
    expect(latest?.layoutRevision).toBe(2);
    expect(latest?.nodes).toHaveLength(6);
    expect(latest?.nodes.filter((node) => node.kind === "stage")).toHaveLength(3);
  });

  it("re-runs ELK when a cross-stage edge label widens, but not for same-geometry text", async () => {
    const engine = makeEngine();
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);
    await renderWith(graph, engine);
    expect(engine.layout).toHaveBeenCalledTimes(3);
    const firstRevision = latest?.layoutRevision;

    // Label text grows: resolved geometry widens -> the outer spacer grows,
    // so the stage channel must relayout (regression: label geometry used to
    // be excluded from the layout hash).
    const widerLabel: WorkflowLayoutInput = {
      ...graph,
      edges: graph.edges.map((edge) => ({ ...edge, label: "知识包跨阶段正式交接" })),
    };
    await renderWith(widerLabel, engine);
    expect(engine.layout).toHaveBeenCalledTimes(6);
    expect(latest?.layoutRevision).toBe((firstRevision ?? 0) + 1);

    // Same-geometry text change (same character count): runtime-only merge,
    // no relayout, no extra ELK calls.
    const sameSizeText: WorkflowLayoutInput = {
      ...widerLabel,
      edges: widerLabel.edges.map((edge) => ({ ...edge, label: "阶段通道必须重新布局" })),
    };
    await renderWith(sameSizeText, engine);
    expect(engine.layout).toHaveBeenCalledTimes(6);
    expect(latest?.layoutRevision).toBe((firstRevision ?? 0) + 1);
  });

  it("re-runs ELK at most once for measured size calibration, then converges", async () => {
    const engine = makeEngine();
    await renderWith(makeGraph(["knowledge_collection", "experiment_design"]), engine);
    expect(engine.layout).toHaveBeenCalledTimes(3);
    const firstRevision = latest?.layoutRevision;

    // Canvas measures real rendered nodes and reports bigger sizes.
    await act(async () => {
      latest?.reportMeasuredSize("knowledge_collection", { width: 300, height: 120 });
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(engine.layout).toHaveBeenCalledTimes(6);
    expect(latest?.layoutRevision).toBe((firstRevision ?? 0) + 1);

    // Second measurement reports the same size -> hash unchanged, no re-run.
    await act(async () => {
      latest?.reportMeasuredSize("knowledge_collection", { width: 300, height: 120 });
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(engine.layout).toHaveBeenCalledTimes(6);
  });

  it("drops stale promises so a slow old run cannot overwrite a newer run", async () => {
    const engine = makeEngine();
    // Serial pipeline: the first stage call of each round is issued first and
    // BLOCKS the rest of the round until resolved. Resolving an old round's
    // first promise after a new round was requested must be dropped (token).
    const pendingCalls: Array<{ graph: ElkNode; resolve: (value: ElkNode) => void }> = [];
    let awaiting = false;
    engine.layout.mockImplementation(
      (graph: ElkNode) =>
        new Promise<ElkNode>((resolve) => {
          if (!awaiting) {
            awaiting = true;
            pendingCalls.push({ graph, resolve });
          } else {
            resolve(fakeLayout(graph));
          }
        }),
    );

    await renderWith(makeGraph(["knowledge_collection", "experiment_design"]), engine);
    // First round is blocked on its first stage promise; nothing committed.
    expect(pendingCalls).toHaveLength(1);
    expect(latest?.layoutRevision).toBe(0);

    // A new round is requested while the old one is still pending.
    awaiting = false;
    await renderWith(
      makeGraph(["knowledge_collection", "experiment_design", "execution_iteration"]),
      engine,
    );
    expect(pendingCalls).toHaveLength(2);

    // The old round's first promise resolves now — it must be dropped.
    await act(async () => {
      pendingCalls[0]!.resolve(fakeLayout(pendingCalls[0]!.graph));
      await Promise.resolve();
    });
    expect(latest?.layoutRevision).toBe(0);

    // The new round's first promise resolves: the whole round commits once.
    await act(async () => {
      pendingCalls[1]!.resolve(fakeLayout(pendingCalls[1]!.graph));
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
    engine.layout.mockRejectedValueOnce(new Error("layout engine crashed"));
    await renderWith(
      makeGraph(["knowledge_collection", "experiment_design", "execution_iteration"]),
      engine,
    );

    expect(latest?.degraded).not.toBeNull();
    expect(latest?.degraded?.reason).toContain("layout engine crashed");
    // The old topology is not a legal recovery scope for the new graph, so
    // the current graph's deterministic fallback stays visible instead.
    expect(latest?.nodes.filter((node) => node.kind === "task").map((node) => node.id))
      .toEqual(["knowledge_collection", "experiment_design", "execution_iteration"]);
    expect(latest?.nodes.every((node) => [node.x, node.y, node.width, node.height].every(Number.isFinite)))
      .toBe(true);
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

  it("flags a label without engine bounds as degraded (P1-5)", () => {
    const result = {
      nodes: [],
      edges: [
        {
          id: "e1",
          source: "a",
          target: "b",
          label: "交接",
          semanticKind: "main" as const,
          pathState: "idle" as const,
          labelAlwaysVisible: false,
          sections: [],
          labelBounds: undefined,
        },
      ],
      width: 0,
      height: 0,
    };
    const diagnostic = layoutDiagnostic(result);
    expect(diagnostic).not.toBeNull();
    expect(diagnostic?.reason).toContain('edge "e1" has a label but the engine did not place label bounds');
  });

  it("flags a non-well-formed section chain as degraded (P1-5)", () => {
    const result = {
      nodes: [],
      edges: [
        {
          id: "e2",
          source: "a",
          target: "b",
          label: "回路",
          semanticKind: "rerun" as const,
          pathState: "idle" as const,
          labelAlwaysVisible: true,
          sections: [
            { id: "s1", start: { x: 0, y: 0 }, end: { x: 10, y: 0 }, bendPoints: [], incomingSectionIds: [], outgoingSectionIds: ["s2"] },
            { id: "s2", start: { x: 11, y: 5 }, end: { x: 20, y: 5 }, bendPoints: [], incomingSectionIds: ["s1"], outgoingSectionIds: [] },
          ],
          labelBounds: { x: 0, y: 0, width: 10, height: 10 },
        },
      ],
      width: 0,
      height: 0,
    };
    const diagnostic = layoutDiagnostic(result);
    expect(diagnostic).not.toBeNull();
    expect(diagnostic?.reason).toContain('edge "e2" section chain is not well-formed');
  });

  it("rejects a layout that keeps every node but drops the business edges", () => {
    const graph = makeGraph(["knowledge_collection", "experiment_design"]);
    const complete = createDeterministicWorkflowLayout(graph, "serpentine");

    const diagnostic = layoutDiagnostic({ ...complete, edges: [] }, graph);

    expect(diagnostic?.reason).toContain("business edges");
  });

  it("stays clean when every label has bounds and chains are well-formed (P1-5)", () => {
    const result = {
      nodes: [],
      edges: [
        {
          id: "e3",
          source: "a",
          target: "b",
          label: "主流程",
          semanticKind: "main" as const,
          pathState: "idle" as const,
          labelAlwaysVisible: false,
          sections: [
            { id: "s1", start: { x: 0, y: 0 }, end: { x: 10, y: 0 }, bendPoints: [], incomingSectionIds: [], outgoingSectionIds: [] },
          ],
          labelBounds: { x: 0, y: 0, width: 10, height: 10 },
        },
      ],
      width: 0,
      height: 0,
    };
    expect(layoutDiagnostic(result)).toBeNull();
  });
});
