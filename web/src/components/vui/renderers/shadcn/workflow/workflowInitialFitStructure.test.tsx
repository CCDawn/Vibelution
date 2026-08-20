/**
 * P1-1 structure contracts (M level, no DOM measurement).
 *
 * Mocks @xyflow/react so <ReactFlow> becomes a props-recording stub; asserts:
 *  - the canvas no longer passes implicit `fitView` / `fitViewOptions`;
 *  - the canvas still wires WorkflowCanvasControls with onFitAll (explicit);
 *  - WorkflowCanvasControls renders standalone against a fake instance and
 *    prefers the injected onFitAll over a React Flow fallback.
 *
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const rfCalls: Array<Record<string, unknown>> = vi.hoisted(() => []);
const fakeInstance = vi.hoisted(() => ({
  fitView: vi.fn(),
  zoomIn: vi.fn(),
  zoomOut: vi.fn(),
  setCenter: vi.fn(),
  getNode: vi.fn(() => null),
}));

vi.mock("@xyflow/react", () => ({
  ReactFlowProvider: ({ children }: { children: unknown }) => children,
  useReactFlow: () => fakeInstance,
  useNodesInitialized: () => true,
  Background: () => null,
  MiniMap: () => null,
  MarkerType: { ArrowClosed: "arrowclosed" },
  ConnectionLineType: { Step: "step", SmoothStep: "smoothstep", Bezier: "default", Straight: "straight" },
  useViewport: () => ({ x: 0, y: 0, zoom: 1 }),
  ReactFlow: (props: Record<string, unknown>) => {
    rfCalls.push(props);
    return null;
  },
}));

import type { WorkflowLayoutInput, WorkflowLayoutNode } from "../../../product/workflow/workflowCanvasTypes";
import { WorkflowCanvasControls } from "./WorkflowCanvasControls";
import { ShadcnWorkflowCanvas } from "./ShadcnWorkflowCanvas";
import { WorkflowOrthogonalConnectionLine } from "./WorkflowOrthogonalConnectionLine";
import { WORKFLOW_MANUAL_LAYOUT_GRID } from "./workflowManualLayout";
import { useWorkflowAutoLayout } from "./useWorkflowAutoLayout";
import { useWorkflowInitialFit } from "./useWorkflowInitialFit";

vi.mock("./useWorkflowAutoLayout", () => ({
  useWorkflowAutoLayout: vi.fn(() => ({
    nodes: [],
    edges: [],
    layoutRevision: 1,
    degraded: null,
    initialFitRevision: null,
    structureKey: "structure:empty",
    acknowledgeInitialFit: vi.fn(),
    fitAll: vi.fn(),
    reportMeasuredSize: vi.fn(),
  })),
}));

vi.mock("./useWorkflowInitialFit", () => ({
  useWorkflowInitialFit: () => ({ pendingInitialFit: false }),
}));

function emptyGraph(): WorkflowLayoutInput {
  return { stages: [], nodes: [], edges: [], run: null };
}

function sampleLayoutNodes(): WorkflowLayoutNode[] {
  return [
    {
      id: "stage:experiment",
      stageId: "experiment",
      label: "实验设计",
      actorKind: "system",
      visualKind: "stage_region",
      kind: "stage",
      x: 0,
      y: 0,
      width: 240,
      height: 32,
      stageTone: "idle",
    },
    {
      id: "protocol_design",
      stageId: "experiment",
      label: "协议设计",
      actorKind: "agent",
      visualKind: "agent_task",
      kind: "task",
      x: 40,
      y: 80,
      width: 300,
      height: 72,
      status: "pending",
    },
  ];
}

function sampleGraph(): WorkflowLayoutInput {
  return {
    stages: [{ stageId: "experiment", label: "实验设计", nodeIds: ["protocol_design"] }],
    nodes: [{
      nodeId: "protocol_design",
      stageId: "experiment",
      label: "协议设计",
      actorKind: "agent",
      visualKind: "agent_task",
      status: "pending",
    }],
    edges: [],
    run: null,
  };
}

function idleLayoutHook(nodes: WorkflowLayoutNode[] = []) {
  return {
    nodes,
    edges: [],
    layoutRevision: 1,
    degraded: null,
    initialFitRevision: null,
    structureKey: "structure:empty",
    acknowledgeInitialFit: vi.fn(),
    fitAll: vi.fn(),
    reportMeasuredSize: vi.fn(),
  };
}

describe("ShadcnWorkflowCanvas structure (P1-1)", () => {
  beforeEach(() => {
    vi.stubGlobal("ResizeObserver", class {
      observe() {}
      disconnect() {}
      unobserve() {}
    });
  });

  afterEach(() => {
    rfCalls.length = 0;
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("does not pass implicit fitView / fitViewOptions to ReactFlow", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    await act(async () => {
      root.render(<ShadcnWorkflowCanvas graph={emptyGraph()} />);
    });
    await act(async () => {
      root.unmount();
      container.remove();
    });

    const rfProps = rfCalls[0];
    expect(rfProps).toBeDefined();
    expect(rfProps.fitView).toBeUndefined();
    expect(rfProps.fitViewOptions).toBeUndefined();
    expect(typeof rfProps.onMoveStart).toBe("function");
  });

  it("wires WorkflowCanvasControls with an explicit onFitAll (not implicit fitView)", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    await act(async () => {
      root.render(<ShadcnWorkflowCanvas graph={emptyGraph()} />);
    });
    await act(async () => {
      root.unmount();
      container.remove();
    });

    const rfProps = rfCalls[0];
    const controlsElement = (Array.isArray(rfProps.children) ? rfProps.children : [rfProps.children]).find(
      (child: React.ReactElement) => child.type === WorkflowCanvasControls,
    );
    expect(controlsElement).toBeDefined();
    expect(typeof controlsElement.props.onFitAll).toBe("function");
  });

  it("enables the approved 16px manual-layout controls only for serpentine canvases", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    await act(async () => {
      root.render(<ShadcnWorkflowCanvas graph={emptyGraph()} layoutMode="serpentine" />);
    });

    const rfProps = rfCalls[0];
    expect(rfProps.nodesDraggable).toBe(true);
    expect(rfProps.snapToGrid).toBe(false);
    const backgroundElement = (Array.isArray(rfProps.children) ? rfProps.children : [rfProps.children]).find(
      (child: React.ReactElement) => child?.props?.gap != null,
    );
    expect(backgroundElement.props.gap).toBe(WORKFLOW_MANUAL_LAYOUT_GRID);
    expect(rfProps.edgesReconnectable).toBe(true);
    expect(rfProps.connectionLineType).toBe("step");
    expect(rfProps.connectionLineComponent).toBe(WorkflowOrthogonalConnectionLine);
    expect(rfProps.nodesConnectable).toBe(false);
    expect(typeof rfProps.onReconnect).toBe("function");
    expect(typeof rfProps.isValidConnection).toBe("function");
    expect(rfProps.isValidConnection({
      source: "protocol",
      target: "review",
      sourceHandle: null,
      targetHandle: "workflow-snap:SOUTH:0.5000",
    })).toBe(false);
    const controlsElement = (Array.isArray(rfProps.children) ? rfProps.children : [rfProps.children]).find(
      (child: React.ReactElement) => child.type === WorkflowCanvasControls,
    );
    expect(controlsElement.props.manualLayout).toEqual(expect.objectContaining({
      canUndo: false,
      locked: false,
    }));

    await act(async () => {
      root.unmount();
      container.remove();
    });
  });

  it("does not paint serpentine stage labels as React Flow nodes", async () => {
    vi.mocked(useWorkflowAutoLayout).mockReturnValue(idleLayoutHook(sampleLayoutNodes()));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    await act(async () => {
      root.render(<ShadcnWorkflowCanvas graph={sampleGraph()} layoutMode="serpentine" />);
    });

    const rfProps = rfCalls[0];
    const nodes = rfProps.nodes as Array<{ id: string; type?: string }>;
    expect(nodes.map((node) => node.id)).toEqual(["protocol_design"]);
    expect(nodes.some((node) => node.type === "stageRegion")).toBe(false);

    await act(async () => {
      root.unmount();
      container.remove();
    });
    vi.mocked(useWorkflowAutoLayout).mockReturnValue(idleLayoutHook());
  });

  it("still paints stage-columns region nodes", async () => {
    vi.mocked(useWorkflowAutoLayout).mockReturnValue(idleLayoutHook(sampleLayoutNodes()));
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    await act(async () => {
      root.render(<ShadcnWorkflowCanvas graph={sampleGraph()} layoutMode="stage-columns" />);
    });

    const rfProps = rfCalls[0];
    const nodes = rfProps.nodes as Array<{ id: string; type?: string }>;
    expect(nodes.map((node) => ({ id: node.id, type: node.type }))).toEqual([
      { id: "stage:experiment", type: "stageRegion" },
      { id: "protocol_design", type: "agentTask" },
    ]);
    const backgroundElement = (Array.isArray(rfProps.children) ? rfProps.children : [rfProps.children]).find(
      (child: React.ReactElement) => child?.props?.gap != null,
    );
    expect(backgroundElement.props.gap).toBe(20);

    await act(async () => {
      root.unmount();
      container.remove();
    });
    vi.mocked(useWorkflowAutoLayout).mockReturnValue(idleLayoutHook());
  });

  it("deletes the legacy fitView-only control wiring so onFitAll is the single explicit path", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    await act(async () => {
      root.render(<ShadcnWorkflowCanvas graph={emptyGraph()} />);
    });
    await act(async () => {
      root.unmount();
      container.remove();
    });

    // No props on the React Flow stub represent an implicit-fit escape hatch.
    for (const props of rfCalls) {
      expect(props.fitView).toBeUndefined();
      expect(props.fitViewOptions).toBeUndefined();
    }
  });

  it("selects a task directly from the React Flow node click", async () => {
    const onSelectNode = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    await act(async () => {
      root.render(<ShadcnWorkflowCanvas graph={emptyGraph()} onSelectNode={onSelectNode} />);
    });

    const rfProps = rfCalls[0];
    expect(typeof rfProps.onNodeClick).toBe("function");
    (rfProps.onNodeClick as (event: unknown, node: { id: string }) => void)(
      {},
      { id: "source_extraction" },
    );
    expect(onSelectNode).toHaveBeenCalledWith("source_extraction");

    await act(async () => {
      root.unmount();
      container.remove();
    });
  });

  it("does not expose React Flow selection-change callbacks that can replay stale nodes", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    await act(async () => {
      root.render(<ShadcnWorkflowCanvas graph={emptyGraph()} selectedNodeId="source_extraction" />);
    });

    expect(rfCalls[0].onSelectionChange).toBeUndefined();

    await act(async () => {
      root.unmount();
      container.remove();
    });
  });

  it("shows a degraded banner when the layout hook reports a failure (P1-5)", async () => {
    vi.mocked(useWorkflowAutoLayout).mockReturnValue({
      nodes: [],
      edges: [],
      layoutRevision: 1,
      degraded: { reason: "layout engine crashed" },
      initialFitRevision: null,
      structureKey: "structure:empty",
      acknowledgeInitialFit: vi.fn(),
      fitAll: vi.fn(),
      reportMeasuredSize: vi.fn(),
    });
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    await act(async () => {
      root.render(<ShadcnWorkflowCanvas graph={emptyGraph()} />);
    });

    const banner = container.querySelector('[data-vui="workflow-degraded"]');
    expect(banner).toBeTruthy();
    expect(banner?.textContent).toContain("布局降级");
    expect(banner?.textContent).toContain("layout engine crashed");

    await act(async () => {
      root.unmount();
      container.remove();
    });
    vi.mocked(useWorkflowAutoLayout).mockReturnValue({
      nodes: [],
      edges: [],
      layoutRevision: 1,
      degraded: null,
      initialFitRevision: null,
      structureKey: "structure:empty",
      acknowledgeInitialFit: vi.fn(),
      fitAll: vi.fn(),
      reportMeasuredSize: vi.fn(),
    });
  });
});

describe("WorkflowCanvasControls standalone (P1-1)", () => {
  it("prefers the injected onFitAll over the React Flow instance fallback", async () => {
    const onFitAll = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);
    await act(async () => {
      root.render(<WorkflowCanvasControls onFitAll={onFitAll} />);
    });

    const fitAllButton = container.querySelector('[aria-label="适应全部"]');
    expect(fitAllButton).toBeTruthy();
    await act(async () => {
      (fitAllButton as HTMLButtonElement).click();
    });
    await act(async () => {
      root.unmount();
      container.remove();
    });

    expect(onFitAll).toHaveBeenCalledTimes(1);
    expect(fakeInstance.fitView).not.toHaveBeenCalled();
  });
});
