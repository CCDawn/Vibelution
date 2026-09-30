import { Focus, Layers3, List, Maximize2, Network, Search, X } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { MemoryKnowledgeGraphNode, MemoryKnowledgeGraphPayload } from "../api/types";
import { PaneHeightResizeHandle } from "../components/layout/PaneHeightResizeHandle";
import type { PaneHeightSpec } from "../components/layout/paneHeightPersistence";
import { usePersistedPaneHeight } from "../components/layout/usePersistedPaneHeight";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VButton, VCanvasWorkbenchPage, VNativeInput, VSurface } from "../components/vui";
import { GRAPH_NODE_TYPE_LABELS, MemoryGraphNodeInspectorPanel, type MemoryGraphNodeInspectorCopy, type MemoryGraphRelation } from "./MemoryGraphNodeInspectorPanel";
import { memoryGraphSlice } from "./memory/memoryGraphSlice";
import { MemoryGraphRelationInspector } from "./MemoryGraphRelationInspector";
import styles from "./MemoryGraphViewPanel.styles";
const MemoryGraphCanvas = lazy(() => import("./MemoryGraphCanvas").then(module => ({ default: module.MemoryGraphCanvas })));

export type { MemoryGraphRelation } from "./MemoryGraphNodeInspectorPanel";

// Wave 6B: the graph node list keeps a shared persisted height pane.
const MEMORY_GRAPH_NODE_LIST_PANE: PaneHeightSpec = {
  id: "graph-node-list",
  defaultHeight: 168,
  minHeight: 96,
  maxHeight: 360,
};
const MEMORY_GRAPH_HEIGHT_PANES: PaneHeightSpec[] = [MEMORY_GRAPH_NODE_LIST_PANE];

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
  isGraphLoading?: boolean;
  graphError?: string;
  onRetryGraph?: () => void;
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

export function MemoryGraphViewPanel(props: MemoryGraphViewPanelProps) {
  const { copy, graphPayload, graphSearchText, activeGraphNodeType, graphTypeEntries, selectedGraphNode,
    onGraphSearchTextChange, onActiveGraphNodeTypeChange, onClearGraphFilters, onSelectGraphNode, onFocusGraphNode } = props;
  const [flat, setFlat] = useState(false);
  const [detailOpen, setDetailOpen] = useState(Boolean(selectedGraphNode));
  const [matchOnly, setMatchOnly] = useState(false);
  const [depth, setDepth] = useState(0);
  const [edgeId, setEdgeId] = useState("");
  const [showList, setShowList] = useState(false);
  const [focusToken, setFocusToken] = useState(0);
  const lastTrigger = useRef<HTMLElement | null>(null);
  const selectedId = selectedGraphNode?.id ?? "";
  const {
    registerSplitContainer: registerGraphContainer,
    paneVariablesStyle: graphPaneVariablesStyle,
    heights: graphHeights,
    draggingPaneId: graphHeightDraggingPaneId,
    startResize: startGraphHeightResize,
    onResizeKeyDown: onGraphHeightResizeKeyDown,
  } = usePersistedPaneHeight({ layoutId: WORKBENCH_LAYOUT_IDS.memory, panes: MEMORY_GRAPH_HEIGHT_PANES });
  const graphNodeListHeight = graphHeights["graph-node-list"] ?? MEMORY_GRAPH_NODE_LIST_PANE.defaultHeight;
  const center = depth ? selectedId : "";
  const slice = useMemo(() => memoryGraphSlice(graphPayload?.nodes ?? [], graphPayload?.edges ?? [],
    graphSearchText, activeGraphNodeType, { matchOnly, center, depth }),
  [graphPayload?.nodes, graphPayload?.edges, graphSearchText, activeGraphNodeType, matchOnly, center, depth]);
  const highlightIds = useMemo(() => graphSearchText.trim() ? slice.matches.map(node => node.id) : [], [slice.matches, graphSearchText]);
  const close = () => { setDetailOpen(false); setEdgeId(""); if (lastTrigger.current?.isConnected) lastTrigger.current.focus(); };
  const select = (id: string) => {
    lastTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    onSelectGraphNode(id); setDetailOpen(true); setEdgeId("");
  };
  const navigate = (id: string) => { setDepth(0); setMatchOnly(false); setEdgeId(""); onFocusGraphNode(id); setDetailOpen(true); };
  const reset = () => { onClearGraphFilters(); onSelectGraphNode(""); setDepth(0); setMatchOnly(false); close(); setFocusToken(value => value + 1); };
  useEffect(() => { setEdgeId(""); if (selectedId) setDetailOpen(true); }, [selectedId]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") { setDetailOpen(false); setEdgeId(""); lastTrigger.current?.focus(); } };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }, []);
  const clearSelection = () => { onSelectGraphNode(""); setDepth(0); setEdgeId(""); setDetailOpen(false); };
  const edge = graphPayload?.edges.find(item => item.id === edgeId);
  const inspector = (selectedGraphNode || edge) && detailOpen ? <div className={styles.atlasInspector} data-vui-region="memory-graph-inspector">
    <div className={styles.atlasDetailHeader}><span>{edge ? "关系与依据" : copy.graphSelectedNode}</span>
      <VButton aria-label="关闭详情" onClick={close} icon={<X size={16} />} variant="ghost" /></div>
    {edge ? <MemoryGraphRelationInspector edge={edge} nodes={graphPayload?.nodes ?? []} onNavigate={navigate} onBack={() => { if (!selectedGraphNode) navigate(edge.source); else setEdgeId(""); }} /> :
      selectedGraphNode ? <MemoryGraphNodeInspectorPanel copy={copy} selectedGraphNode={selectedGraphNode}
        selectedGraphChildren={props.selectedGraphChildren} selectedGraphRelations={props.selectedGraphRelations}
        selectedGraphDetailItems={props.selectedGraphDetailItems} isGraphNodeDetailFetching={props.isGraphNodeDetailFetching}
        formatTimestamp={props.formatTimestamp} onFocusGraphNode={navigate} onSelectRelation={setEdgeId} /> : null}
  </div> : undefined;
  return <VCanvasWorkbenchPage hideHeader title={copy.knowledgeGraph} ariaLabel={copy.knowledgeGraph}
    className={styles.graphWorkspace} domainRecipe="memory-knowledge-workbench" data-vui-recipe="memory-knowledge-workbench"
    data-vui-region="memory-graph-workspace" layoutId={WORKBENCH_LAYOUT_IDS.memory}
    resize={{ sidebar: { id: "filters", defaultWidth: 224, minWidth: 190, maxWidth: 340 }, aside: { id: "inspector", defaultWidth: 336, minWidth: 280, maxWidth: 440 } }}
    responsive={{ enabled: true, rail: { label: "搜索与筛选" }, inspector: { label: "节点详情", open: detailOpen, onOpenChange: setDetailOpen, narrowPlacement: "bottom" } }}
    railClassName={styles.atlasRail} canvasClassName={styles.atlasCanvas} inspectorClassName={styles.atlasInspectorHost}
    rail={<VSurface as="div" tone="rail" padding="none" className={styles.atlasRailInner} data-vui-region="memory-graph-filters">
      <div><p className={styles.atlasEyebrow}>MEMORY ATLAS</p><h2 className={styles.railTitle}>{copy.knowledgeGraph}</h2></div>
      <label className={styles.atlasSearch}><Search size={16} /><VNativeInput aria-label={copy.graphSearchPlaceholder} placeholder={copy.graphSearchPlaceholder}
        value={graphSearchText} onChange={event => { onGraphSearchTextChange(event.target.value); clearSelection(); }} />
        {graphSearchText && <VButton variant="ghost" aria-label="清空搜索" icon={<X size={14} />} onClick={() => { onGraphSearchTextChange(""); clearSelection(); }} />}</label>
      <div><p className={styles.atlasEyebrow}>{copy.graphNodeTypes}</p><div className={styles.atlasFilters}>
        {graphTypeEntries.map(([type, count]) => <VButton key={type} variant="ghost" contentLayout="plain" aria-pressed={activeGraphNodeType === type}
          data-active={activeGraphNodeType === type} onClick={() => { onActiveGraphNodeTypeChange(activeGraphNodeType === type ? "" : type); clearSelection(); }}>
          <span>{GRAPH_NODE_TYPE_LABELS[type] ?? type}</span><span className={styles.typeCount}>{count}</span>
        </VButton>)}</div></div>
      {(graphSearchText || activeGraphNodeType) && <VButton variant="ghost" className={styles.graphClearFocusButton} onClick={reset}>{copy.graphClearFocus}</VButton>}
      {graphSearchText && <div className={styles.searchResults}><span className={styles.atlasEyebrow}>{slice.matches.length} 条匹配</span>{slice.matches.slice(0, 20).map(node =>
        <VButton key={node.id} variant="ghost" className={styles.searchResult} onClick={() => select(node.id)}>{node.label}</VButton>)}</div>}
      <p className={styles.accessNote}>{copy.graphReadOnly} · {copy.graphAcl}</p>
    </VSurface>}
    canvas={<div ref={registerGraphContainer} className={styles.atlasMain} style={graphPaneVariablesStyle} data-vui-region="memory-graph-canvas">
      <div className={styles.atlasHeading}><div><p className={styles.atlasEyebrow}>MEMORY ATLAS</p><h2 className={styles.canvasTitle}>{copy.knowledgeGraph}</h2><p className={styles.canvasHint}>从一个线索开始，沿着关系找到依据。</p></div>
        <div className={styles.viewModes}><VButton variant="ghost" aria-pressed={!flat} onClick={() => setFlat(false)} icon={<Layers3 size={14} />}>3D</VButton><VButton variant="ghost" aria-pressed={flat} onClick={() => setFlat(true)} icon={<Network size={14} />}>平面</VButton></div></div>
      <div className={styles.atlasStage}>
        {!graphPayload && props.isGraphLoading ? <div role="status" className={styles.atlasEmpty}>{copy.loading}</div> : !graphPayload && props.graphError ? <div role="alert" className={styles.atlasEmpty}><strong>图谱加载失败</strong><p>{props.graphError}</p><VButton onClick={props.onRetryGraph}>重试</VButton></div> : slice.nodes.length ? <Suspense fallback={<div role="status" className={styles.atlasEmpty}>{copy.loading}</div>}>
          <MemoryGraphCanvas nodes={slice.nodes} edges={slice.edges} selectedNodeId={selectedId} onSelectNode={select}
            fallbackText={copy.graphCanvasFallback} flat={flat} focusToken={focusToken} highlightIds={highlightIds}
            onSelectEdge={id => { setEdgeId(id); setDetailOpen(true); }} />
        </Suspense> : <div role="status" className={styles.atlasEmpty}><Network size={28} /><strong>{graphSearchText || activeGraphNodeType ? "没有找到相关内容" : "当前范围还没有可显示的图谱"}</strong><p>仅展示当前权限范围内已加载的节点。</p></div>}
        <div className={styles.atlasContext}>
          {graphSearchText && <div className={styles.atlasActionRow}><span>{slice.matches.length} 条匹配 · {Math.max(0, slice.nodes.length - slice.matches.length)} 条关联</span><VButton variant="ghost" aria-pressed={matchOnly} onClick={() => { setMatchOnly(value => !value); clearSelection(); }}>{matchOnly ? "恢复关联上下文" : "仅看匹配项"}</VButton></div>}
          {selectedGraphNode && <div className={styles.atlasActionRow}><span className={styles.selectedTitle}>{selectedGraphNode.label}</span><VButton variant="ghost" onClick={() => { setDepth(value => value ? 0 : 1); onClearGraphFilters(); }}>{depth ? "返回全部" : "只看相关"}</VButton>
            {depth === 1 && <VButton variant="ghost" onClick={() => setDepth(2)}>再展开一层</VButton>}{!detailOpen && <VButton variant="ghost" onClick={() => setDetailOpen(true)}>查看详情</VButton>}
            <VButton variant="ghost" aria-label="取消选择" icon={<X size={14} />} onClick={clearSelection} /></div>}
        </div>
        <div className={styles.atlasTools}><VButton variant="ghost" aria-label="恢复全景" icon={<Maximize2 size={16} />} onClick={reset} /><VButton variant="ghost" aria-label="聚焦选中节点" isDisabled={!selectedId} icon={<Focus size={16} />} onClick={() => setFocusToken(value => value + 1)} /><VButton variant="ghost" aria-label="节点列表" aria-pressed={showList} icon={<List size={16} />} onClick={() => setShowList(value => !value)} /></div>
      </div>
      {graphPayload && props.graphError && <p role="alert" className={styles.refreshError}>刷新失败，当前显示上次加载的图谱。<VButton variant="ghost" onClick={props.onRetryGraph}>重试</VButton></p>}
      <div className={styles.atlasFooter}><span>{copy.graphVisibleNodes}: {slice.nodes.length} · {copy.graphVisibleEdges}: {slice.edges.length}{graphPayload?.summary.truncated ? " · 已达到加载上限" : ""}</span><span>{flat ? "拖动平移" : "360° 拖动环绕 · 右键平移"} · 滚轮缩放</span></div>
      {showList && <>
        <PaneHeightResizeHandle label={copy.graphNodes} valueNow={graphNodeListHeight}
          valueMin={MEMORY_GRAPH_NODE_LIST_PANE.minHeight} valueMax={MEMORY_GRAPH_NODE_LIST_PANE.maxHeight}
          active={graphHeightDraggingPaneId === "graph-node-list"} className={styles.graphNodeListResizeHandle}
          onPointerDown={event => startGraphHeightResize("graph-node-list", event, { direction: 1 })}
          onKeyDown={event => onGraphHeightResizeKeyDown("graph-node-list", event, { direction: 1 })} />
        <div className={styles.atlasNodeList} data-vui-region="memory-graph-node-list">{slice.nodes.map(node => <VButton key={node.id} variant="ghost" onClick={() => select(node.id)}>{node.label}</VButton>)}</div>
      </>}
    </div>} inspector={inspector} />;
}
