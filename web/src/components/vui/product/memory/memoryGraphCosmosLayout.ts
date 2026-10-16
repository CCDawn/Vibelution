import type { MemoryKnowledgeGraphEdge } from "../../../../api/types";
import { memoryGraphClusterSeed, type MemoryGraphLayout } from "./memoryGraphModel";

/** Presentation only: source placement follows actual returned relationships. */
export function layoutMemoryGraphCosmos(layout: MemoryGraphLayout, edges: readonly MemoryKnowledgeGraphEdge[], compact = false): MemoryGraphLayout {
  const originalCenters = new Map(layout.clusters.map(cluster => [cluster.key, cluster.center]));
  const ordered = [...layout.clusters].sort((left, right) => right.nodeIds.length - left.nodeIds.length || left.key.localeCompare(right.key));
  const centers = new Map(ordered.map((cluster, index) => {
    const angle = index * Math.PI * (3 - Math.sqrt(5));
    const radius = ordered.length === 1 ? 0 : Math.sqrt(index + 0.5) * 7.5;
    return [cluster.key, { x: Math.cos(angle) * radius * (compact ? 0.65 : 1.45), y: Math.sin(angle) * radius * (compact ? 1.3 : 0.67), z: ordered.length === 1 ? 0 : Math.sin(memoryGraphClusterSeed(cluster.key)) * 6 }];
  }));
  const translated = layout.nodes.map(node => {
    const from = originalCenters.get(node.clusterKey)!, to = centers.get(node.clusterKey)!;
    return { ...node, x: node.x - from.x + to.x, y: node.y - from.y + to.y, z: node.z - from.z + to.z };
  });
  const byId = new Map(translated.map(node => [node.id, node]));
  const neighbors = new Map<string, Set<string>>();
  for (const edge of edges) {
    if (!byId.has(edge.source) || !byId.has(edge.target)) continue;
    for (const [from, to] of [[edge.source, edge.target], [edge.target, edge.source]]) {
      const ids = neighbors.get(from) ?? new Set<string>(); ids.add(to); neighbors.set(from, ids);
    }
  }
  return { clusters: layout.clusters.map(cluster => ({ ...cluster, center: centers.get(cluster.key)! })), nodes: translated.map(node => {
    if (node.source.type === "topic") return { ...node, ...centers.get(node.clusterKey) };
    if (node.source.type !== "source_artifact") return node;
    const records = [...(neighbors.get(node.id) ?? [])].sort().map(id => byId.get(id)!).filter(record => record.source.type === "knowledge_item");
    if (!records.length) return node;
    const seed = memoryGraphClusterSeed(node.id) / 4294967296 * Math.PI * 2;
    const mean = records.reduce((sum, record) => ({ x: sum.x + record.x / records.length, y: sum.y + record.y / records.length, z: sum.z + record.z / records.length }), { x: 0, y: 0, z: 0 });
    return { ...node, x: mean.x + Math.cos(seed) * 0.65, y: mean.y + Math.sin(seed) * 0.45, z: mean.z - 0.85 };
  }) };
}
