import { describe, expect, it } from "vitest";

import type { TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import {
  applyNodeDragDeltas,
  buildCanvasWithAppliedNodeDraft,
  buildCanvasWithDeletedNode,
  buildCanvasWithDraggedNode,
  buildCanvasWithEdge,
  buildCanvasWithLeadConnection,
  buildCanvasWithNewNode,
  buildCanvasWithRelabeledEdge,
  buildCanvasWithRelabeledNode,
  buildCanvasWithUnboundNode,
  buildCanvasWithoutEdge,
  nextEdgeId,
} from "./teamCanvasNodeModel";

function node(partial: Partial<TeamCanvasNode> & Pick<TeamCanvasNode, "id">): TeamCanvasNode {
  return {
    id: partial.id,
    label: partial.label ?? partial.id,
    type: partial.type ?? "role",
    status: partial.status ?? "unbound",
    x: partial.x ?? 0,
    y: partial.y ?? 0,
    agentId: partial.agentId ?? "",
    agentCode: partial.agentCode ?? "",
    agentName: partial.agentName ?? "",
    role: partial.role ?? "",
    purpose: partial.purpose ?? "",
  } as TeamCanvasNode;
}

function canvas(nodes: TeamCanvasNode[], edges: TeamOrganizationCanvas["edges"] = []): TeamOrganizationCanvas {
  return {
    teamId: "team-1",
    nodes,
    edges,
    validation: { ok: true, issues: [] },
  } as TeamOrganizationCanvas;
}

describe("teamCanvasNodeModel", () => {
  it("adds a new unbound role node and selects it", () => {
    const base = canvas([node({ id: "lead", x: 10, y: 10 })]);
    const next = buildCanvasWithNewNode({ canvas: base, lang: "zh" });
    expect(next.canvas.nodes).toHaveLength(2);
    expect(next.selectedNodeId).toBe(next.canvas.nodes[1]?.id);
    expect(next.canvas.nodes[1]?.label).toBe("新角色");
    expect(next.canvas.nodes[1]?.status).toBe("unbound");
  });

  it("applies node draft binding to the selected node", () => {
    const selected = node({ id: "n2", label: "old" });
    const base = canvas([node({ id: "lead" }), selected]);
    const next = buildCanvasWithAppliedNodeDraft({
      canvas: base,
      selectedNode: selected,
      nodeDraft: { label: "Planner", role: "lead", purpose: "plan", agentId: "a1" },
      agent: { agentId: "a1", agentCode: "P", displayName: "Planner Agent" },
    });
    const updated = next.nodes.find((item) => item.id === "n2");
    expect(updated?.agentId).toBe("a1");
    expect(updated?.type).toBe("agent");
    expect(updated?.status).toBe("bound");
    expect(updated?.label).toBe("Planner");
  });

  it("unbinds, deletes, connects, and moves nodes", () => {
    const selected = node({ id: "n2", agentId: "a1", type: "agent", status: "bound" });
    const base = canvas(
      [node({ id: "lead" }), selected],
      [{ id: "e1", source: "lead", target: "n2", label: "", type: "reports_to" }],
    );

    const unbound = buildCanvasWithUnboundNode({ canvas: base, selectedNodeId: "n2" });
    expect(unbound.nodes.find((item) => item.id === "n2")?.status).toBe("unbound");

    const deleted = buildCanvasWithDeletedNode({ canvas: base, selectedNodeId: "n2" });
    expect(deleted?.canvas.nodes).toHaveLength(1);
    expect(deleted?.canvas.edges).toHaveLength(0);
    expect(deleted?.selectedNodeId).toBe("lead");

    const connected = buildCanvasWithLeadConnection({
      canvas: canvas([node({ id: "lead" }), node({ id: "n3" })]),
      selectedNodeId: "n3",
    });
    expect(connected?.edges).toHaveLength(1);
    expect(connected?.edges[0]?.source).toBe("lead");

    const moved = buildCanvasWithDraggedNode({ canvas: base, nodeId: "n2", x: 40, y: 50 });
    expect(moved.nodes.find((item) => item.id === "n2")).toMatchObject({ x: 40, y: 50 });
  });

  it("computes drag deltas without inventing negative positions", () => {
    expect(applyNodeDragDeltas({
      startX: 10,
      startY: 10,
      startClientX: 100,
      startClientY: 100,
      clientX: 90,
      clientY: 80,
      scale: 1,
    })).toEqual({ x: 0, y: 0, moved: true });
  });

  it("connects two nodes with a deterministic id and default communication type", () => {
    const base = canvas([node({ id: "lead" }), node({ id: "n2" })]);
    const next = buildCanvasWithEdge({ canvas: base, sourceNodeId: "lead", targetNodeId: "n2" });
    expect(next).not.toBeNull();
    expect(next?.edges).toHaveLength(1);
    expect(next?.edges[0]).toMatchObject({
      id: "edge-lead-n2",
      source: "lead",
      target: "n2",
      type: "communication",
      label: "",
    });
  });

  it("keeps an explicit whitelisted edge type and trims the label", () => {
    const base = canvas([node({ id: "lead" }), node({ id: "n2" })]);
    const next = buildCanvasWithEdge({
      canvas: base,
      sourceNodeId: "lead",
      targetNodeId: "n2",
      type: "delegates_to",
      label: "  委派  ",
    });
    expect(next?.edges[0]).toMatchObject({ type: "delegates_to", label: "委派" });
  });

  it("rejects duplicate same-direction edges but allows the reverse direction", () => {
    const base = canvas(
      [node({ id: "lead" }), node({ id: "n2" })],
      [{ id: "e1", source: "lead", target: "n2", label: "", type: "reports_to" }],
    );
    expect(buildCanvasWithEdge({ canvas: base, sourceNodeId: "lead", targetNodeId: "n2" })).toBeNull();
    const reversed = buildCanvasWithEdge({ canvas: base, sourceNodeId: "n2", targetNodeId: "lead" });
    expect(reversed?.edges).toHaveLength(2);
    expect(reversed?.edges[1]).toMatchObject({ id: "edge-n2-lead", source: "n2", target: "lead" });
  });

  it("rejects unknown edge types, missing endpoints, and self edges", () => {
    const base = canvas([node({ id: "lead" }), node({ id: "n2" })]);
    expect(buildCanvasWithEdge({
      canvas: base,
      sourceNodeId: "lead",
      targetNodeId: "n2",
      type: "secret_handshake",
    })).toBeNull();
    expect(buildCanvasWithEdge({ canvas: base, sourceNodeId: "lead", targetNodeId: "ghost" })).toBeNull();
    expect(buildCanvasWithEdge({ canvas: base, sourceNodeId: "lead", targetNodeId: "lead" })).toBeNull();
    expect(buildCanvasWithEdge({ canvas: base, sourceNodeId: "", targetNodeId: "n2" })).toBeNull();
  });

  it("generates suffixed deterministic edge ids on collision", () => {
    const edges = [
      { id: "edge-a-b", source: "x", target: "y", label: "", type: "communication" },
    ];
    expect(nextEdgeId(edges, "a", "b")).toBe("edge-a-b-2");
    expect(nextEdgeId([...edges, { id: "edge-a-b-2", source: "x", target: "z", label: "", type: "communication" }], "a", "b"))
      .toBe("edge-a-b-3");
    expect(nextEdgeId([], "a", "b")).toBe("edge-a-b");
  });

  it("deletes an edge by id and rejects unknown edge ids", () => {
    const base = canvas(
      [node({ id: "lead" }), node({ id: "n2" })],
      [
        { id: "e1", source: "lead", target: "n2", label: "", type: "reports_to" },
        { id: "e2", source: "n2", target: "lead", label: "", type: "supports" },
      ],
    );
    const next = buildCanvasWithoutEdge({ canvas: base, edgeId: "e1" });
    expect(next?.edges.map((edge) => edge.id)).toEqual(["e2"]);
    expect(buildCanvasWithoutEdge({ canvas: base, edgeId: "missing" })).toBeNull();
  });

  it("relabels an edge in place and rejects unknown edge ids", () => {
    const base = canvas(
      [node({ id: "lead" }), node({ id: "n2" })],
      [{ id: "e1", source: "lead", target: "n2", label: "旧标签", type: "reports_to" }],
    );
    const next = buildCanvasWithRelabeledEdge({ canvas: base, edgeId: "e1", label: " 新标签 " });
    expect(next?.edges[0]).toMatchObject({ id: "e1", label: "新标签", type: "reports_to" });
    expect(buildCanvasWithRelabeledEdge({ canvas: base, edgeId: "missing", label: "x" })).toBeNull();
  });

  it("relabeled nodes keep role/agent fields untouched (member projection safe)", () => {
    const bound = node({ id: "n2", label: "旧名", role: "lead", agentId: "a1", type: "agent", status: "bound" });
    const base = canvas([node({ id: "lead" }), bound]);
    const next = buildCanvasWithRelabeledNode({ canvas: base, nodeId: "n2", label: "  资料提炼  " });
    expect(next?.nodes.find((item) => item.id === "n2")).toMatchObject({
      label: "资料提炼",
      role: "lead",
      agentId: "a1",
      type: "agent",
      status: "bound",
    });
  });

  it("rejects empty or unchanged node labels and unknown nodes", () => {
    const base = canvas([node({ id: "lead", label: "负责人" }), node({ id: "n2", label: "同名" })]);
    expect(buildCanvasWithRelabeledNode({ canvas: base, nodeId: "n2", label: "   " })).toBeNull();
    expect(buildCanvasWithRelabeledNode({ canvas: base, nodeId: "ghost", label: "x" })).toBeNull();
    // Unchanged label returns the same canvas reference (idempotent no-save).
    expect(buildCanvasWithRelabeledNode({ canvas: base, nodeId: "n2", label: "同名" })).toBe(base);
  });
});
