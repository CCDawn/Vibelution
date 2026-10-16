import { expect, it } from "vitest";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../../../../api/types";
import { layoutMemoryKnowledgeGraph } from "./memoryGraphModel";
import { layoutMemoryGraphCosmos } from "./memoryGraphCosmosLayout";

it("places real shared sources near their records, keeps topics centered and preserves DTOs", () => {
  const node = (id: string, type: string): MemoryKnowledgeGraphNode => ({ id, type, label: id, summary: "", status: "active", createdAt: "", updatedAt: "", metadata: { topicId: "dynamic-id", topicLabel: "真实主题" }, visual: {}, responsibilityQuestion: "", childNodeIds: [], contentItems: [] });
  const nodes = [node("arbitrary-root", "topic"), node("uuid-alpha", "knowledge_item"), node("opaque-beta", "knowledge_item"), node("sha-source", "source_artifact")];
  const edges: MemoryKnowledgeGraphEdge[] = nodes.slice(1, 3).map(record => ({ id: record.id + ":source", source: record.id, target: "sha-source", type: "knowledge_item_has_source", label: "来源于", weight: 1, metadata: { layer: "evidence" } }));
  const base = layoutMemoryKnowledgeGraph(nodes, edges, { groupByTopic: true });
  const before = JSON.stringify(base);
  const spatial = layoutMemoryGraphCosmos(base, edges);
  expect(spatial.nodes.find(node => node.id === "arbitrary-root")).toMatchObject(spatial.clusters[0].center);
  const source = spatial.nodes.find(node => node.id === "sha-source")!;
  const records = spatial.nodes.filter(node => node.source.type === "knowledge_item");
  expect(source.z).toBeCloseTo((records[0].z + records[1].z) / 2 - 0.85);
  expect(spatial.nodes.every(view => view.source === nodes.find(node => node.id === view.id))).toBe(true);
  expect(JSON.stringify(base)).toBe(before);
  expect(layoutMemoryGraphCosmos(base, [...edges].reverse())).toEqual(spatial);
});
