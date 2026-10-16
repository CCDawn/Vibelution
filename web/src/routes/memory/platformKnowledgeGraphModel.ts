import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode, PlatformKnowledgeGraphPayload } from "../../api/types";

export type PlatformRelationLayer = "knowledge" | "ownership" | "evidence";
export const platformLayerLabels: Record<PlatformRelationLayer, string> = { knowledge: "知识关联", ownership: "归属关系", evidence: "证据关系" };
export const topicBasisLabels = { tag: "按内容标签聚合", knowledge_base: "按知识库聚合", official_target_domain: "按已审核科研领域聚合", title_keywords: "按标题关键词分组" } as const;

export function isAdministrativeRelation(edge: MemoryKnowledgeGraphEdge) {
  return edge.type === "official_approved_for_ingestion";
}

export function isContentRelation(edge: MemoryKnowledgeGraphEdge) {
  return relationLayer(edge) === "knowledge" && edge.type !== "topic_has_item";
}

export function relationLayer(edge: MemoryKnowledgeGraphEdge): PlatformRelationLayer {
  return edge.metadata.layer === "ownership" ? "ownership" : edge.metadata.layer === "evidence" ? "evidence" : "knowledge";
}

/** Display-only aggregation; neither proximity nor shared tags creates factual edges. */
export function platformTopicOverview(payload: PlatformKnowledgeGraphPayload, edges: MemoryKnowledgeGraphEdge[]) {
  const byId = new Map(payload.nodes.map(node => [node.id, node]));
  const topics = payload.topics.filter(topic => topic.nodeIds.some(id => byId.has(id)));
  const topicIds = new Set(topics.map(topic => topic.id));
  const nodes: MemoryKnowledgeGraphNode[] = topics.map(topic => ({
    id: topic.id, type: "topic", label: `${topic.label} · ${topic.nodeIds.filter(id => byId.has(id)).length} 条知识`, summary: `${topicBasisLabels[topic.groupingBasis]} · 进入主题查看关系`,
    status: "active", createdAt: "", updatedAt: "", responsibilityQuestion: "这个主题包含哪些正式知识和来源依据？",
    metadata: { topicId: topic.id, topicLabel: topic.label, memberCount: topic.nodeIds.filter(id => byId.has(id)).length, groupingBasis: topic.groupingBasis },
    visual: { size: "group" }, childNodeIds: topic.nodeIds, contentItems: [],
  }));
  const aggregate = new Map<string, MemoryKnowledgeGraphEdge>();
  for (const edge of edges) {
    const sourceTopic = String(byId.get(edge.source)?.metadata.topicId ?? "");
    const targetTopic = String(byId.get(edge.target)?.metadata.topicId ?? "");
    if (!topicIds.has(sourceTopic) || !topicIds.has(targetTopic) || sourceTopic === targetTopic) continue;
    const key = `${sourceTopic}\0${targetTopic}\0${edge.label}\0${edge.metadata.status}`;
    const current = aggregate.get(key);
    if (current) { current.weight += 1; (current.metadata.relationIds as string[]).push(edge.id); }
    else aggregate.set(key, { ...edge, id: `overview:${edge.id}`, source: sourceTopic, target: targetTopic, weight: 1,
      metadata: { ...edge.metadata, relationIds: [edge.id] } });
  }
  return { nodes, edges: [...aggregate.values()] };
}

/** Full spatial projection uses returned records and real relation IDs only. */
export function platformSpatialOverview(payload: PlatformKnowledgeGraphPayload, edges: MemoryKnowledgeGraphEdge[]) {
  const roots = platformTopicOverview(payload, []).nodes;
  const available = new Map(payload.nodes.map(node => [node.id, node]));
  const validEdges = edges.filter(edge => available.has(edge.source) && available.has(edge.target) && edge.type !== "topic_has_item");
  const ids = new Set(payload.nodes.filter(node => node.type === "knowledge_item").map(node => node.id));
  for (const edge of validEdges) { ids.add(edge.source); ids.add(edge.target); }
  const topicNames = new Map(payload.topics.map(topic => [topic.id, topic.label]));
  const membership = new Map<string, string>();
  for (const topic of payload.topics) for (const id of topic.nodeIds) if (!membership.has(id)) membership.set(id, topic.id);
  // A shared source can have multiple topics. Pick one deterministic display
  // cluster while retaining its single identity and every actual relation.
  const linkedTopics = new Map<string, string[]>();
  for (const edge of validEdges) for (const [from, to] of [[edge.source, edge.target], [edge.target, edge.source]]) {
    const topic = available.get(to)?.metadata.topicId ?? membership.get(to);
    if (typeof topic === "string" && topicNames.has(topic)) linkedTopics.set(from, [...(linkedTopics.get(from) ?? []), topic]);
  }
  const records = payload.nodes.filter(node => ids.has(node.id) && node.type !== "topic").map(node => {
    const topicId = typeof node.metadata.topicId === "string" && node.metadata.topicId ? node.metadata.topicId
      : membership.get(node.id) ?? [...(Array.isArray(node.metadata.topicIds) ? node.metadata.topicIds.filter((id): id is string => typeof id === "string" && topicNames.has(id)) : []), ...(linkedTopics.get(node.id) ?? [])].sort()[0];
    return topicId ? { ...node, metadata: { ...node.metadata, topicId, topicLabel: topicNames.get(topicId) ?? node.metadata.topicLabel } } : node;
  });
  const nodes = [...roots, ...records];
  const rendered = new Set(nodes.map(node => node.id));
  return { nodes, edges: validEdges.filter(edge => rendered.has(edge.source) && rendered.has(edge.target)) };
}

export function platformTopicSlice(payload: PlatformKnowledgeGraphPayload, topicId: string, edges: MemoryKnowledgeGraphEdge[], selectedNodeId = "") {
  const members = new Set(payload.topics.find(topic => topic.id === topicId)?.nodeIds ?? []);
  const owned = new Set(payload.nodes.filter(node => node.metadata.topicId === topicId || (Array.isArray(node.metadata.topicIds) && node.metadata.topicIds.includes(topicId))).map(node => node.id));
  for (const id of members) owned.add(id);
  const selectedEdges = edges.filter(edge => owned.has(edge.source) || owned.has(edge.target));
  const ids = new Set(selectedEdges.flatMap(edge => [edge.source, edge.target]));
  // Include the selected theme's owner chain without pulling sibling owners in.
  if (edges.some(edge => relationLayer(edge) === "ownership")) {
    for (let hop = 0; hop < 2; hop++) {
      for (const edge of edges) if (ids.has(edge.target) && !selectedEdges.includes(edge)) {
        selectedEdges.push(edge); ids.add(edge.source);
      }
    }
  }
  if (selectedNodeId) ids.add(selectedNodeId);
  for (const id of members) ids.add(id);
  return { nodes: payload.nodes.filter(node => ids.has(node.id)), edges: selectedEdges };
}
