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
  team: 5.5,
  agent: 8.5,
  agent_private_memory: 10.5,
  knowledge_base: 13,
  knowledge_item: 17,
  source_artifact: 20,
  refinement_proposal: 15,
  knowledge_batch: 16,
  rating_suggestion: 18,
  runtime_scene: 22,
  evolution: 24,
  supervision: 24,
  tag: 19,
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
    const vertical = (typeIndex - typeEntries.length / 2) * 1.2;
    group.forEach((node, index) => {
      const count = Math.max(1, group.length);
      const angle = (index / count) * Math.PI * 2 + typeIndex * 0.47;
      const degreeBoost = Math.min(3.8, Math.sqrt(degree.get(node.id) ?? 0));
      positions.push({
        id: node.id,
        x: Math.cos(angle) * (radius + degreeBoost),
        y: vertical + Math.sin(angle * 1.7) * 2.4,
        z: Math.sin(angle) * (radius + degreeBoost),
      });
    });
  });
  self.postMessage({ type: "layout", positions });
};
