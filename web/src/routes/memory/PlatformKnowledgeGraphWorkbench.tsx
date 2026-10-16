import styles from "./PlatformKnowledgeGraphWorkbench.styles";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ArrowLeft, FileText, Globe2, Maximize2, Network, Search, ShieldCheck, X } from "lucide-react";
import { fetchPlatformKnowledgeGraph, fetchPlatformKnowledgeGraphNodeDetail, platformKnowledgeGraphKeys } from "../../api/memory";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../../api/types";
import { VButton, VCanvasWorkbenchPage, VMemoryGraphCanvas, VNativeInput, VSurface, VTabs } from "../../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { MemoryGraphRelationInspector } from "../MemoryGraphRelationInspector";
import { isAdministrativeRelation, isContentRelation, platformLayerLabels, platformSpatialOverview, platformTopicOverview, platformTopicSlice, relationLayer, topicBasisLabels, type PlatformRelationLayer } from "./platformKnowledgeGraphModel";

export function PlatformKnowledgeGraphWorkbench({ onAgentView }: { onAgentView: () => void }) {
  const [limit, setLimit] = useState(800);
  const [topicId, setTopicId] = useState("");
  const [layer, setLayer] = useState<PlatformRelationLayer>("knowledge");
  const [query, setQuery] = useState("");
  const [relationType, setRelationType] = useState("");
  const [candidates, setCandidates] = useState(false);
  const [administrative, setAdministrative] = useState(false);
  const [nodeId, setNodeId] = useState("");
  const [edgeId, setEdgeId] = useState("");
  const [detailRecords, setDetailRecords] = useState<{ nodes: MemoryKnowledgeGraphNode[]; edges: MemoryKnowledgeGraphEdge[] }>({ nodes: [], edges: [] });
  const [detailOpen, setDetailOpen] = useState(false);
  const [spatial, setSpatial] = useState(true);
  const [showSources, setShowSources] = useState(true);
  const [focusToken, setFocusToken] = useState(0);
  const graph = useQuery({ queryKey: platformKnowledgeGraphKeys.overview(limit), queryFn: ({ signal }) => fetchPlatformKnowledgeGraph({ limit, signal }), staleTime: 60_000 });
  const payload = graph.data;
  const detail = useQuery({ queryKey: platformKnowledgeGraphKeys.detail(nodeId), queryFn: ({ signal }) => fetchPlatformKnowledgeGraphNodeDetail(nodeId, { signal }), enabled: Boolean(nodeId), staleTime: 60_000 });
  const search = query.trim().toLocaleLowerCase();
  const matches = useMemo(() => search ? (payload?.nodes ?? []).filter(node => `${node.label} ${node.summary}`.toLocaleLowerCase().includes(search)) : [], [payload, search]);
  const eligible = useMemo(() => (payload?.edges ?? []).filter(edge => (relationLayer(edge) === layer || (spatial && layer === "knowledge" && showSources && relationLayer(edge) === "evidence")) && edge.type !== "topic_has_item" && (administrative || !isAdministrativeRelation(edge)) && (candidates || edge.metadata.status !== "candidate") && (!relationType || edge.label === relationType)), [payload, layer, candidates, relationType, administrative, spatial, showSources]);
  const overview = useMemo(() => payload ? platformTopicOverview(payload, eligible) : { nodes: [], edges: [] }, [payload, eligible]);
  const selectedSliceId = spatial ? "" : nodeId;
  const slice = useMemo(() => payload ? platformTopicSlice(payload, topicId, eligible, selectedSliceId) : { nodes: [], edges: [] }, [payload, topicId, eligible, selectedSliceId]);
  const spatialOverview = useMemo(() => payload ? platformSpatialOverview(payload, eligible) : { nodes: [], edges: [] }, [payload, eligible]);
  const spatialTopic = useMemo(() => payload ? platformSpatialOverview({ ...payload, nodes: slice.nodes, topics: payload.topics.filter(item => item.id === topicId) }, slice.edges) : { nodes: [], edges: [] }, [payload, slice, topicId]);
  const topic = payload?.topics.find(item => item.id === topicId);
  const knownNodes = [...(payload?.nodes ?? []), ...detailRecords.nodes];
  const selectedEdge = payload?.edges.find(edge => edge.id === edgeId) ?? detailRecords.edges.find(edge => edge.id === edgeId);
  const selectedNode = knownNodes.find(node => node.id === nodeId);
  // A detail response for a previously selected node is never used for the next node.
  const currentDetail = detail.data?.nodeId === nodeId ? detail.data : undefined;
  const legend = [...new Set((payload?.edges ?? []).filter(edge => relationLayer(edge) === layer && edge.type !== "topic_has_item" && (administrative || !isAdministrativeRelation(edge)) && (candidates || edge.metadata.status !== "candidate")).map(edge => edge.label))];
  const hasContentRelations = (payload?.edges ?? []).some(isContentRelation);
  const resetSelection = () => { setNodeId(""); setEdgeId(""); setDetailOpen(false); };
  const reset = () => { setTopicId(""); setQuery(""); setRelationType(""); setDetailRecords({ nodes: [], edges: [] }); resetSelection(); setFocusToken(value => value + 1); };
  const openTopic = (id: string) => { setTopicId(id); setQuery(""); setRelationType(""); resetSelection(); setFocusToken(value => value + 1); };
  const openNode = (id: string) => {
    const node = knownNodes.find(item => item.id === id);
    if (!node) return;
    const memberships = Array.isArray(node.metadata.topicIds) ? node.metadata.topicIds.filter((id): id is string => typeof id === "string") : [];
    const targetTopic = memberships.includes(topicId) ? topicId : String(node.metadata.topicId ?? memberships[0] ?? "");
    if (targetTopic && !spatial) setTopicId(targetTopic);
    setNodeId(id); setEdgeId(""); setQuery(""); setDetailOpen(true); setFocusToken(value => value + 1);
  };
  const openEdge = (edge: MemoryKnowledgeGraphEdge) => {
    if (currentDetail) setDetailRecords({ nodes: [currentDetail.node, ...currentDetail.relatedNodes], edges: currentDetail.edges });
    const from = knownNodes.find(node => node.id === edge.source) ?? currentDetail?.relatedNodes.find(node => node.id === edge.source);
    const to = knownNodes.find(node => node.id === edge.target) ?? currentDetail?.relatedNodes.find(node => node.id === edge.target);
    if (!spatial) { setTopicId(String(from?.metadata.topicId ?? to?.metadata.topicId ?? topicId)); setLayer(relationLayer(edge)); }
    setRelationType(""); setNodeId(""); setEdgeId(edge.id); setDetailOpen(true);
  };
  const matchingTopics = new Set(matches.map(node => String(node.metadata.topicId ?? node.id)));
  const overviewRecords = spatial ? spatialOverview : overview;
  const canvasNodes = useMemo(() => search ? overviewRecords.nodes.filter(node => matchingTopics.has(node.id) || matchingTopics.has(String(node.metadata.topicId)) || node.label.toLocaleLowerCase().includes(search)) : overviewRecords.nodes, [overviewRecords, search, payload]);
  const canvasNodeIds = new Set(canvasNodes.map(node => node.id));
  const visibleEdges = useMemo(() => topicId ? (spatial ? spatialTopic.edges : slice.edges) : overviewRecords.edges.filter(edge => canvasNodeIds.has(edge.source) && canvasNodeIds.has(edge.target)), [topicId, spatial, spatialTopic, slice, overviewRecords, canvasNodes]);
  const sourceLocation = (node: MemoryKnowledgeGraphNode) => {
    const source = node.metadata.sourceRef;
    const names: Record<string, string> = { url: "链接", pageRange: "页码", page: "页码", fileName: "文件", path: "文件位置", title: "标题", lineStart: "起始行", lineEnd: "结束行" };
    return source && typeof source === "object" ? Object.entries(source).filter(([, value]) => typeof value === "string" || typeof value === "number").map(([key, value]) => `${names[key] ?? key}: ${String(value)}`).join(" · ") : node.type === "official_research_ref" ? "此处是审核或科研引用记录，未附原文位置" : "";
  };
  const inspector = <VSurface tone="panel" padding="none" className={styles.inspector}>
    <div className={styles.detailHeader}><strong>{selectedEdge ? "关系与依据" : selectedNode ? "节点详情" : "平台知识全景"}</strong>{(selectedEdge || selectedNode) && <VButton variant="ghost" aria-label="清除详情选择" icon={<X size={14} />} onClick={resetSelection} />}</div>
    {selectedEdge ? <MemoryGraphRelationInspector edge={selectedEdge} nodes={knownNodes} onNavigate={openNode} onBack={() => openNode(selectedEdge.source)} /> : <div className={styles.detailContent}>
      {selectedNode ? <>
        <h2 className={styles.nodeTitle}>{selectedNode.label}</h2><p className={styles.nodeSummary}>{selectedNode.summary}</p>
        <dl className={styles.nodeMetadata}><dt className={styles.muted}>知识归属</dt><dd>{String(selectedNode.metadata.ownerLabel ?? knownNodes.find(node => ["team", "agent"].includes(node.type) && node.metadata.ownerId === selectedNode.metadata.ownerId)?.label ?? "平台知识目录")}</dd><dt className={styles.muted}>来源位置</dt><dd className={styles.breakWords}>{sourceLocation(selectedNode) || "当前节点不是来源记录"}</dd><dt className={styles.muted}>版本与审核</dt><dd className={styles.breakWords}>{[selectedNode.metadata.revision && `修订 ${selectedNode.metadata.revision}`, selectedNode.metadata.reviewedAt, selectedNode.metadata.capturedAt].filter(Boolean).map(String).join(" · ") || "未提供"}</dd></dl>
        <details className={styles.technical}><summary>内部标识与校验信息</summary><p className={styles.sourceHash}>节点标识：{selectedNode.id}</p>{Boolean(selectedNode.metadata.sourceHash) && <p className={styles.sourceHash}>来源哈希：{String(selectedNode.metadata.sourceHash)}</p>}</details>
        <p className={styles.metadataBoundary}>当前管理图谱读取正式知识元数据和来源定位，不提供私有记忆正文或来源原文。</p>
        {detail.isFetching && <p role="status" className={styles.loadingDetail}>正在核对关联记录…</p>}
        {detail.error && <div role="alert" className={styles.loadingDetail}>详情加载失败：{detail.error.message}<VButton variant="ghost" onClick={() => void detail.refetch()}>重试</VButton></div>}
        {currentDetail?.summaryCounts?.truncated && <p role="status" className={styles.truncatedDetail}>详情关联已达加载上限。</p>}
        <h3 className={styles.relationHeading}>相关关系</h3>
        <div className={styles.relationList}>{(currentDetail?.edges ?? payload?.edges ?? []).filter(edge => (edge.source === nodeId || edge.target === nodeId) && (administrative || !isAdministrativeRelation(edge)) && (candidates || edge.metadata.status !== "candidate")).map(edge => <VButton key={edge.id} variant="ghost" className={styles.relationButton} onClick={() => openEdge(edge)}>{edge.label} → {knownNodes.find(node => node.id === (edge.source === nodeId ? edge.target : edge.source))?.label ?? currentDetail?.relatedNodes.find(node => node.id === (edge.source === nodeId ? edge.target : edge.source))?.label ?? "关联记录"}</VButton>)}</div>
      </> : <><Globe2 size={28} className={styles.overviewIcon} /><h2 className={styles.overviewTitle}>从全景找到知识</h2><p className={styles.overviewSummary}>选择星域阅读资料标题与摘要，再沿已记录的关系查看来源。</p><p className={styles.overviewHint}>主题按内容标签、标题关键词或知识库分组，进入主题可查看分组依据。分组和空间距离都不表示因果或支持关系。</p><p className={styles.boundaryHint}>全平台正式知识管理范围，排除 Agent 私有记忆文件、待审核内容和原始对话。仅本机授权管理员可访问。</p></>}
    </div>}
  </VSurface>;
  return <VCanvasWorkbenchPage hideHeader title="平台知识图谱" ariaLabel="平台知识图谱" domainRecipe="memory-knowledge-workbench" layoutId={WORKBENCH_LAYOUT_IDS.memory} className={styles.workspace}
    resize={{ sidebar: { id: "filters", defaultWidth: 224, minWidth: 190, maxWidth: 340 }, aside: { id: "inspector", defaultWidth: 336, minWidth: 280, maxWidth: 440 } }}
    responsive={{ enabled: true, rail: { label: "知识导航" }, inspector: { label: "关系与依据", open: detailOpen, onOpenChange: setDetailOpen, narrowPlacement: "bottom" } }}
    rail={<VSurface tone="rail" padding="none" className={styles.inspector}><div className={styles.railHeader}><h2 className={styles.railTitle}><Network size={17} />平台知识图谱</h2><label className={styles.search}><Search size={14} /><VNativeInput aria-label="搜索主题、知识或来源" placeholder="搜索主题、知识或来源" value={query} onChange={event => { setQuery(event.target.value); setTopicId(""); resetSelection(); }} /></label></div>
      <div className={styles.railContent}><VButton className={styles.overviewButton} variant={topicId ? "ghost" : "secondary"} icon={<Globe2 size={14} />} onClick={reset}>平台总览</VButton><p className={styles.railHeading}>知识主题</p><div className={styles.railList}>{payload?.topics.map(item => <VButton key={item.id} className={styles.topicButton} variant={item.id === topicId ? "secondary" : "ghost"} onClick={() => openTopic(item.id)}>{item.label} · {item.nodeIds.length}</VButton>)}</div>
        {search && <div className={styles.searchResults}><p className={styles.railHint}>{matches.length} 条匹配</p>{matches.slice(0, 30).map(node => <VButton key={node.id} variant="ghost" className={styles.topicButton} onClick={() => openNode(node.id)}>{node.label}</VButton>)}</div>}
        <p className={styles.railHeading}>关系图例 · {platformLayerLabels[layer]}</p><div className={styles.railList}>{legend.map(label => <VButton key={label} variant={relationType === label ? "secondary" : "ghost"} className={styles.overviewButton} onClick={() => { setRelationType(current => current === label ? "" : label); resetSelection(); }}>{label}</VButton>)}</div>
        <label className={styles.candidateToggle}><VNativeInput type="checkbox" checked={candidates} onChange={event => { setCandidates(event.target.checked); resetSelection(); }} />包含待确认关系</label>{layer === "evidence" && <label className={styles.candidateToggle}><VNativeInput type="checkbox" checked={administrative} onChange={event => { setAdministrative(event.target.checked); resetSelection(); }} />显示入库审核记录</label>}<VButton className={styles.agentButton} variant="ghost" onClick={onAgentView}>Agent 权限视图</VButton>
      </div><p className={styles.accessNote}><ShieldCheck size={14} className={styles.icon} />本机管理员 · 正式知识只读<br />不改变 Agent 可读范围</p></VSurface>}
    canvas={<div className={styles.canvas}><div className={styles.heading}>{topicId && <VButton variant="ghost" icon={<ArrowLeft size={14} />} onClick={reset}>返回全景</VButton>}<strong>{topic?.label ?? "平台知识全景"}</strong><span className={styles.groupingHint}>{topic ? topicBasisLabels[topic.groupingBasis] : `${payload?.topics.length ?? 0} 个已加载主题`}</span></div>
      <div className={styles.tabs}><VTabs value={layer} onValueChange={value => { setLayer(value as PlatformRelationLayer); setRelationType(""); resetSelection(); }} items={Object.entries(platformLayerLabels).map(([id, label]) => ({ id, label }))} aria-label="关系视图" />
        <div className={styles.viewControls}>{spatial && layer === "knowledge" && <label className={styles.sourceToggle}><VNativeInput type="checkbox" checked={showSources} onChange={event => { setShowSources(event.target.checked); resetSelection(); }} />来源连线</label>}
          <VButton variant="ghost" aria-pressed={spatial} onClick={() => { setSpatial(true); resetSelection(); }}>3D 空间</VButton><VButton variant="ghost" aria-pressed={!spatial} onClick={() => { setSpatial(false); resetSelection(); }}>关系图</VButton>
        </div>
      </div>
      {payload && layer === "knowledge" && !(topicId ? slice.edges.some(isContentRelation) : hasContentRelations) && <p role="status" className={styles.relationStatus}>{topicId ? "本主题尚未记录支持、反驳或引用等内容关系。下面展示已收录的知识，可切换“证据关系”查看来源。" : "当前数据主要记录知识收录和来源，内容关系尚未建立。星域表示内容分组，不代表主题互相支持。"}</p>}
      <div className={styles.stage}>
        {!payload && graph.isPending ? <div role="status" className={styles.loading}>正在读取平台知识…</div> : !payload && graph.error ? <div role="alert" className={styles.empty}><strong>平台图谱加载失败</strong><p className={styles.errorMessage}>{graph.error.message}</p><VButton onClick={() => void graph.refetch()}>重试</VButton><VButton variant="ghost" onClick={onAgentView}>查看 Agent 权限范围</VButton></div> : payload && (topicId ? slice.nodes.length : canvasNodes.length) ? <VMemoryGraphCanvas nodes={topicId ? (spatial ? spatialTopic.nodes : slice.nodes) : canvasNodes} edges={visibleEdges} selectedNodeId={nodeId || (spatial && !edgeId ? topicId : "")} selectedEdgeId={edgeId} mode={spatial ? "galaxy" : "relations"} appearance={spatial ? "cosmos" : undefined} groupByTopic={spatial || !topicId} focusToken={focusToken} onSelectNode={id => { if (overview.nodes.some(node => node.id === id)) openTopic(id); else openNode(id); }} onSelectEdge={id => { const edge = eligible.find(edge => edge.id === id) ?? payload.edges.find(edge => (overview.edges.find(item => item.id === id)?.metadata.relationIds as string[] | undefined)?.includes(edge.id)); if (edge) openEdge(edge); }} fallbackText="当前浏览器无法显示三维空间，可使用主题列表或关系图浏览。" /> : <div role="status" className={styles.empty}><FileText className={styles.emptyIcon} /><strong>{search ? "没有找到相关内容" : "当前范围还没有正式知识"}</strong><p className={styles.emptyMessage}>{search ? "可更换关键词或清空搜索。" : "审核收录后的有效知识会显示在这里。"}</p>{search && <VButton onClick={reset}>清空搜索</VButton>}</div>}
        {spatial && canvasNodes.length > 0 && <><p className={styles.spatialLegend}>三维知识空间<span>知识与来源为可选节点 · 连线为已记录关系</span></p><VButton variant="ghost" className={styles.fit} aria-label="适配当前三维图谱" icon={<Maximize2 size={16} />} onClick={() => { resetSelection(); setFocusToken(value => value + 1); }} /></>}
      </div>{payload?.summary.truncated && <div role="status" className={styles.truncation}><span>已加载 {payload.summary.nodeCount} / {payload.summary.totalNodeCount} 个节点，当前画面不是全量。</span>{limit < 5000 && <VButton variant="secondary" onClick={() => { setLimit(5000); resetSelection(); }}>加载更多（最多 5000）</VButton>}</div>}
      {payload && graph.error && <p role="alert" className={styles.refreshError}>刷新失败，保留上次加载的数据。<VButton variant="ghost" onClick={() => void graph.refetch()}>重试</VButton></p>}
      <div className={styles.footer}><span>{topicId ? `${topic?.nodeIds.length ?? 0} 条知识 · ${visibleEdges.length} 条关系` : `${payload?.nodes.filter(node => node.type === "knowledge_item").length ?? 0} 条正式知识 · ${payload?.topics.length ?? 0} 个主题 · ${visibleEdges.length} 条关系`}</span><span>{spatial ? "拖动旋转 · 右拖平移 · 滚轮缩放" : "箭头表示关系方向 · 点选可看依据"}</span></div>
    </div>} inspector={selectedNode || selectedEdge ? inspector : undefined} />;
}
