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
import { afterEach, describe, expect, it, vi } from "vitest";

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
  MarkerType: { ArrowClosed: "arrowclosed" },
  ReactFlow: (props: Record<string, unknown>) => {
    rfCalls.push(props);
    return null;
  },
}));

import type { WorkflowLayoutInput } from "../../../product/workflow/workflowCanvasTypes";
import { WorkflowCanvasControls } from "./WorkflowCanvasControls";
import { ShadcnWorkflowCanvas } from "./ShadcnWorkflowCanvas";
import { useWorkflowAutoLayout } from "./useWorkflowAutoLayout";
import { useWorkflowInitialFit } from "./useWorkflowInitialFit";

vi.mock("./useWorkflowAutoLayout", () => ({
  useWorkflowAutoLayout: vi.fn(() => ({
    nodes: [],
    edges: [],
    layoutRevision: 1,
    degraded: null,
    initialFitRevision: null,
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

describe("ShadcnWorkflowCanvas structure (P1-1)", () => {
  afterEach(() => {
    rfCalls.length = 0;
    vi.clearAllMocks();
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

  it("shows a degraded banner when the layout hook reports a failure (P1-5)", async () => {
    vi.mocked(useWorkflowAutoLayout).mockReturnValue({
      nodes: [],
      edges: [],
      layoutRevision: 1,
      degraded: { reason: "layout engine crashed" },
      initialFitRevision: null,
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
