import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../api/types";

type WorkerRequest = {
  type: "layout";
  nodes: MemoryKnowledgeGraphNode[];
  edges: MemoryKnowledgeGraphEdge[];
};

type LayoutNode = {
  id: string;
  x: number;
  y: number;
  z: number;
};

const TYPE_RADIUS: Record<string, number> = {
  project: 0,
  team: 7,
  agent: 12,
  agent_private_memory: 16,
  knowledge_base: 20,
  knowledge_item: 24,
  source_artifact: 28,
  refinement_proposal: 22,
  knowledge_batch: 24,
  rating_suggestion: 26,
  runtime_scene: 34,
  evolution: 30,
  supervision: 30,
  tag: 28,
};

self.onmessage = (event: MessageEvent<WorkerRequest>) => {
  if (event.data?.type !== "layout") {
    return;
  }
  const nodes = event.data.nodes ?? [];
  const edges = event.data.edges ?? [];
  const degree = new Map<string, number>();
  for (const edge of edges) {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }
  const byType = new Map<string, MemoryKnowledgeGraphNode[]>();
  for (const node of nodes) {
    const list = byType.get(node.type) ?? [];
    list.push(node);
    byType.set(node.type, list);
  }
  const positions: LayoutNode[] = [];
  const typeEntries = Array.from(byType.entries());
  typeEntries.forEach(([type, group], typeIndex) => {
    const radius = TYPE_RADIUS[type] ?? 12 + typeIndex * 1.8;
    const vertical = (typeIndex - typeEntries.length / 2) * 1.55;
    group.forEach((node, index) => {
      const count = Math.max(1, group.length);
      const angle = (index / count) * Math.PI * 2 + typeIndex * 0.47;
      const layerSpread = Math.min(5.5, Math.sqrt(count) * 1.35);
      const degreeBoost = Math.min(4.8, Math.sqrt(degree.get(node.id) ?? 0));
      positions.push({
        id: node.id,
        x: Math.cos(angle) * (radius + layerSpread + degreeBoost),
        y: vertical + Math.sin(angle * 1.7) * 3.2,
        z: Math.sin(angle) * (radius + layerSpread + degreeBoost),
      });
    });
  });
  self.postMessage({ type: "layout", positions });
};
