import type {
  MemoryKnowledgeGraphEdge,
  MemoryKnowledgeGraphNode,
} from "../../../../api/types";

export type MemoryGraphClusterKey =
  | "workspace"
  | "agents"
  | "knowledge"
  | "sources"
  | "operations";

export type MemoryGraphCluster = {
  key: MemoryGraphClusterKey;
  label: string;
  center: { x: number; y: number; z: number };
  nodeIds: string[];
};

export type PositionedMemoryKnowledgeGraphNode = {
  id: string;
  source: MemoryKnowledgeGraphNode;
  clusterKey: MemoryGraphClusterKey;
  clusterLabel: string;
  x: number;
  y: number;
  z: number;
};

export type MemoryGraphLayout = {
  nodes: PositionedMemoryKnowledgeGraphNode[];
  clusters: MemoryGraphCluster[];
};

type ClusterDefinition = Omit<MemoryGraphCluster, "nodeIds">;

const CLUSTERS: readonly ClusterDefinition[] = [
  { key: "workspace", label: "项目与团队", center: { x: -7, y: 7, z: -3 } },
  { key: "agents", label: "Agent 与私有记忆", center: { x: -6, y: 0, z: 5 } },
  { key: "knowledge", label: "知识与概念", center: { x: 2, y: 4, z: -5 } },
  { key: "sources", label: "知识来源", center: { x: 7, y: -2, z: 3 } },
  { key: "operations", label: "运行与扩展", center: { x: -1, y: -5, z: -4 } },
] as const;

const TYPE_CLUSTER: Record<string, MemoryGraphClusterKey> = {
  project: "workspace",
  team: "workspace",
  agent: "agents",
  agent_private_memory: "agents",
  knowledge_base: "knowledge",
  knowledge_item: "knowledge",
  refinement_proposal: "knowledge",
  rating_suggestion: "knowledge",
  tag: "knowledge",
  concept: "knowledge",
  source_artifact: "sources",
  knowledge_batch: "sources",
  runtime_scene: "operations",
  evolution: "operations",
  supervision: "operations",
};

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const CLUSTER_PHASE: Record<MemoryGraphClusterKey, number> = {
  workspace: 0.3,
  agents: 1.1,
  knowledge: 2.2,
  sources: 3.35,
  operations: 4.5,
};

function compareIds(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function clusterForType(type: string): MemoryGraphClusterKey {
  return TYPE_CLUSTER[type] ?? "operations";
}

function radiusForCount(count: number): number {
  return count <= 1 ? 0 : 1.35 + Math.cbrt(count) * 0.7;
}

function resolveClusterCenters(
  definitions: readonly ClusterDefinition[],
  counts: ReadonlyMap<MemoryGraphClusterKey, number>,
): Map<MemoryGraphClusterKey, { x: number; y: number; z: number }> {
  const populated = definitions.filter((cluster) => (counts.get(cluster.key) ?? 0) > 0);
  const centers = new Map(populated.map((cluster) => [cluster.key, cluster.center]));
  if (populated.length < 2) return centers;

  const centroid = populated.reduce(
    (sum, cluster) => ({
      x: sum.x + cluster.center.x / populated.length,
      y: sum.y + cluster.center.y / populated.length,
      z: sum.z + cluster.center.z / populated.length,
    }),
    { x: 0, y: 0, z: 0 },
  );
  let nearest = Number.POSITIVE_INFINITY;
  for (let left = 0; left < populated.length; left += 1) {
    for (let right = left + 1; right < populated.length; right += 1) {
      const deltaX = populated[left].center.x - populated[right].center.x;
      const deltaY = populated[left].center.y - populated[right].center.y;
      nearest = Math.min(nearest, Math.hypot(deltaX, deltaY, populated[left].center.z - populated[right].center.z));
    }
  }

  const largestRadius = Math.max(
    ...populated.map((cluster) => radiusForCount(counts.get(cluster.key) ?? 0)),
  );
  const desiredGap = 2 * (largestRadius + 1.35) + 3.5;
  const spacingScale = Math.max(1, desiredGap / Math.max(1, nearest));

  for (const cluster of populated) {
    centers.set(cluster.key, {
      x: centroid.x + (cluster.center.x - centroid.x) * spacingScale,
      y: centroid.y + (cluster.center.y - centroid.y) * spacingScale,
      z: centroid.z + (cluster.center.z - centroid.z) * spacingScale,
    });
  }
  return centers;
}

/**
 * Assigns stable display coordinates without mutating the API nodes. The server
 * DTO remains the source of IDs, node types, edge endpoints, relation labels,
 * and metadata; positions and topic clusters are presentation-only.
 */
export function layoutMemoryKnowledgeGraph(
  nodes: readonly MemoryKnowledgeGraphNode[],
  edges: readonly MemoryKnowledgeGraphEdge[],
): MemoryGraphLayout {
  const grouped = new Map<MemoryGraphClusterKey, MemoryKnowledgeGraphNode[]>(
    CLUSTERS.map((cluster) => [cluster.key, []]),
  );
  const nodeIds = new Set(nodes.map((node) => node.id));
  const degree = new Map<string, number>(nodes.map((node) => [node.id, 0]));

  for (const edge of edges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue;
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }

  for (const node of nodes) {
    grouped.get(clusterForType(node.type))?.push(node);
  }
  const counts = new Map([...grouped.entries()].map(([key, members]) => [key, members.length]));
  const centers = resolveClusterCenters(CLUSTERS, counts);
  const positioned: PositionedMemoryKnowledgeGraphNode[] = [];
  const clusters: MemoryGraphCluster[] = [];

  for (const definition of CLUSTERS) {
    const members = [...(grouped.get(definition.key) ?? [])].sort((left, right) => {
      const degreeDelta = (degree.get(right.id) ?? 0) - (degree.get(left.id) ?? 0);
      return degreeDelta || compareIds(left.id, right.id);
    });
    if (members.length === 0) continue;
    const center = centers.get(definition.key) ?? definition.center;

    clusters.push({
      ...definition,
      center: { ...center },
      nodeIds: members.map((node) => node.id),
    });

    members.forEach((source, index) => {
      // A spherical distribution gives every topic genuine depth. Small radial
      // variation avoids a hollow shell without piling nodes at the center.
      const angle = CLUSTER_PHASE[definition.key] + index * GOLDEN_ANGLE;
      const vertical = 1 - 2 * (index + 0.5) / members.length;
      const radial = Math.sqrt(Math.max(0, 1 - vertical * vertical));
      const radius = radiusForCount(members.length) * (index % 3 === 0 ? 0.82 : 1);
      positioned.push({
        id: source.id,
        source,
        clusterKey: definition.key,
        clusterLabel: definition.label,
        x: center.x + Math.cos(angle) * radial * radius,
        y: center.y + vertical * radius,
        z: center.z + Math.sin(angle) * radial * radius,
      });
    });
  }

  positioned.sort((left, right) => compareIds(left.id, right.id));
  return { nodes: positioned, clusters };
}
