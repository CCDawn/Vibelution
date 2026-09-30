import { describe, expect, it } from "vitest";

import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../../api/types";
import { memoryGraphSlice } from "./memoryGraphSlice";

function node(
  id: string,
  label: string,
  type = "concept",
  contentItems: MemoryKnowledgeGraphNode["contentItems"] = [],
): MemoryKnowledgeGraphNode {
  return {
    id,
    type,
    label,
    summary: "",
    status: "active",
    createdAt: "2026-09-30T00:00:00.000Z",
    updatedAt: "2026-09-30T00:00:00.000Z",
    metadata: {},
    responsibilityQuestion: "",
    visual: {},
    childNodeIds: [],
    contentItems,
  };
}

function edge(id: string, source: string, target: string): MemoryKnowledgeGraphEdge {
  return { id, source, target, type: "related", label: "关联", weight: 1, metadata: {} };
}

describe("memoryGraphSlice", () => {
  it("keeps direct search context inside the payload and leaves the DTO unchanged", () => {
    const nodes = [
      node("memory", "私人记忆", "agent_private_memory", [
        { id: "item-1", type: "memory", title: "会话中的记忆检索", summary: "按需读取" },
      ]),
      node("source", "来源"),
      node("neighbor", "直接关联"),
      node("second-hop", "第二层"),
    ];
    const edges = [
      edge("memory-source", "memory", "source"),
      edge("memory-neighbor", "memory", "neighbor"),
      edge("neighbor-second-hop", "neighbor", "second-hop"),
      edge("dangling-out", "memory", "not-loaded"),
      edge("dangling-in", "not-loaded", "memory"),
    ];
    const original = structuredClone({ nodes, edges });

    const result = memoryGraphSlice(nodes, edges, "  会话中的记忆检索 ", "");

    expect(result.matches.map(item => item.id)).toEqual(["memory"]);
    expect(result.nodes.map(item => item.id)).toEqual(["memory", "source", "neighbor"]);
    expect(result.edges.map(item => item.id)).toEqual(["memory-source", "memory-neighbor"]);
    expect({ nodes, edges }).toEqual(original);
  });

  it("shows only matched nodes and omits context edges when matchOnly is enabled", () => {
    const nodes = [node("match", "Memory graph"), node("neighbor", "Related source")];
    const edges = [edge("match-neighbor", "match", "neighbor")];

    const result = memoryGraphSlice(nodes, edges, "memory", "", { matchOnly: true });

    expect(result.matches.map(item => item.id)).toEqual(["match"]);
    expect(result.nodes.map(item => item.id)).toEqual(["match"]);
    expect(result.edges).toEqual([]);
  });

  it("expands selected neighborhoods by one or two hops, capped at two", () => {
    const nodes = [node("a", "A"), node("b", "B"), node("c", "C"), node("d", "D"), node("e", "E")];
    const edges = [edge("ab", "a", "b"), edge("bc", "b", "c"), edge("cd", "c", "d"), edge("de", "d", "e")];

    const oneHop = memoryGraphSlice(nodes, edges, "", "", { center: "c", depth: 1 });
    const twoHops = memoryGraphSlice(nodes, edges, "", "", { center: "c", depth: 2 });
    const capped = memoryGraphSlice(nodes, edges, "", "", { center: "c", depth: 8 });

    expect(oneHop.nodes.map(item => item.id)).toEqual(["b", "c", "d"]);
    expect(oneHop.edges.map(item => item.id)).toEqual(["bc", "cd"]);
    expect(twoHops.nodes.map(item => item.id)).toEqual(["a", "b", "c", "d", "e"]);
    expect(capped.nodes.map(item => item.id)).toEqual(twoHops.nodes.map(item => item.id));
  });

  it("does not let dangling edge endpoints extend the authorized graph", () => {
    const nodes = [node("seed", "Seed"), node("neighbor", "Neighbor")];
    const edges = [edge("valid", "seed", "neighbor"), edge("outside", "neighbor", "outside-node")];

    const result = memoryGraphSlice(nodes, edges, "seed", "", { center: "neighbor", depth: 2 });

    expect(result.nodes.map(item => item.id)).toEqual(["seed", "neighbor"]);
    expect(result.edges.map(item => item.id)).toEqual(["valid"]);
    expect(result.nodes.some(item => item.id === "outside-node")).toBe(false);
  });
});
