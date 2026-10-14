import styles from "./PlatformKnowledgeGraphWorkbench.styles";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ArrowLeft, FileText, Globe2, Network, Search, ShieldCheck, X } from "lucide-react";
import { fetchPlatformKnowledgeGraph, fetchPlatformKnowledgeGraphNodeDetail, platformKnowledgeGraphKeys } from "../../api/memory";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../../api/types";
import { VButton, VCanvasWorkbenchPage, VMemoryGraphCanvas, VNativeInput, VSurface, VTabs } from "../../components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { MemoryGraphRelationInspector } from "../MemoryGraphRelationInspector";
import { platformLayerLabels, platformTopicOverview, platformTopicSlice, relationLayer, topicBasisLabels, type PlatformRelationLayer } from "./platformKnowledgeGraphModel";

export function PlatformKnowledgeGraphWorkbench({ onAgentView }: { onAgentView: () => void }) {
  const [limit, setLimit] = useState(800);
  const [topicId, setTopicId] = useState("");
  const [layer, setLayer] = useState<PlatformRelationLayer>("knowledge");
  const [query, setQuery] = useState("");
  const [relationType, setRelationType] = useState("");
  const [candidates, setCandidates] = useState(false);
  const [nodeId, setNodeId] = useState("");
  const [edgeId, setEdgeId] = useState("");
  const [detailRecords, setDetailRecords] = useState<{ nodes: MemoryKnowledgeGraphNode[]; edges: MemoryKnowledgeGraphEdge[] }>({ nodes: [], edges: [] });
  const [detailOpen, setDetailOpen] = useState(false);
  const graph = useQuery({ queryKey: platformKnowledgeGraphKeys.overview(limit), queryFn: ({ signal }) => fetchPlatformKnowledgeGraph({ limit, signal }), staleTime: 60_000 });
  const payload = graph.data;
  const detail = useQuery({ queryKey: platformKnowledgeGraphKeys.detail(nodeId), queryFn: ({ signal }) => fetchPlatformKnowledgeGraphNodeDetail(nodeId, { signal }), enabled: Boolean(nodeId), staleTime: 60_000 });
  const search = query.trim().toLocaleLowerCase();
  const matches = useMemo(() => search ? (payload?.nodes ?? []).filter(node => `${node.label} ${node.summary}`.toLocaleLowerCase().includes(search)) : [], [payload, search]);
  const eligible = useMemo(() => (payload?.edges ?? []).filter(edge => relationLayer(edge) === layer && (candidates || edge.metadata.status !== "candidate") && (!relationType || edge.label === relationType)), [payload, layer, candidates, relationType]);
  const overview = useMemo(() => payload ? platformTopicOverview(payload, eligible) : { nodes: [], edges: [] }, [payload, eligible]);
  const slice = useMemo(() => payload ? platformTopicSlice(payload, topicId, eligible, nodeId) : { nodes: [], edges: [] }, [payload, topicId, eligible, nodeId]);
  const topic = payload?.topics.find(item => item.id === topicId);
  const knownNodes = [...(payload?.nodes ?? []), ...detailRecords.nodes];
  const selectedEdge = payload?.edges.find(edge => edge.id === edgeId) ?? detailRecords.edges.find(edge => edge.id === edgeId);
  const selectedNode = knownNodes.find(node => node.id === nodeId);
  // A detail response for a previously selected node is never used for the next node.
  const currentDetail = detail.data?.nodeId === nodeId ? detail.data : undefined;
  const legend = [...new Set((payload?.edges ?? []).filter(edge => relationLayer(edge) === layer && (candidates || edge.metadata.status !== "candidate")).map(edge => edge.label))];
  const resetSelection = () => { setNodeId(""); setEdgeId(""); setDetailOpen(false); };
  const reset = () => { setTopicId(""); setQuery(""); setRelationType(""); setDetailRecords({ nodes: [], edges: [] }); resetSelection(); };
  const openTopic = (id: string) => { setTopicId(id); setQuery(""); setRelationType(""); resetSelection(); };
  const openNode = (id: string) => {
    const node = knownNodes.find(item => item.id === id);
    if (!node) return;
    const memberships = Array.isArray(node.metadata.topicIds) ? node.metadata.topicIds.filter((id): id is string => typeof id === "string") : [];
    const targetTopic = memberships.includes(topicId) ? topicId : String(node.metadata.topicId ?? memberships[0] ?? "");
    if (targetTopic) setTopicId(targetTopic);
    setNodeId(id); setEdgeId(""); setQuery(""); setDetailOpen(true);
  };
  const openEdge = (edge: MemoryKnowledgeGraphEdge) => {
    if (currentDetail) setDetailRecords({ nodes: [currentDetail.node, ...currentDetail.relatedNodes], edges: currentDetail.edges });
    const from = knownNodes.find(node => node.id === edge.source) ?? currentDetail?.relatedNodes.find(node => node.id === edge.source);
    const to = knownNodes.find(node => node.id === edge.target) ?? currentDetail?.relatedNodes.find(node => node.id === edge.target);
    setTopicId(String(from?.metadata.topicId ?? to?.metadata.topicId ?? topicId));
    setLayer(relationLayer(edge)); setRelationType(""); setNodeId(""); setEdgeId(edge.id); setDetailOpen(true);
  };
  const matchingTopics = new Set(matches.map(node => String(node.metadata.topicId ?? node.id)));
  const canvasNodes = search ? overview.nodes.filter(node => matchingTopics.has(node.id) || node.label.toLocaleLowerCase().includes(search)) : overview.nodes;
  const canvasNodeIds = new Set(canvasNodes.map(node => node.id));
  const sourceLocation = (node: MemoryKnowledgeGraphNode) => {
    const source = node.metadata.sourceRef;
    const names: Record<string, string> = { url: "链接", pageRange: "页码", page: "页码", fileName: "文件", path: "文件位置", title: "标题", lineStart: "起始行", lineEnd: "结束行" };
    return source && typeof source === "object" ? Object.entries(source).filter(([, value]) => typeof value === "string" || typeof value === "number").map(([key, value]) => `${names[key] ?? key}: ${String(value)}`).join(" · ") : String(node.metadata.sourceId ?? "");
  };
  const inspector = <VSurface tone="panel" padding="none" className={styles.inspector}>
    <div className={styles.detailHeader}><strong>{selectedEdge ? "关系与依据" : selectedNode ? "节点详情" : "平台知识全景"}</strong>{(selectedEdge || selectedNode) && <VButton variant="ghost" aria-label="清除详情选择" icon={<X size={14} />} onClick={resetSelection} />}</div>
    {selectedEdge ? <MemoryGraphRelationInspector edge={selectedEdge} nodes={knownNodes} onNavigate={openNode} onBack={() => openNode(selectedEdge.source)} /> : <div className={styles.detailContent}>
      {selectedNode ? <>
        <h2 className={styles.nodeTitle}>{selectedNode.label}</h2><p className={styles.nodeSummary}>{selectedNode.summary}</p>
        <dl className={styles.nodeMetadata}><dt className={styles.muted}>知识归属</dt><dd>{String(selectedNode.metadata.ownerId ?? "平台知识目录")}</dd><dt className={styles.muted}>来源位置</dt><dd className={styles.breakWords}>{sourceLocation(selectedNode) || "当前节点不是来源记录"}</dd><dt className={styles.muted}>版本与审核</dt><dd className={styles.breakWords}>{[selectedNode.metadata.revision && `修订 ${selectedNode.metadata.revision}`, selectedNode.metadata.reviewedAt, selectedNode.metadata.capturedAt].filter(Boolean).map(String).join(" · ") || "未提供"}</dd></dl>
        {Boolean(selectedNode.metadata.sourceHash) && <p className={styles.sourceHash}>来源哈希：{String(selectedNode.metadata.sourceHash)}</p>}
        <p className={styles.metadataBoundary}>当前管理图谱读取正式知识元数据和来源定位，不提供私有记忆正文或来源原文。</p>
        {detail.isFetching && <p role="status" className={styles.loadingDetail}>正在核对关联记录…</p>}
        {detail.error && <div role="alert" className={styles.loadingDetail}>详情加载失败：{detail.error.message}<VButton variant="ghost" onClick={() => void detail.refetch()}>重试</VButton></div>}
        {currentDetail?.summaryCounts?.truncated && <p role="status" className={styles.truncatedDetail}>详情关联已达加载上限。</p>}
        <h3 className={styles.relationHeading}>相关关系</h3>
        <div className={styles.relationList}>{(currentDetail?.edges ?? payload?.edges ?? []).filter(edge => (edge.source === nodeId || edge.target === nodeId) && (candidates || edge.metadata.status !== "candidate")).map(edge => <VButton key={edge.id} variant="ghost" className={styles.relationButton} onClick={() => openEdge(edge)}>{edge.label} → {(payload?.nodes ?? []).find(node => node.id === (edge.source === nodeId ? edge.target : edge.source))?.label ?? "关联记录"}</VButton>)}</div>
      </> : <><Globe2 size={28} className={styles.overviewIcon} /><h2 className={styles.overviewTitle}>从全景找到知识</h2><p className={styles.overviewSummary}>选择星域查看主题知识，点选带中文名称的关系，核对相连原因与来源。</p><p className={styles.overviewHint}>主题依据来自已审核科研领域、主标签或知识库；空间距离不代表事实强度。归属关系与来源证据分别阅读。</p><p className={styles.boundaryHint}>全平台正式知识管理范围，排除 Agent 私有记忆文件、待审核内容和原始对话。仅本机授权管理员可访问。</p></>}
    </div>}
  </VSurface>;
  return <VCanvasWorkbenchPage hideHeader title="平台知识图谱" ariaLabel="平台知识图谱" domainRecipe="memory-knowledge-workbench" layoutId={WORKBENCH_LAYOUT_IDS.memory} className={styles.workspace}
    resize={{ sidebar: { id: "filters", defaultWidth: 224, minWidth: 190, maxWidth: 340 }, aside: { id: "inspector", defaultWidth: 336, minWidth: 280, maxWidth: 440 } }}
    responsive={{ enabled: true, rail: { label: "知识导航" }, inspector: { label: "关系与依据", open: detailOpen, onOpenChange: setDetailOpen, narrowPlacement: "bottom" } }}
    rail={<VSurface tone="rail" padding="none" className={styles.inspector}><div className={styles.railHeader}><h2 className={styles.railTitle}><Network size={17} />平台知识图谱</h2><label className={styles.search}><Search size={14} /><VNativeInput aria-label="搜索主题、知识或来源" placeholder="搜索主题、知识或来源" value={query} onChange={event => { setQuery(event.target.value); setTopicId(""); resetSelection(); }} /></label></div>
      <div className={styles.railContent}><VButton className={styles.overviewButton} variant={topicId ? "ghost" : "secondary"} icon={<Globe2 size={14} />} onClick={reset}>平台总览</VButton><p className={styles.railHeading}>知识主题</p><div className={styles.railList}>{payload?.topics.map(item => <VButton key={item.id} className={styles.topicButton} variant={item.id === topicId ? "secondary" : "ghost"} onClick={() => openTopic(item.id)}>{item.label} · {item.nodeIds.length}</VButton>)}</div>
        {search && <div className={styles.searchResults}><p className={styles.railHint}>{matches.length} 条匹配</p>{matches.slice(0, 30).map(node => <VButton key={node.id} variant="ghost" className={styles.topicButton} onClick={() => openNode(node.id)}>{node.label}</VButton>)}</div>}
        <p className={styles.railHeading}>关系图例 · {platformLayerLabels[layer]}</p><div className={styles.railList}>{legend.map(label => <VButton key={label} variant={relationType === label ? "secondary" : "ghost"} className={styles.overviewButton} onClick={() => { setRelationType(current => current === label ? "" : label); resetSelection(); }}>{label}</VButton>)}</div>
        <label className={styles.candidateToggle}><VNativeInput type="checkbox" checked={candidates} onChange={event => { setCandidates(event.target.checked); resetSelection(); }} />包含待确认关系</label><VButton className={styles.agentButton} variant="ghost" onClick={onAgentView}>Agent 权限视图</VButton>
      </div><p className={styles.accessNote}><ShieldCheck size={14} className={styles.icon} />本机管理员 · 正式知识只读<br />不改变 Agent 可读范围</p></VSurface>}
    canvas={<div className={styles.canvas}><div className={styles.heading}>{topicId && <VButton variant="ghost" icon={<ArrowLeft size={14} />} onClick={reset}>返回全景</VButton>}<strong>{topic?.label ?? "平台知识全景"}</strong><span className={styles.groupingHint}>{topic ? topicBasisLabels[topic.groupingBasis] : `${payload?.topics.length ?? 0} 个已加载主题`}</span></div>
      <div className={styles.tabs}><VTabs value={layer} onValueChange={value => { setLayer(value as PlatformRelationLayer); setRelationType(""); resetSelection(); }} items={Object.entries(platformLayerLabels).map(([id, label]) => ({ id, label }))} aria-label="关系视图" /></div>
      <div className={styles.stage}>
        {!payload && graph.isPending ? <div role="status" className={styles.loading}>正在读取平台知识…</div> : !payload && graph.error ? <div role="alert" className={styles.empty}><strong>平台图谱加载失败</strong><p className={styles.errorMessage}>{graph.error.message}</p><VButton onClick={() => void graph.refetch()}>重试</VButton><VButton variant="ghost" onClick={onAgentView}>查看 Agent 权限范围</VButton></div> : payload && (topicId ? slice.nodes.length : canvasNodes.length) ? <VMemoryGraphCanvas nodes={topicId ? slice.nodes : canvasNodes} edges={topicId ? slice.edges : overview.edges.filter(edge => canvasNodeIds.has(edge.source) && canvasNodeIds.has(edge.target))} selectedNodeId={nodeId} selectedEdgeId={edgeId} mode={topicId ? "relations" : "galaxy"} groupByTopic={!topicId} onSelectNode={topicId ? openNode : openTopic} onSelectEdge={id => { const edge = topicId ? eligible.find(edge => edge.id === id) : payload.edges.find(edge => (overview.edges.find(item => item.id === id)?.metadata.relationIds as string[] | undefined)?.includes(edge.id)); if (edge) openEdge(edge); }} fallbackText="当前浏览器无法显示星系，可使用主题列表浏览。" /> : <div role="status" className={styles.empty}><FileText className={styles.emptyIcon} /><strong>{search ? "没有找到相关内容" : "当前范围还没有正式知识"}</strong><p className={styles.emptyMessage}>{search ? "可更换关键词或清空搜索。" : "审核收录后的有效知识会显示在这里。"}</p>{search && <VButton onClick={reset}>清空搜索</VButton>}</div>}
      </div>{payload?.summary.truncated && <div role="status" className={styles.truncation}><span>已加载 {payload.summary.nodeCount} / {payload.summary.totalNodeCount} 个节点，当前画面不是全量。</span>{limit < 5000 && <VButton variant="secondary" onClick={() => { setLimit(5000); resetSelection(); }}>加载更多（最多 5000）</VButton>}</div>}
      {payload && graph.error && <p role="alert" className={styles.refreshError}>刷新失败，保留上次加载的数据。<VButton variant="ghost" onClick={() => void graph.refetch()}>重试</VButton></p>}
      <div className={styles.footer}><span>{topicId ? `${slice.nodes.length} 个节点 · ${slice.edges.length} 条${platformLayerLabels[layer]}` : `正式知识 · ${payload?.summary.nodeCount ?? 0} 个已加载节点`}</span><span>{topicId ? "箭头表示关系方向 · 点选可看依据" : "主题星系 · 拖动环绕 · 滚轮缩放"}</span></div>
    </div>} inspector={inspector} />;
}
