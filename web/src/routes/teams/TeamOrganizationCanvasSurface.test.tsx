/** @vitest-environment happy-dom */
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import styles from "../TeamsRoute.styles";
import { canvasStyleScale, canvasViewStyle, NODE_WIDTH, type CanvasViewportStyle } from "./canvasGeometry";
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
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
  host = null;
});

describe("TeamOrganizationCanvasSurface viewport", () => {
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
