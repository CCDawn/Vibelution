import { Search, XCircle } from "lucide-react";
import { lazy, Suspense, type CSSProperties } from "react";

import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode, MemoryKnowledgeGraphPayload } from "../api/types";
import { PaneHeightResizeHandle } from "../components/layout/PaneHeightResizeHandle";
import type { PaneHeightSpec } from "../components/layout/paneHeightPersistence";
import { usePersistedPaneHeight } from "../components/layout/usePersistedPaneHeight";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VButton, VMetricStrip, VNativeInput, VSection, VSurface } from "../components/vui";
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

const MEMORY_GRAPH_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.memory;
const MEMORY_GRAPH_NODE_LIST_PANE: PaneHeightSpec = {
  id: "graph-node-list",
  defaultHeight: 168,
  minHeight: 96,
  maxHeight: 360,
};
const MEMORY_GRAPH_HEIGHT_PANES: PaneHeightSpec[] = [MEMORY_GRAPH_NODE_LIST_PANE];

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
  const {
    heights: graphHeights,
    draggingPaneId: graphHeightDraggingPaneId,
    startResize: startGraphHeightResize,
    onResizeKeyDown: onGraphHeightResizeKeyDown,
  } = usePersistedPaneHeight({
    layoutId: MEMORY_GRAPH_LAYOUT_ID,
    panes: MEMORY_GRAPH_HEIGHT_PANES,
  });
  const graphNodeListHeight = graphHeights["graph-node-list"] ?? MEMORY_GRAPH_NODE_LIST_PANE.defaultHeight;
  const graphCanvasStyle = {
    ["--memory-graph-node-list-height" as string]: `${graphNodeListHeight}px`,
  } as CSSProperties;

  return (
    <>
      <VMetricStrip
        ariaLabel={copy.knowledgeGraph}
        metrics={[
          { id: "visible-nodes", label: copy.graphVisibleNodes, value: filteredGraphNodes.length, detail: `${copy.graphNodes}: ${graphPayload?.summary.nodeCount ?? 0}` },
          { id: "visible-edges", label: copy.graphVisibleEdges, value: filteredGraphEdges.length, detail: `${copy.graphEdges}: ${graphPayload?.summary.edgeCount ?? 0}` },
          { id: "gpu", label: copy.graphGpu, value: graphPayload?.operatingBoundary.gpuPreferred ? copy.yes : copy.no },
          { id: "worker", label: copy.graphWorker, value: graphPayload?.operatingBoundary.layoutWorker ? copy.yes : copy.no },
          { id: "readonly", label: copy.graphReadOnly, value: graphPayload?.operatingBoundary.readOnly ? copy.yes : copy.no },
          { id: "acl", label: copy.graphAcl, value: graphPayload?.operatingBoundary.honorsKnowledgeAcl ? copy.yes : copy.no },
        ]}
      />

      <div
        className={`${styles.workspace} ${styles.graphWorkspace}`}
        data-vui-recipe="memory-knowledge-workbench"
        data-vui-layout-id={MEMORY_GRAPH_LAYOUT_ID}
        data-vui-region="memory-graph-workspace"
      >
        <VSurface
          as="aside"
          className={styles.sourcePanel}
          elevation="panel"
          tone="rail"
          data-vui-region="memory-graph-filters"
        >
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
          <VSection className={styles.managementPanel} title={copy.graphNodes} eyebrow={copy.graphNodeTypes}>
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
          </VSection>
        </VSurface>

        <VSurface
          as="main"
          className={styles.graphCanvasPanel}
          elevation="panel"
          tone="rail"
          style={graphCanvasStyle}
          data-vui-region="memory-graph-canvas"
        >
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
          <PaneHeightResizeHandle
            label={copy.graphNodes}
            valueNow={graphNodeListHeight}
            valueMin={MEMORY_GRAPH_NODE_LIST_PANE.minHeight}
            valueMax={MEMORY_GRAPH_NODE_LIST_PANE.maxHeight}
            active={graphHeightDraggingPaneId === "graph-node-list"}
            className={styles.graphNodeListResizeHandle}
            onPointerDown={(event) => startGraphHeightResize("graph-node-list", event, { direction: 1 })}
            onKeyDown={(event) => onGraphHeightResizeKeyDown("graph-node-list", event, { direction: 1 })}
          />
          <div className={styles.graphNodeList} data-vui-region="memory-graph-node-list">
            {filteredGraphNodes.slice(0, 80).map((node) => (
              <VButton
                key={node.id}
                type="button"
                contentLayout="plain"
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
        </VSurface>

        <div data-vui-region="memory-graph-inspector">
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
      </div>
    </>
  );
}
