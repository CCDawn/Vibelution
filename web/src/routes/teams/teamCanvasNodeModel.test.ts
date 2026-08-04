import { describe, expect, it } from "vitest";

import type { TeamCanvasNode, TeamOrganizationCanvas } from "../../api/types";
import {
  applyNodeDragDeltas,
  buildCanvasWithAppliedNodeDraft,
  buildCanvasWithDeletedNode,
  buildCanvasWithDraggedNode,
  buildCanvasWithLeadConnection,
  buildCanvasWithNewNode,
  buildCanvasWithUnboundNode,
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
});
