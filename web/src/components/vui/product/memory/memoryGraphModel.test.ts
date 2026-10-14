import { describe, expect, it } from "vitest";
import type { MemoryKnowledgeGraphNode } from "../../../../api/types";
import { layoutMemoryKnowledgeGraph, memoryGraphClusterSeed } from "./memoryGraphModel";

function node(id: string, type = "concept"): MemoryKnowledgeGraphNode {
  return { id, type, label: id, summary: "", status: "active", createdAt: "", updatedAt: "",
    metadata: {}, responsibilityQuestion: "", visual: {}, childNodeIds: [], contentItems: [] };
}

describe("memory graph spatial layout", () => {
  it("groups explicit topics across node types only when the consumer opts in", () => {
    const nodes = [node("source", "source_artifact"), node("concept"), node("unassigned", "agent")];
    nodes[0].metadata = { topicId: "science", topicLabel: "科学研究" };
    nodes[1].metadata = { topicId: "science", topicLabel: "科学研究" };
    expect(layoutMemoryKnowledgeGraph(nodes, []).clusters.map(cluster => cluster.key)).toEqual(["agents", "knowledge", "sources"]);
    const layout = layoutMemoryKnowledgeGraph(nodes, [], { groupByTopic: true });
    expect(layout.clusters.find(cluster => cluster.key === "topic:science")).toMatchObject({ label: "科学研究", nodeIds: ["concept", "source"] });
    expect(layout.nodes.find(view => view.id === "unassigned")?.clusterKey).toBe("agents");
    expect(layoutMemoryKnowledgeGraph([...nodes].reverse(), [], { groupByTopic: true })).toEqual(layout);
  });

  it("keeps a singleton aggregated topic populated and counts finite members without mutating DTOs", () => {
    const aggregate = node("theme", "topic");
    aggregate.label = "工程知识 · 42";
    aggregate.metadata = { topicId: "engineering", topicLabel: "工程知识", memberCount: 42 };
    const before = JSON.stringify(aggregate);
    const layout = layoutMemoryKnowledgeGraph([aggregate], [], { groupByTopic: true });
    expect(layout.clusters).toHaveLength(1);
    expect(layout.clusters[0]).toMatchObject({ key: "topic:engineering", memberCount: 42, nodeIds: ["theme"] });
    expect(layout.nodes[0].source).toBe(aggregate);
    expect(layout.nodes[0].x).toBe(layout.clusters[0].center.x);
    expect(JSON.stringify(aggregate)).toBe(before);
    aggregate.metadata.memberCount = Infinity;
    expect(layoutMemoryKnowledgeGraph([aggregate], [], { groupByTopic: true }).clusters[0].memberCount).toBe(1);
    expect(memoryGraphClusterSeed("topic:engineering")).toBe(memoryGraphClusterSeed("topic:engineering"));
    expect(memoryGraphClusterSeed("topic:science")).not.toBe(memoryGraphClusterSeed("topic:engineering"));
  });
  it("distributes a topic in a volume rather than a plane or a thin depth band", () => {
    const { nodes } = layoutMemoryKnowledgeGraph(Array.from({ length: 22 }, (_, i) => node(String(i))), []);
    const spans = ["x", "y", "z"].map(axis => {
      const values = nodes.map(n => n[axis as "x" | "y" | "z"]);
      return Math.max(...values) - Math.min(...values);
    });
    expect(Math.min(...spans) / Math.max(...spans)).toBeGreaterThan(0.6);
    const [a, b, c, d] = nodes;
    const u = [b.x-a.x,b.y-a.y,b.z-a.z], v = [c.x-a.x,c.y-a.y,c.z-a.z], w = [d.x-a.x,d.y-a.y,d.z-a.z];
    const volume = u[0]*(v[1]*w[2]-v[2]*w[1]) - u[1]*(v[0]*w[2]-v[2]*w[0]) + u[2]*(v[0]*w[1]-v[1]*w[0]);
    expect(Math.abs(volume)).toBeGreaterThan(1);
  });

  it("is deterministic under payload reordering and preserves source identity", () => {
    const nodes = Array.from({ length: 12 }, (_, i) => node(String(i), i % 2 ? "agent" : "concept"));
    const before = JSON.stringify(nodes);
    const first = layoutMemoryKnowledgeGraph(nodes, []);
    expect(layoutMemoryKnowledgeGraph([...nodes].reverse(), [])).toEqual(first);
    expect(JSON.stringify(nodes)).toBe(before);
    for (const view of first.nodes) expect(view.source).toBe(nodes.find(n => n.id === view.id));
  });

  it("keeps dense topic envelopes separated in 3D and handles sparse payloads", () => {
    expect(layoutMemoryKnowledgeGraph([], []).nodes).toEqual([]);
    const single = layoutMemoryKnowledgeGraph([node("one")], []);
    expect(single.nodes[0].x).toBe(single.clusters[0].center.x);
    const types = ["agent", "concept", "source_artifact", "project", "runtime_scene"];
    const layout = layoutMemoryKnowledgeGraph(Array.from({ length: 110 }, (_, i) => node(String(i), types[i % 5])), []);
    const radius = (key: string) => {
      const center = layout.clusters.find(c => c.key === key)!.center;
      return Math.max(...layout.nodes.filter(n => n.clusterKey === key).map(n => Math.hypot(n.x-center.x,n.y-center.y,n.z-center.z)));
    };
    for (let i = 0; i < layout.clusters.length; i++) for (let j = i+1; j < layout.clusters.length; j++) {
      const a = layout.clusters[i], b = layout.clusters[j];
      expect(Math.hypot(a.center.x-b.center.x,a.center.y-b.center.y,a.center.z-b.center.z)).toBeGreaterThan(radius(a.key)+radius(b.key)+2);
    }
  });
});
