import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../../api/types";

/** Only expands within the server-authorized payload; dangling edges never create nodes. */
export function memoryGraphSlice(
  nodes: MemoryKnowledgeGraphNode[], edges: MemoryKnowledgeGraphEdge[], query: string, type: string,
  options: { matchOnly?: boolean; center?: string; depth?: number } = {},
) {
  const text = query.trim().toLowerCase();
  const matches = nodes.filter(node => (!type || node.type === type) && (!text || [
    node.label, node.type, node.status, node.summary, node.responsibilityQuestion,
    ...(node.contentItems ?? []).map(item => `${item.title} ${item.summary} ${item.knowledgeBaseName ?? ""}`),
  ].some(value => String(value || "").toLowerCase().includes(text))));
  const allowed = new Set(nodes.map(node => node.id));
  let ids = new Set(matches.map(node => node.id));
  const expand = (seed: Set<string>) => {
    const next = new Set(seed);
    for (const edge of edges) {
      if (!allowed.has(edge.source) || !allowed.has(edge.target)) continue;
      if (seed.has(edge.source)) next.add(edge.target);
      if (seed.has(edge.target)) next.add(edge.source);
    }
    return next;
  };
  if (text && !options.matchOnly) ids = expand(ids);
  if (options.center && allowed.has(options.center) && options.depth) {
    ids = new Set([options.center]);
    for (let hop = 0; hop < Math.min(2, options.depth); hop++) ids = expand(ids);
  }
  return {
    matches,
    nodes: nodes.filter(node => ids.has(node.id)),
    edges: edges.filter(edge => allowed.has(edge.source) && allowed.has(edge.target) && ids.has(edge.source) && ids.has(edge.target)),
  };
}
