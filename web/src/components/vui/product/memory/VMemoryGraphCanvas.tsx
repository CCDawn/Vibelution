import { lazy, Suspense } from "react";

import type {
  MemoryKnowledgeGraphEdge,
  MemoryKnowledgeGraphNode,
} from "../../../../api/types";
import { VSurface } from "../../primitives/VSurface";
import styles from "./VMemoryGraphCanvas.styles";

export type VMemoryGraphCanvasProps = {
  nodes: MemoryKnowledgeGraphNode[];
  edges: MemoryKnowledgeGraphEdge[];
  selectedNodeId: string;
  onSelectNode: (id: string) => void;
  fallbackText: string;
  flat?: boolean;
  focusToken?: number;
  highlightIds?: string[];
  onSelectEdge?: (id: string) => void;
};

const LazyShadcnMemoryGraphCanvas = lazy(async () => {
  const renderer = await import("../../renderers/shadcn/memory/ShadcnMemoryGraphCanvas");
  return { default: renderer.ShadcnMemoryGraphCanvas };
});

/**
 * VUI product API for the read-only memory knowledge graph. Three.js and its
 * controls stay behind the shadcn renderer's lazy boundary.
 */
export function VMemoryGraphCanvas(props: VMemoryGraphCanvasProps) {
  return (
    <VSurface
      as="section"
      aria-label="记忆知识图谱"
      data-vui="memory-graph-canvas"
      tone="workspace"
      elevation="flat"
      padding="none"
      className={styles.root}
    >
      <Suspense fallback={<div className={styles.loading} role="status">正在载入图谱画布…</div>}>
        <LazyShadcnMemoryGraphCanvas {...props} />
      </Suspense>
    </VSurface>
  );
}
