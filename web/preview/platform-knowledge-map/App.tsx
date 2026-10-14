import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, BookOpen, ChevronRight, FileText, Globe2, Layers3, Lock, Network, Search, ShieldCheck, Sun, Moon, X } from "lucide-react";
import { VButton, VCanvasWorkbenchPage, VDialog, VNativeInput, VSurface, VTabs, VuiProvider, VWorkbenchFrame } from "../../src/components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../src/components/layout/workbenchLayoutIds";
import { evidence, nodes, relations, topics, type GraphEvidence, type GraphNode, type GraphRelation, type RelationLayer, type TopicId } from "./fixtures";
import { GalaxyOverview } from "./GalaxyOverview";
import { kindLabels, RelationGraph } from "./RelationGraph";

const layerLabels: Record<RelationLayer, string> = { knowledge: "知识关联", ownership: "归属关系", evidence: "证据关系" };
const byId = new Map(nodes.map(node => [node.id, node]));
const evidenceById = new Map(evidence.map(item => [item.id, item]));
const sentence = (relation: GraphRelation) => `${byId.get(relation.source)?.label} — ${relation.label} → ${byId.get(relation.target)?.label}`;

export function App() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [topicId, setTopicId] = useState<TopicId | null>(null);
  const [layer, setLayer] = useState<RelationLayer>("knowledge");
  const [query, setQuery] = useState("");
  const [relationType, setRelationType] = useState("");
  const [includeCandidates, setIncludeCandidates] = useState(false);
  const [nodeId, setNodeId] = useState("");
  const [relationId, setRelationId] = useState("");
  const [detailOpen, setDetailOpen] = useState(false);
  const [source, setSource] = useState<GraphEvidence | null>(null);
  useEffect(() => { document.documentElement.dataset.theme = theme; }, [theme]);
  const topic = topics.find(item => item.id === topicId);
  const search = query.trim().toLocaleLowerCase();
  const matches = useMemo(() => search ? nodes.filter(node => node.access === "readable" && `${node.label} ${node.summary} ${node.owner}`.toLocaleLowerCase().includes(search)) : [], [search]);
  const matchingTopics = useMemo(() => new Set<TopicId>([...matches.map(node => node.topic), ...topics.filter(item => search && item.label.toLocaleLowerCase().includes(search)).map(item => item.id)]), [matches, search]);
  const eligible = relations.filter(relation => relation.layer === layer && (includeCandidates || relation.status === "confirmed") && (!relationType || relation.label === relationType));
  const visibleRelations = topicId ? eligible.filter(relation => byId.get(relation.source)?.topic === topicId || byId.get(relation.target)?.topic === topicId) : eligible;
  const ids = new Set(visibleRelations.flatMap(relation => [relation.source, relation.target]));
  if (nodeId && byId.get(nodeId)?.topic === topicId) ids.add(nodeId);
  const visibleNodes = nodes.filter(node => ids.has(node.id));
  const selectedRelation = relations.find(relation => relation.id === relationId);
  const selectedNode = byId.get(nodeId);
  const legend = [...new Set(relations.filter(relation => relation.layer === layer && (includeCandidates || relation.status === "confirmed")).map(relation => relation.label))];
  const reset = () => { setTopicId(null); setNodeId(""); setRelationId(""); setRelationType(""); setQuery(""); setDetailOpen(false); };
  const openTopic = (id: TopicId) => {
    setTopicId(id); setQuery(""); setRelationType(""); setNodeId("");
    setRelationId(relations.find(relation => relation.layer === layer && relation.status === "confirmed" && byId.get(relation.source)?.topic === id)?.id ?? "");
    setDetailOpen(false);
  };
  const openRelation = (relation: GraphRelation) => {
    setTopicId(byId.get(relation.source)!.topic); setLayer(relation.layer); setRelationType("");
    setNodeId(""); setRelationId(relation.id); setDetailOpen(true); setQuery("");
  };
  const openNode = (node: GraphNode, fromSearch = false) => {
    setTopicId(node.topic); setNodeId(node.id); setRelationId(""); setDetailOpen(true);
    if (fromSearch) {
      setLayer(node.kind === "source" || node.kind === "experiment" ? "evidence" : node.kind === "team" || node.kind === "agent" ? "ownership" : "knowledge");
      setRelationType(""); setQuery("");
    }
  };
  const changeLayer = (value: string) => { setLayer(value as RelationLayer); setRelationType(""); setNodeId(""); setRelationId(""); setDetailOpen(false); };

  const rail = <VSurface tone="rail" padding="none" className="flex h-full flex-col overflow-hidden !rounded-none !border-0 !shadow-none">
    <div className="flex items-center gap-2 border-b border-[var(--vui-border-subtle)] px-4 py-4"><Network size={18} className="text-[var(--accent-cool)]" /><strong className="text-vui-sm">知识导航</strong></div>
    <div className="min-h-0 flex-1 overflow-y-auto p-3">
      <VButton className="min-h-11 w-full !justify-start" icon={<Globe2 size={15} />} variant={topicId ? "ghost" : "secondary"} aria-pressed={!topicId} onClick={reset}>平台总览</VButton>
      <p className="mb-2 mt-5 px-2 text-vui-xs text-[var(--fg-tertiary)]">知识主题</p>
      <div className="grid gap-1">{topics.map(item => <VButton key={item.id} variant={topicId === item.id ? "secondary" : "ghost"} contentLayout="plain" aria-pressed={topicId === item.id}
        className="min-h-11 w-full !justify-start" onClick={() => openTopic(item.id)}>
        <span className="flex w-full min-w-0 items-center gap-2"><span className="h-2 w-2 shrink-0 rounded-full" style={{ background: `#${item.color.toString(16)}` }} /><span className="min-w-0 flex-1 truncate text-left">{item.label}</span><span className="text-vui-xs text-[var(--fg-tertiary)]">{nodes.filter(node => node.topic === item.id && node.access === "readable").length}</span></span>
      </VButton>)}</div>
      {search && <div className="mt-5 border-t border-[var(--vui-border-subtle)] pt-4" aria-live="polite"><p className="mb-2 px-2 text-vui-xs text-[var(--fg-tertiary)]">{matches.length} 个节点 · {matchingTopics.size} 个主题匹配</p>
        {matches.slice(0, 8).map(node => <VButton key={node.id} variant="ghost" className="!h-auto min-h-11 w-full !justify-start !whitespace-normal py-2 text-left" onClick={() => openNode(node, true)}>{node.label}</VButton>)}
        {topics.filter(item => matchingTopics.has(item.id) && !matches.some(node => node.topic === item.id)).map(item => <VButton key={item.id} variant="ghost" className="min-h-11 w-full" onClick={() => openTopic(item.id)}>{item.label}</VButton>)}
      </div>}
      <p className="mb-2 mt-6 px-2 text-vui-xs text-[var(--fg-tertiary)]">关系图例 · {layerLabels[layer]}</p>
      <div className="grid gap-1">{legend.map(label => <VButton key={label} variant="ghost" contentLayout="plain" aria-pressed={relationType === label} className="min-h-10 w-full !justify-between" onClick={() => { setRelationType(current => current === label ? "" : label); setNodeId(""); setRelationId(""); }}><span>{label}</span><span className="text-vui-xs text-[var(--fg-tertiary)]">{eligible.filter(relation => relation.label === label).length}</span></VButton>)}</div>
      {relationType && <VButton variant="ghost" className="mt-2 min-h-10 w-full" onClick={() => setRelationType("")}>显示全部关系类型</VButton>}
      <label className="mt-5 flex min-h-11 cursor-pointer items-center gap-2 px-2 text-vui-xs"><VNativeInput type="checkbox" checked={includeCandidates} onChange={event => { setIncludeCandidates(event.target.checked); if (!event.target.checked && selectedRelation?.status === "candidate") setRelationId(""); }} />包含待确认关系</label>
      <p className="px-2 text-vui-xs leading-relaxed text-[var(--fg-tertiary)]">实线为演示已确认关系，虚线为待确认关联。空间距离不表示事实强度。</p>
    </div>
    <div className="border-t border-[var(--vui-border-subtle)] p-4 text-vui-xs leading-relaxed text-[var(--fg-tertiary)]"><ShieldCheck size={14} className="mb-1" />全部授权范围（演示）<br />{nodes.filter(node => node.access === "readable").length} 个可见节点 · 1 个受限占位<br />未连接真实知识或 Agent</div>
  </VSurface>;

  const inspector = <VSurface tone="panel" padding="none" className="flex h-full min-h-0 flex-col overflow-hidden !rounded-none !border-0 !shadow-none" data-preview-inspector>
    <div className="hidden shrink-0 items-center justify-between border-b border-[var(--vui-border-subtle)] px-4 py-4 min-[900px]:flex"><strong className="text-vui-sm">{selectedRelation ? "关系与依据" : selectedNode ? "节点详情" : "从全景找到知识"}</strong>{(selectedRelation || selectedNode) && <VButton variant="ghost" aria-label="清除详情选择" icon={<X size={14} />} onClick={() => { setNodeId(""); setRelationId(""); setDetailOpen(false); }} />}</div>
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
      {selectedRelation ? <>
        <span className="mb-3 inline-flex rounded border border-[var(--vui-border-subtle)] px-2 py-1 text-vui-xs text-[var(--fg-secondary)]">{selectedRelation.status === "candidate" ? "待确认关联 · 演示" : "已确认关系 · 演示"}</span>
        <h2 className="break-words text-vui-md font-semibold leading-relaxed" data-relation-sentence>{sentence(selectedRelation)}</h2>
        <p className="mb-2 mt-6 text-vui-xs font-medium text-[var(--fg-tertiary)]">为什么相连</p><p className="text-vui-sm leading-loose text-[var(--fg-secondary)]">{selectedRelation.reason}</p>
        <div className="mt-5 grid grid-cols-2 gap-2"><VButton variant="secondary" className="!h-auto min-h-11 !whitespace-normal p-2" onClick={() => openNode(byId.get(selectedRelation.source)!)}>起点详情</VButton><VButton variant="secondary" className="!h-auto min-h-11 !whitespace-normal p-2" onClick={() => openNode(byId.get(selectedRelation.target)!)}>终点详情</VButton></div>
        <p className="mb-3 mt-7 text-vui-xs font-medium text-[var(--fg-tertiary)]">关系依据</p>
        {selectedRelation.evidenceIds.length ? <div className="grid gap-3">{selectedRelation.evidenceIds.map(id => {
          const item = evidenceById.get(id)!;
          return <div key={id} className="border-l-2 border-[var(--vui-border-strong)] pl-3"><p className="text-vui-sm font-medium leading-relaxed">{item.label}</p><p className="mt-1 text-vui-xs leading-relaxed text-[var(--fg-tertiary)]">{item.location} · {item.version}</p><VButton variant="ghost" className="mt-2 min-h-11" icon={item.accessible ? <FileText size={14} /> : <Lock size={14} />} isDisabled={!item.accessible} onClick={() => { if (item.accessible) setSource(item); }}>{item.accessible ? "查看演示原文" : "来源受限，不能读取"}</VButton></div>;
        })}</div> : <p className="text-vui-sm leading-loose text-[var(--fg-secondary)]">{selectedRelation.layer === "ownership" ? "这条归属关系来自演示组织目录。内容依据请切换到证据关系查看。" : "尚无可确认的来源依据，不能将这条关联视为事实。"}</p>}
        {selectedRelation.status === "candidate" && <p className="mt-5 rounded border border-dashed border-[var(--vui-border-strong)] p-3 text-vui-xs leading-relaxed text-[var(--fg-secondary)]">候选关系需要原文或实验依据与审核；预览不会自动确认，也不会写入正式知识。</p>}
      </> : selectedNode ? <>
        <span className="mb-3 inline-flex items-center gap-1 text-vui-xs text-[var(--fg-tertiary)]">{selectedNode.access === "restricted" && <Lock size={13} />}{kindLabels[selectedNode.kind]} · {topics.find(item => item.id === selectedNode.topic)?.label}</span>
        <h2 className="break-words text-vui-md font-semibold leading-relaxed">{selectedNode.label}</h2><p className="mt-4 text-vui-sm leading-loose text-[var(--fg-secondary)]">{selectedNode.summary}</p>
        <dl className="mt-5 grid gap-1 text-vui-xs"><dt className="text-[var(--fg-tertiary)]">归属</dt><dd>{selectedNode.owner}</dd><dt className="mt-3 text-[var(--fg-tertiary)]">可读范围</dt><dd>{selectedNode.access === "readable" ? "可读演示内容" : "仅为受限占位，不能读取来源内容"}</dd></dl>
        <p className="mb-3 mt-7 text-vui-xs text-[var(--fg-tertiary)]">与它关联的内容</p><div className="grid gap-2">{relations.filter(relation => (relation.source === selectedNode.id || relation.target === selectedNode.id) && (includeCandidates || relation.status === "confirmed")).map(relation => <VButton key={relation.id} variant="ghost" contentLayout="plain" className="!h-auto min-h-11 w-full !justify-start !whitespace-normal border-b border-[var(--vui-border-subtle)] py-3 text-left" onClick={() => openRelation(relation)}><span><small className="block text-vui-xs text-[var(--accent-cool)]">{relation.source === selectedNode.id ? relation.label : `← ${relation.label}`}</small><span className="block text-vui-sm">{byId.get(relation.source === selectedNode.id ? relation.target : relation.source)?.label}</span></span></VButton>)}</div>
      </> : <>
        <Layers3 size={28} className="mb-5 text-[var(--accent-cool)]" /><h2 className="text-vui-md font-semibold">平台知识全景</h2>
        <p className="mt-3 text-vui-sm leading-loose text-[var(--fg-secondary)]">先找到一个主题，再读清知识之间的关系，最后回到原文或实验依据。</p>
        <div className="mt-6 grid gap-5 text-vui-sm"><p><strong>① 选一个星域</strong><span className="mt-1 block text-vui-xs leading-relaxed text-[var(--fg-tertiary)]">主题汇总跨团队的知识，不再只看单个 Agent。</span></p><p><strong>② 读一条关系</strong><span className="mt-1 block text-vui-xs leading-relaxed text-[var(--fg-tertiary)]">每条线有中文谓语和箭头，点击可解释为什么相连。</span></p><p><strong>③ 查看关系依据</strong><span className="mt-1 block text-vui-xs leading-relaxed text-[var(--fg-tertiary)]">保留来源位置、版本、权限和确认状态。</span></p></div>
        <p className="mt-8 border-t border-[var(--vui-border-subtle)] pt-4 text-vui-xs leading-relaxed text-[var(--fg-tertiary)]">本页全部为演示数据，用于确认信息组织。平台总量、真实来源、全局授权和抽取结果尚未接入。</p>
      </>}
    </div>
  </VSurface>;

  const canvas = <div className="flex h-full min-h-0 flex-col overflow-hidden">
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-[var(--vui-border-subtle)] px-4 py-3 text-vui-sm">
      {topicId && <VButton variant="ghost" icon={<ArrowLeft size={14} />} onClick={reset}>返回全景</VButton>}
      <span className="text-[var(--fg-tertiary)]">平台全景</span>{topicId && <><ChevronRight size={13} /><strong>{topic?.label}</strong></>}
      <span className="ml-auto text-vui-xs text-[var(--fg-tertiary)]">{topicId ? `${visibleNodes.length} 个节点 · ${visibleRelations.length} 条${layerLabels[layer]}` : `${topics.length} 个演示主题 · 全平台范围预览`}</span>
    </div>
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-4 py-2">
      <VTabs value={layer} onValueChange={changeLayer} items={Object.entries(layerLabels).map(([id, label]) => ({ id, label }))} aria-label="关系视图" />
      {topicId && <span className="text-vui-xs text-[var(--fg-tertiary)]">箭头表示方向 · 点选关系看依据</span>}
    </div>
    <div className="relative min-h-0 flex-1 bg-[var(--vui-surface-workspace)]">
      {search && matchingTopics.size === 0 ? <div className="grid h-full place-content-center gap-3 px-6 text-center" role="status"><Search size={28} className="mx-auto text-[var(--fg-tertiary)]" /><strong className="text-vui-md">没有找到相关内容</strong><p className="text-vui-sm text-[var(--fg-secondary)]">搜索只覆盖当前演示数据，可更换关键词。</p><VButton className="mx-auto min-h-11" onClick={() => setQuery("")}>清空搜索，返回全景</VButton></div>
        : !topicId ? <GalaxyOverview topics={topics} nodes={nodes} relations={eligible} highlightedTopics={matchingTopics} onTopic={openTopic} onRelation={openRelation} />
          : visibleRelations.length ? <RelationGraph nodes={visibleNodes} relations={visibleRelations} layer={layer} selectedNodeId={nodeId} selectedRelationId={relationId} onNode={openNode} onRelation={openRelation} />
            : <div className="grid h-full place-content-center gap-3 p-6 text-center" role="status"><Network size={28} className="mx-auto text-[var(--fg-tertiary)]" /><p>此主题在当前筛选下没有关系。</p><VButton onClick={() => setRelationType("")}>清除关系筛选</VButton></div>}
    </div>
    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-[var(--vui-border-subtle)] px-4 py-2 text-vui-xs text-[var(--fg-tertiary)]"><span>{topicId ? "知识内容、组织归属和来源依据分别阅读" : "星云与节点有真实三维位置；局部关系使用清晰的阅读布局"}</span><span>示例数据 · 不代表平台真实总量</span></div>
  </div>;

  return <VuiProvider><div className="flex h-dvh min-h-0 flex-col bg-[var(--bg-canvas)] text-[var(--fg-primary)]">
    <header className="flex shrink-0 flex-wrap items-center gap-3 border-b border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] px-4 py-3">
      <Network size={19} className="text-[var(--accent-cool)]" /><div><h1 className="text-vui-md font-semibold">平台知识图谱</h1><p className="text-vui-xs text-[var(--fg-tertiary)]">全景 · 关系 · 依据</p></div>
      <span className="rounded border border-[var(--vui-border-subtle)] px-2 py-1 text-vui-xs text-[var(--fg-secondary)]">隔离预览 · 演示数据</span>
      <label className="ml-auto flex w-full max-w-[330px] min-w-0 items-center gap-2 rounded border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-input)] px-2"><Search size={14} className="shrink-0 text-[var(--fg-tertiary)]" /><VNativeInput className="!min-h-11 w-full !border-0 !bg-transparent !shadow-none" aria-label="搜索主题、知识或来源" placeholder="搜索主题、知识或来源" value={query} onChange={event => { setQuery(event.target.value); setTopicId(null); setNodeId(""); setRelationId(""); setRelationType(""); setDetailOpen(false); }} />{query && <VButton aria-label="清空搜索" variant="ghost" icon={<X size={13} />} onClick={() => setQuery("")} />}</label>
      <VButton className="min-h-11 min-w-11" variant="ghost" aria-label={theme === "dark" ? "切换浅色主题" : "切换深色主题"} icon={theme === "dark" ? <Sun size={16} /> : <Moon size={16} />} onClick={() => setTheme(current => current === "dark" ? "light" : "dark")} />
    </header>
    <div className="flex min-h-0 flex-1"><VWorkbenchFrame><VCanvasWorkbenchPage hideHeader title="平台知识图谱" ariaLabel="平台知识图谱隔离预览" domainRecipe="memory-knowledge-workbench"
      className="h-full !p-0" layoutId={WORKBENCH_LAYOUT_IDS.memory} rail={rail} canvas={canvas} inspector={inspector}
      resize={{ sidebar: { id: "filters", defaultWidth: 220, minWidth: 200, maxWidth: 280 }, aside: { id: "inspector", defaultWidth: 330, minWidth: 300, maxWidth: 400 } }}
      responsive={{ enabled: true, rail: { label: "知识导航" }, inspector: { label: "关系与依据", open: detailOpen, onOpenChange: setDetailOpen, narrowPlacement: "bottom" } }} /></VWorkbenchFrame></div>
    <VDialog open={Boolean(source)} onOpenChange={open => { if (!open) setSource(null); }} title={source?.label ?? "来源原文"} description="合成摘录 · 仅用于演示原文定位，不对应真实资料" size="lg">
      {source && <div className="grid gap-4"><p className="text-vui-xs text-[var(--fg-tertiary)]">{source.location} · {source.version}</p><blockquote className="border-l-2 border-[var(--accent-cool)] pl-4 text-vui-sm leading-loose">{source.excerpt}</blockquote><p className="text-vui-xs leading-relaxed text-[var(--fg-secondary)]">正式接入后，此处按权限读取真实来源并保留位置与版本。</p></div>}
    </VDialog>
  </div></VuiProvider>;
}
