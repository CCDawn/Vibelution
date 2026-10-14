import { describe, expect, it } from "vitest";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode, PlatformKnowledgeGraphPayload } from "../../api/types";
import { isAdministrativeRelation, isContentRelation, platformTopicOverview, platformTopicSlice } from "./platformKnowledgeGraphModel";
const node = (id: string, topicId?: string): MemoryKnowledgeGraphNode => ({ id, type: "knowledge_item", label: id, summary: "", status: "active", createdAt: "", updatedAt: "", metadata: { topicId }, visual: {}, responsibilityQuestion: "", childNodeIds: [], contentItems: [] });
const edge = (id: string, source: string, target: string, layer = "knowledge"): MemoryKnowledgeGraphEdge => ({ id, source, target, type: "supports", label: "支持", weight: 1, metadata: { layer, status: "confirmed" } });
const payload = { nodes: [node("a", "t1"), node("b", "t2"), node("c", "t1"), node("base"), node("owner"), node("other-owner")], edges: [], topics: [{ id: "t1", label: "主题一", groupingBasis: "tag", nodeIds: ["a", "c"] }, { id: "t2", label: "主题二", groupingBasis: "tag", nodeIds: ["b"] }] } as unknown as PlatformKnowledgeGraphPayload;
describe("platform topic display projection", () => {
  it("distinguishes content facts from grouping and ingestion audit records", () => {
    expect(isContentRelation({ ...edge("group", "t1", "a"), type: "topic_has_item" })).toBe(false);
    expect(isContentRelation(edge("support", "a", "b"))).toBe(true);
    const audit = { ...edge("audit", "ref", "a", "evidence"), type: "official_approved_for_ingestion" };
    expect(isContentRelation(audit)).toBe(false);
    expect(isAdministrativeRelation(audit)).toBe(true);
    expect(isAdministrativeRelation(edge("source", "a", "s", "evidence"))).toBe(false);
  });
  it("does not invent semantic edges from shared tags and aggregates only existing cross-theme relations", () => {
    expect(platformTopicOverview(payload, []).edges).toEqual([]);
    const result = platformTopicOverview(payload, [edge("ab", "a", "b"), edge("cb", "c", "b"), edge("ac", "a", "c"), edge("missing", "a", "inaccessible")]);
    expect(result.edges).toHaveLength(1);
    expect(result.edges[0].metadata.relationIds).toEqual(["ab", "cb"]);
    expect(result.nodes[0].metadata.memberCount).toBe(2);
    expect(result.nodes[0].contentItems).toEqual([]);
  });
  it("keeps cross-theme endpoints and includes only the selected owner chain", () => {
    const semantic = platformTopicSlice(payload, "t1", [edge("ab", "a", "b")]);
    expect(semantic.nodes.map(item => item.id)).toContain("b");
    const ownership = platformTopicSlice(payload, "t1", [edge("ba", "base", "a", "ownership"), edge("ob", "owner", "base", "ownership"), edge("unrelated", "other-owner", "b", "ownership")]);
    expect(ownership.nodes.map(item => item.id)).toContain("owner");
    expect(ownership.nodes.map(item => item.id)).not.toContain("other-owner");
  });
});
