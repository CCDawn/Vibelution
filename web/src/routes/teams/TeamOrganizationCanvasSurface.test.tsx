/** @vitest-environment happy-dom */
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import styles from "../TeamsRoute.styles";
import { CANVAS_MAX_ZOOM, canvasStyleScale, canvasViewStyle, NODE_WIDTH, type CanvasViewportStyle } from "./canvasGeometry";
import { TeamOrganizationCanvasSurface, type TeamOrganizationCanvasSurfaceProps } from "./TeamOrganizationCanvasSurface";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const nodes: TeamCanvasNode[] = [
  { id: "a", type: "role", label: "Lead", role: "lead", purpose: "", agentId: "", agentCode: "", agentName: "", x: 100, y: 100, status: "ready" },
  { id: "b", type: "role", label: "Member", role: "member", purpose: "", agentId: "", agentCode: "", agentName: "", x: 1800, y: 900, status: "ready" },
];
const frame = { width: 280, height: 240 };
const canvas: TeamOrganizationCanvas = {
  schemaVersion: 1, canvasKind: "team_organization_canvas", teamId: "team", updatedAt: "", path: "",
  viewport: { x: 0, y: 0, zoom: 1 }, nodes,
  edges: [{ id: "edge", source: "a", target: "b", type: "reports_to", label: "" }],
};
const noop = () => undefined;

function surfaceProps(overrides: Partial<TeamOrganizationCanvasSurfaceProps> = {}): TeamOrganizationCanvasSurfaceProps {
  return {
    lang: "zh", selectedTeam: null, effectiveTeamId: "team", teamDetailLoadMode: "ready", researchTeamId: "research",
    canvas, displayCanvasNodes: nodes, visibleEdges: canvas.edges, selectedNodeId: "a", activeAgents: [],
    agentDisplay: () => ({ name: "Agent" }), researchCanvasReadOnly: true, hideToolbar: true,
    researchCanvasAutoLayoutActive: false, showCommunicationEdges: false, organizationEdgeCount: 1,
    communicationEdgeCount: 0, communicationEdgeHint: "", communicationEdgeButtonLabel: "", saveLabel: "",
    hasWritableCanvas: true, linkedChatRoomId: "", activeTeamMemberCount: 0, teamSyncPending: false,
    teamArchivePending: false, teamArchiveDisabledReason: "", showTeamLoadingSurface: false,
    teamWorkspaceLoadingTitle: "", teamWorkspaceLoadingMessage: "", teamDetailPending: false,
    teamCanvasPending: false, teamDetailError: false, teamCanvasError: false,
    canvasViewportStyle: canvasViewStyle(nodes, frame), canvasFrameSize: frame, canvasFrameRef: noop,
    nodeToneClass: () => "", roleBadgeToneClass: () => "", nodeActiveClassName: "", nodeReadOnlyClassName: "",
    styles, teamWorkspaceRoute: () => "/teams", teamChatRoomRoute: () => "/chat",
    onSelectNode: noop, onLayoutModeChange: noop, onToggleCommunicationEdges: noop, onAddNode: noop,
    onArchiveTeam: noop, onSyncRoom: noop,
    ...overrides,
  };
}

let root: Root | null = null;
let host: HTMLDivElement | null = null;
function mount(element: React.ReactNode) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root?.render(element));
  return host;
}
function mountInteractive(overrides: Partial<TeamOrganizationCanvasSurfaceProps> = {}) {
  const changed = vi.fn();
  function Probe() {
    const [view, setView] = useState<CanvasViewportStyle | null>(null);
    return <TeamOrganizationCanvasSurface {...surfaceProps({
      canvasViewportStyle: view ?? canvasViewStyle(nodes, frame),
      onCanvasViewportChange: (next) => { changed(next); setView(next); },
      ...overrides,
    })} />;
  }
  const element = mount(<Probe />);
  const viewport = element.querySelector<HTMLDivElement>('[data-testid="team-canvas-frame"]')!;
  viewport.setPointerCapture = vi.fn();
  viewport.hasPointerCapture = vi.fn(() => true);
  viewport.releasePointerCapture = vi.fn();
  const world = element.querySelector<HTMLElement>('[data-testid="team-canvas-world"]')!;
  return { element, viewport, world, changed };
}
function pointer(target: Element, type: string, overrides: Record<string, number | boolean | string> = {}) {
  const event = Object.assign(new Event(type, { bubbles: true, cancelable: true }), {
    button: 0, pointerId: 1, isPrimary: true, pointerType: "mouse", clientX: 20, clientY: 30, ...overrides,
  });
  act(() => target.dispatchEvent(event));
  return event;
}
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
});

describe("TeamOrganizationCanvasSurface viewport", () => {
  it("keeps the communication switch reachable when the authoring toolbar is hidden", () => {
    const toggle = vi.fn();
    const element = mount(<TeamOrganizationCanvasSurface {...surfaceProps({ communicationEdgeCount: 1, onToggleCommunicationEdges: toggle })} />);
    const toolbar = element.querySelector('[data-testid="team-canvas-relationship-toolbar"]')!;
    const button = toolbar.querySelector<HTMLButtonElement>('button')!;
    expect(button.textContent).toContain("通信关系 · 已隐藏");
    expect(button.getAttribute("aria-pressed")).toBe("false");
    act(() => button.click());
    expect(toggle).toHaveBeenCalledOnce();
    expect(element.querySelector('[data-testid="team-canvas-toolbar"]')).toBeNull();
    act(() => root?.render(<TeamOrganizationCanvasSurface {...surfaceProps({ communicationEdgeCount: 1, showCommunicationEdges: true, onToggleCommunicationEdges: toggle })} />));
    expect(button.textContent).toContain("通信关系 · 已显示");
    expect(button.getAttribute("aria-pressed")).toBe("true");
    act(() => root?.render(<TeamOrganizationCanvasSurface {...surfaceProps({ onToggleCommunicationEdges: toggle })} />));
    const disabledButton = toolbar.querySelector<HTMLButtonElement>('button')!;
    expect(disabledButton.disabled).toBe(true);
    act(() => disabledButton.click());
    expect(toggle).toHaveBeenCalledOnce();
  });
  it.each(["mouse", "touch"])("pans background with %s capture without editing nodes and stops on cancel", (pointerType) => {
    const pointerDown = vi.fn();
    const { viewport, world, changed } = mountInteractive({ researchCanvasReadOnly: false, onNodePointerDown: pointerDown });
    const before = structuredClone(nodes);
    const initialOffsetX = parseFloat(world.style.getPropertyValue("--canvas-offset-x"));
    const initialOffsetY = parseFloat(world.style.getPropertyValue("--canvas-offset-y"));
    pointer(world, "pointerdown", { pointerType });
    expect(viewport.setPointerCapture).toHaveBeenCalledWith(1);
    expect(document.activeElement).toBe(viewport);
    pointer(viewport, "pointermove", { clientX: 80, clientY: 10, pointerId: 2 });
    expect(changed).not.toHaveBeenCalled();
    pointer(viewport, "pointermove", { clientX: 80, clientY: 10 });
    expect(parseFloat(world.style.getPropertyValue("--canvas-offset-x"))).toBeCloseTo(initialOffsetX + 60);
    expect(parseFloat(world.style.getPropertyValue("--canvas-offset-y"))).toBeCloseTo(initialOffsetY - 20);
    expect(viewport.className).toContain("!cursor-grabbing");
    pointer(viewport, "pointercancel");
    expect(viewport.releasePointerCapture).toHaveBeenCalledWith(1);
    expect(viewport.className).not.toContain("!cursor-grabbing");
    pointer(viewport, "pointermove", { clientX: 180 });
    expect(changed).toHaveBeenCalledOnce();
    expect(pointerDown).not.toHaveBeenCalled();
    expect(nodes).toEqual(before);
    expect(world.querySelector<HTMLElement>('button')!.style.getPropertyValue("--node-x")).toBe("100px");
  });

  it("leaves nodes, edge selection, view controls and secondary pointers out of background pan", () => {
    const nodeDown = vi.fn();
    const { element, viewport, world, changed } = mountInteractive({ researchCanvasReadOnly: false, onNodePointerDown: nodeDown });
    pointer(world.querySelector('button')!, "pointerdown");
    pointer(element.querySelector('[data-testid="team-canvas-edge-edge"]')!, "pointerdown");
    pointer(element.querySelector('[data-testid="team-canvas-view-controls"]')!, "pointerdown");
    pointer(world, "pointerdown", { button: 2 });
    pointer(world, "pointerdown", { isPrimary: false });
    pointer(viewport, "pointermove", { clientX: 100 });
    expect(nodeDown).toHaveBeenCalledOnce();
    expect(viewport.setPointerCapture).not.toHaveBeenCalled();
    expect(changed).not.toHaveBeenCalled();
  });

  it("preserves editable edges and their input interactions without moving the viewport", () => {
    const selectedEdge = vi.fn();
    const commitLabel = vi.fn();
    const { element, viewport, changed } = mountInteractive({
      researchCanvasReadOnly: false,
      canvasAuthoring: {
        selectedEdgeId: "edge", connectSourceNodeId: "", renamingNodeId: "", edgeLabelDraft: "test", nodeRenameDraft: "",
        onSelectEdge: selectedEdge, onBeginConnect: noop, onCancelConnect: noop, onConnectNodes: noop,
        onDeleteEdge: noop, onEdgeLabelDraftChange: noop, onCommitEdgeLabel: commitLabel,
        onBeginNodeRename: noop, onNodeRenameDraftChange: noop, onCommitNodeRename: noop,
      },
    });
    const edge = element.querySelector<SVGElement>('[data-testid="team-canvas-edge-edge"]')!;
    pointer(edge, "pointerdown");
    act(() => edge.dispatchEvent(new MouseEvent("click", { bubbles: true })));
    expect(selectedEdge).toHaveBeenCalledWith("edge");
    const input = element.querySelector<HTMLInputElement>('[data-testid="team-canvas-edge-label-input"]')!;
    pointer(input, "pointerdown");
    act(() => input.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" })));
    expect(commitLabel).toHaveBeenCalledOnce();
    expect(changed).not.toHaveBeenCalled();
    expect(viewport.setPointerCapture).not.toHaveBeenCalled();
  });

  it("consumes background wheel zoom around the pointer while control wheel remains untouched", () => {
    const { element, viewport, world, changed } = mountInteractive();
    viewport.getBoundingClientRect = () => ({ left: 40, top: 60, width: 280, height: 240 } as DOMRect);
    const initial = canvasViewStyle(nodes, frame);
    // happy-dom's WheelEvent omits inherited MouseEvent coordinates.
    const wheel = Object.assign(new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: -80 }), { clientX: 160, clientY: 150 });
    act(() => world.dispatchEvent(wheel));
    expect(wheel.defaultPrevented).toBe(true);
    const scale = Number(world.style.getPropertyValue("--canvas-scale"));
    expect(scale).toBeGreaterThan(canvasStyleScale(initial));
    expect((120 - parseFloat(world.style.getPropertyValue("--canvas-offset-x"))) / scale)
      .toBeCloseTo((120 - parseFloat(initial["--canvas-offset-x"])) / canvasStyleScale(initial));
    expect((90 - parseFloat(world.style.getPropertyValue("--canvas-offset-y"))) / scale)
      .toBeCloseTo((90 - parseFloat(initial["--canvas-offset-y"])) / canvasStyleScale(initial));
    const controlWheel = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: -80 });
    act(() => element.querySelector('[data-testid="team-canvas-view-controls"]')!.dispatchEvent(controlWheel));
    expect(controlWheel.defaultPrevented).toBe(false);
    expect(changed).toHaveBeenCalledOnce();
  });

  it("supports zoom buttons and keyboard view navigation while preserving nested keyboard actions", () => {
    const { element, viewport, world, changed } = mountInteractive();
    const zoomIn = element.querySelector<HTMLButtonElement>('button[aria-label="放大画布"]')!;
    const initialScale = Number(world.style.getPropertyValue("--canvas-scale"));
    act(() => zoomIn.click());
    expect(Number(world.style.getPropertyValue("--canvas-scale"))).toBeCloseTo(initialScale * 1.2);
    const zoomOut = element.querySelector<HTMLButtonElement>('button[aria-label="缩小画布"]')!;
    act(() => zoomOut.click());
    expect(Number(world.style.getPropertyValue("--canvas-scale"))).toBeCloseTo(initialScale);
    const initialX = parseFloat(world.style.getPropertyValue("--canvas-offset-x"));
    act(() => viewport.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true, cancelable: true })));
    expect(parseFloat(world.style.getPropertyValue("--canvas-offset-x"))).toBeCloseTo(initialX + 40);
    changed.mockClear();
    act(() => zoomIn.dispatchEvent(new KeyboardEvent("keydown", { key: "+", bubbles: true, cancelable: true })));
    expect(changed).not.toHaveBeenCalled();
    act(() => viewport.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true, cancelable: true })));
    expect(changed).toHaveBeenLastCalledWith(null);
    for (let index = 0; index < 30; index++) act(() => zoomIn.click());
    expect(Number(world.style.getPropertyValue("--canvas-scale"))).toBe(CANVAS_MAX_ZOOM);
    expect(zoomIn.disabled).toBe(true);
  });

  it("keeps view actions available with hidden toolbar and updates the shared viewport", () => {
    const changed = vi.fn();
    function Probe() {
      const [lockedView, setLockedView] = useState<CanvasViewportStyle | null>(null);
      return <TeamOrganizationCanvasSurface {...surfaceProps({
        canvasViewportStyle: lockedView ?? canvasViewStyle(nodes, frame),
        onCanvasViewportChange: (view) => { changed(view); setLockedView(view); },
      })} />;
    }
    const element = mount(<Probe />);
    const button = (label: string) => Array.from(element.querySelectorAll("button")).find((item) => item.textContent === label)!;
    const world = element.querySelector<HTMLElement>('[data-testid="team-canvas-world"]')!;
    expect(element.querySelector('[data-testid="team-canvas-toolbar"]')).toBeNull();
    expect(canvasStyleScale(canvasViewStyle(nodes, frame))).toBeLessThan(0.58);
    act(() => button("100%").click());
    expect(world.style.getPropertyValue("--canvas-scale")).toBe("1");
    act(() => button("定位选中").click());
    const offsetX = parseFloat(world.style.getPropertyValue("--canvas-offset-x"));
    expect(offsetX + nodes[0].x + NODE_WIDTH / 2).toBeCloseTo(frame.width / 2);
    act(() => button("适应全部").click());
    expect(changed).toHaveBeenLastCalledWith(null);
    expect(Number(world.style.getPropertyValue("--canvas-scale"))).toBeLessThan(0.58);
  });

  it("renders edges and node positions in one world while read-only nodes remain inspectable", () => {
    const selected = vi.fn();
    const pointerDown = vi.fn();
    const element = mount(<TeamOrganizationCanvasSurface {...surfaceProps({ onSelectNode: selected, onNodePointerDown: pointerDown })} />);
    const world = element.querySelector('[data-testid="team-canvas-world"]')!;
    const node = world.querySelector<HTMLButtonElement>('button[aria-pressed="true"]')!;
    expect(world.querySelector('[data-testid="team-canvas-edges"]')?.parentElement).toBe(world);
    expect(node.parentElement).toBe(world);
    expect(node.style.getPropertyValue("--node-x")).toBe("100px");
    act(() => {
      node.dispatchEvent(new Event("pointerdown", { bubbles: true }));
      node.click();
    });
    expect(pointerDown).not.toHaveBeenCalled();
    expect(selected).toHaveBeenCalledWith("a");
  });

  it("preserves pointer editing callbacks for writable canvases", () => {
    const pointerDown = vi.fn();
    const element = mount(<TeamOrganizationCanvasSurface {...surfaceProps({ researchCanvasReadOnly: false, onNodePointerDown: pointerDown })} />);
    const node = element.querySelector<HTMLButtonElement>('button[aria-pressed="true"]')!;
    act(() => node.dispatchEvent(new Event("pointerdown", { bubbles: true })));
    expect(pointerDown).toHaveBeenCalledOnce();
    expect(pointerDown.mock.calls[0][1]).toEqual(nodes[0]);
  });
});
