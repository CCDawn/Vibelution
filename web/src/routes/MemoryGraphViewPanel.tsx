import { Search, XCircle } from "lucide-react";
import { lazy, Suspense } from "react";

import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode, MemoryKnowledgeGraphPayload } from "../api/types";
import { VButton, VNativeInput } from "../components/vui";
import {
  GRAPH_NODE_TYPE_LABELS,
  MemoryGraphNodeInspectorPanel,
  type MemoryGraphNodeInspectorCopy,
  type MemoryGraphRelation,
} from "./MemoryGraphNodeInspectorPanel";
import styles from "./MemoryGraphViewPanel.styles";

const MemoryGraphCanvas = lazy(() => import("./MemoryGraphCanvas").then((module) => ({ default: module.MemoryGraphCanvas })));

export type { MemoryGraphRelation } from "./MemoryGraphNodeInspectorPanel";

type MemoryGraphContentItem = MemoryKnowledgeGraphNode["contentItems"][number];

export type MemoryGraphViewPanelCopy = MemoryGraphNodeInspectorCopy & {
  graphVisibleNodes: string;
  graphNodes: string;
  graphVisibleEdges: string;
  graphEdges: string;
  graphGpu: string;
  yes: string;
  no: string;
  graphWorker: string;
  graphReadOnly: string;
  graphAcl: string;
  knowledgeGraph: string;
  filters: string;
  graphSearchPlaceholder: string;
  graphNodeTypes: string;
  graphClearFocus: string;
  loading: string;
  graphInteractionHint: string;
  graphCanvasFallback: string;
};

type MemoryGraphViewPanelProps = {
  copy: MemoryGraphViewPanelCopy;
  graphPayload: MemoryKnowledgeGraphPayload | undefined;
  filteredGraphNodes: MemoryKnowledgeGraphNode[];
  filteredGraphEdges: MemoryKnowledgeGraphEdge[];
  graphSearchText: string;
  activeGraphNodeType: string;
  graphTypeEntries: Array<[string, number]>;
  selectedGraphNode: MemoryKnowledgeGraphNode | null;
  selectedGraphChildren: MemoryKnowledgeGraphNode[];
  selectedGraphRelations: {
    incoming: MemoryGraphRelation[];
    outgoing: MemoryGraphRelation[];
  };
  selectedGraphDetailItems: MemoryGraphContentItem[];
  isGraphNodeDetailFetching: boolean;
  formatTimestamp: (value: string) => string;
  onGraphSearchTextChange: (value: string) => void;
  onActiveGraphNodeTypeChange: (value: string) => void;
  onClearGraphFilters: () => void;
  onSelectGraphNode: (nodeId: string) => void;
  onFocusGraphNode: (nodeId: string) => void;
};

export function MemoryGraphViewPanel({
  copy,
  graphPayload,
  filteredGraphNodes,
  filteredGraphEdges,
  graphSearchText,
  activeGraphNodeType,
  graphTypeEntries,
  selectedGraphNode,
  selectedGraphChildren,
  selectedGraphRelations,
  selectedGraphDetailItems,
  isGraphNodeDetailFetching,
  formatTimestamp,
  onGraphSearchTextChange,
  onActiveGraphNodeTypeChange,
  onClearGraphFilters,
  onSelectGraphNode,
  onFocusGraphNode,
}: MemoryGraphViewPanelProps) {
  return (
    <>
      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.graphVisibleNodes}</span>
          <strong>{filteredGraphNodes.length}</strong>
          <small>{copy.graphNodes}: {graphPayload?.summary.nodeCount ?? 0}</small>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.graphVisibleEdges}</span>
          <strong>{filteredGraphEdges.length}</strong>
          <small>{copy.graphEdges}: {graphPayload?.summary.edgeCount ?? 0}</small>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.graphGpu}</span>
          <strong>{graphPayload?.operatingBoundary.gpuPreferred ? copy.yes : copy.no}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.graphWorker}</span>
          <strong>{graphPayload?.operatingBoundary.layoutWorker ? copy.yes : copy.no}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.graphReadOnly}</span>
          <strong>{graphPayload?.operatingBoundary.readOnly ? copy.yes : copy.no}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.graphAcl}</span>
          <strong>{graphPayload?.operatingBoundary.honorsKnowledgeAcl ? copy.yes : copy.no}</strong>
        </section>
      </div>

      <div className={`${styles.workspace} ${styles.graphWorkspace}`}>
        <aside className={styles.sourcePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.knowledgeGraph}</p>
              <h2>{copy.filters}</h2>
            </div>
            <span className={styles.countPill}>{filteredGraphNodes.length}</span>
          </div>
          <label className={styles.searchBox}>
            <Search size={15} />
            <VNativeInput
              value={graphSearchText}
              onChange={(event) => onGraphSearchTextChange(event.target.value)}
              placeholder={copy.graphSearchPlaceholder}
            />
          </label>
          <section className={styles.managementPanel}>
            <div className={styles.managementHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.graphNodeTypes}</p>
                <h2>{copy.graphNodes}</h2>
              </div>
            </div>
            <div className={styles.graphTypeList}>
              {graphTypeEntries.map(([type, count]) => (
                <VButton
                  key={type}
                  type="button"
                  data-active={activeGraphNodeType === type ? "true" : "false"}
                  data-node-type={type}
                  onClick={() => onActiveGraphNodeTypeChange(activeGraphNodeType === type ? "" : type)}
                >
                  <strong>{type}</strong>
                  <small>{count}</small>
                </VButton>
              ))}
            </div>
            {activeGraphNodeType || graphSearchText ? (
              <VButton
                type="button"
                className={styles.graphClearFocusButton}
                onClick={onClearGraphFilters}
              >
                <XCircle size={14} />
                {copy.graphClearFocus}
              </VButton>
            ) : null}
          </section>
        </aside>

        <main className={styles.graphCanvasPanel}>
          <div className={styles.graphCanvasToolbar}>
            <div>
              <p className={styles.panelEyebrow}>{copy.knowledgeGraph}</p>
              <strong>Three.js / WebGL / Worker</strong>
            </div>
            <span className={styles.graphInteractionHint} title={copy.graphInteractionHint}>
              {copy.graphReadOnly} · {copy.graphAcl}
            </span>
          </div>
          <Suspense fallback={<div className={styles.graphCanvasFallback}><strong>{copy.loading}</strong></div>}>
            <MemoryGraphCanvas
              nodes={filteredGraphNodes}
              edges={filteredGraphEdges}
              selectedNodeId={selectedGraphNode?.id ?? ""}
              onSelectNode={onSelectGraphNode}
              fallbackText={copy.graphCanvasFallback}
            />
          </Suspense>
          <div className={styles.graphNodeList}>
            {filteredGraphNodes.slice(0, 80).map((node) => (
              <VButton
                key={node.id}
                type="button"
                className={selectedGraphNode?.id === node.id ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
                data-node-type={node.type}
                data-agent-category={String(node.visual?.agentCategory || node.metadata?.agentCategory || "")}
                onClick={() => onSelectGraphNode(node.id)}
              >
                <span className={styles.graphNodeTypeMark}>{GRAPH_NODE_TYPE_LABELS[node.type] ?? node.type.slice(0, 10)}</span>
                <strong>{node.label}</strong>
                <small>{node.status || "-"}</small>
              </VButton>
            ))}
          </div>
        </main>

        <MemoryGraphNodeInspectorPanel
          copy={copy}
          selectedGraphNode={selectedGraphNode}
          selectedGraphChildren={selectedGraphChildren}
          selectedGraphRelations={selectedGraphRelations}
          selectedGraphDetailItems={selectedGraphDetailItems}
          isGraphNodeDetailFetching={isGraphNodeDetailFetching}
          formatTimestamp={formatTimestamp}
          onFocusGraphNode={onFocusGraphNode}
        />
      </div>
    </>
  );
}
