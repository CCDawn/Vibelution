import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowUpRight, BookOpen, Check, ChevronRight, FileText, Folder, Info, Minus, Network, Search, Settings2, X } from "lucide-react";
import { VButton, VMemoryGraphCanvas, VCanvasWorkbenchPage, VDialog, VNativeInput, VSurface, VTabs, VuiProvider, VWorkbenchFrame } from "../../src/components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../src/components/layout/workbenchLayoutIds";

import type { MemoryKnowledgeGraphNode, MemoryKnowledgeGraphEdge } from "../../src/api/types";

type Layer = "knowledge" | "ownership" | "evidence";
type Knowledge = {
  id: string;
  title: string;
  english: string;
  summary: string;
  source: "a" | "b" | "c";
};

// Deterministic presentation fixtures. These are neither database records nor scientific assertions.
const knowledge: Knowledge[] = [
  { id: "dennard", title: "Dennard 缩放", english: "Dennard scaling", source: "a", summary: "本条演示芯片缩放与功耗问题的知识详情排版。正式内容应保留原始条件、适用范围与来源位置。" },
  { id: "landauer", title: "Landauer 原理", english: "Landauer principle", source: "a", summary: "本条演示信息擦除与能耗主题的阅读结构。这里的中文释义和来源映射仅用于预览，不代表实际知识库记录。" },
  { id: "bremermann", title: "Bremermann 极限", english: "Bremermann limit", source: "b", summary: "本条演示计算物理边界条目的详情结构。正式内容需要回到具体资料，确认定义、前提与数量单位。" },
  { id: "amdahl", title: "Amdahl 定律", english: "Amdahl’s law", source: "c", summary: "本条演示并行计算主题的知识条目。预览不推断它与其他知识之间存在支持、反驳或因果关系。" },
  { id: "margolus", title: "Margolus–Levitin 定理", english: "Margolus–Levitin theorem", source: "b", summary: "本条演示量子演化与计算边界主题的标题和详情。来源内容、版本与原文定位在正式接入后提供。" },
  { id: "universe", title: "宇宙的计算容量", english: "Computational capacity of universe", source: "b", summary: "本条演示较长英文标题的可读性。中文短名是预览释义，不是对实际库内标题或科学结论的改写。" },
  { id: "reversible", title: "可逆计算", english: "Reversible computing", source: "a", summary: "本条演示一个较短中文标题与英文原名的组合。图中的线只表示演示来源连接，不附加结论。" },
  { id: "bekenstein", title: "Bekenstein 界", english: "Bekenstein bound", source: "b", summary: "本条演示物理信息边界主题的阅读位置。正式知识需要独立记录来源、前提、权限与确认状态。" },
  { id: "energy", title: "计算的能量成本", english: "Energy cost of computation", source: "c", summary: "本条演示跨条目主题的知识详情。当前页面不会生成新知识，也不会向实际知识库写入任何关系。" },
  { id: "quantum", title: "量子计算的物理极限", english: "Physical limits of quantum computation", source: "c", summary: "本条演示长英文名称与较长中文标题。预览只确认标题呈现、点选与来源面板的交互方式。" },
];

const sources = [
  { id: "a" as const, title: "示例资料 A", description: "芯片与能耗 · 合成来源占位" },
  { id: "b" as const, title: "示例资料 B", description: "计算物理边界 · 合成来源占位" },
  { id: "c" as const, title: "示例资料 C", description: "计算系统 · 合成来源占位" },
];

const layerNames: Record<Layer, string> = { knowledge: "知识", ownership: "归属", evidence: "证据" };
const themeTitle = "计算物理与能耗";

export function App() {
  const [query, setQuery] = useState("");
  const [layer, setLayer] = useState<Layer>("knowledge");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [showSources, setShowSources] = useState(true);
  const [showEnglish, setShowEnglish] = useState(true);
  const [focusToken, setFocusToken] = useState(0);
  const [uncategorized, setUncategorized] = useState(false);
  const selected = knowledge.find(item => item.id === selectedId);
  const source = sources.find(item => item.id === sourceId);
  const search = query.trim().toLocaleLowerCase();
  const visible = useMemo(() => uncategorized ? [] : knowledge.filter(item => !search || `${item.title} ${item.english} ${themeTitle}`.toLocaleLowerCase().includes(search)), [search, uncategorized]);

  useEffect(() => {
    document.documentElement.dataset.theme = "light";
  }, []);

  const reset = () => {
    setQuery(""); setUncategorized(false); setSelectedId(null); setDetailOpen(false); setFocusToken(value => value + 1); setRailOpen(false);
  };
  const select = (id: string) => { setSelectedId(id); setDetailOpen(true); setRailOpen(false); };
  const closeDetail = () => { setSelectedId(null); setDetailOpen(false); };
  const graphNodes = useMemo<MemoryKnowledgeGraphNode[]>(() => {
    const make = (id: string, type: string, label: string, summary: string): MemoryKnowledgeGraphNode => ({
      id, type, label, summary, status: "preview", createdAt: "", updatedAt: "",
      metadata: { topicId: "physics", topicLabel: themeTitle }, responsibilityQuestion: "",
      visual: { size: type === "knowledge_item" ? "leaf" : "support" }, childNodeIds: [], contentItems: [],
    });
    const items = visible.map(item => make(item.id, "knowledge_item", showEnglish ? item.english : item.title, item.summary));
    if (layer === "ownership") items.push(make("owner", "team", "示例知识团队", "演示归属，不代表实际权限"));
    else if (showSources) for (const source of sources.filter(s => visible.some(n => n.source === s.id)))
      items.push(make("source-" + source.id, "source_artifact", source.title, source.description));
    return items;
  }, [visible, showEnglish, showSources, layer]);
  const graphEdges = useMemo<MemoryKnowledgeGraphEdge[]>(() => layer !== "ownership" && !showSources ? [] : visible.map(item => ({
    id: "edge-" + item.id, source: item.id, target: layer === "ownership" ? "owner" : "source-" + item.source,
    type: layer === "ownership" ? "owned_by" : "sourced_from", label: layer === "ownership" ? "归属" : "来源于", weight: 1,
    metadata: { layer: layer === "ownership" ? "ownership" : "evidence", status: "preview" },
  })), [visible, layer, showSources]);
  const labelIds = useMemo(() => graphNodes.map(node => node.id), [graphNodes]);

  const rail = <VSurface className="kg-rail !h-full !rounded-none !border-0 !shadow-none">
    <div className="kg-rail-heading"><span>知识导航</span><BookOpen size={15} /></div>
    <label className="kg-search"><Search size={15} aria-hidden="true" /><VNativeInput aria-label="搜索主题或知识" placeholder="搜索主题或知识" value={query} onChange={event => { setQuery(event.target.value); setUncategorized(false); }} />{query && <VButton variant="ghost" className="kg-search-clear" aria-label="清空搜索" icon={<X size={13} />} onClick={() => setQuery("")} />}</label>
    <div className="kg-nav-label">主题</div>
    <nav aria-label="知识主题" className="kg-topic-nav">
      <VButton contentLayout="plain" variant="ghost" className="kg-topic" data-active={!uncategorized} onClick={reset}><Network size={15} /><span>{themeTitle}</span><ChevronRight size={13} /></VButton>
      <VButton contentLayout="plain" variant="ghost" className="kg-topic kg-unfiled" data-active={uncategorized} onClick={() => { setUncategorized(true); setQuery(""); closeDetail(); setRailOpen(false); }}><Folder size={15} /><span>未归类</span></VButton>
    </nav>
    <div className="kg-rail-bottom"><span className="kg-preview-dot" />隔离预览<VButton variant="ghost" aria-label="查看预览说明" className="kg-inline-icon" icon={<Info size={14} />} onClick={() => setSettingsOpen(true)} /></div>
  </VSurface>;

  const inspector = selected && detailOpen ? <VSurface className="kg-inspector !h-full !rounded-none !border-0 !shadow-none">
    <div className="kg-inspector-bar"><span>知识详情</span><VButton variant="ghost" aria-label="关闭知识详情" className="kg-icon-button" icon={<X size={17} />} onClick={closeDetail} /></div>
    <div className="kg-inspector-content">
      <div className="kg-kicker"><span className="kg-mini-dot" />知识条目</div>
      <h2>{selected.title}</h2><p className="kg-detail-english">{selected.english}</p>
      <p className="kg-summary">{selected.summary}</p>
      <div className="kg-detail-section"><h3>来源</h3><p className="kg-small-note">来源连接为演示映射，未接入真实文档。</p>
        <VButton contentLayout="plain" variant="ghost" className="kg-source-card" onClick={() => setSourceId(selected.source)}>
          <span className="kg-source-card-icon"><FileText size={18} /></span><span><strong>{sources.find(item => item.id === selected.source)?.title}</strong><small>合成来源占位 · 可查看说明</small></span><ArrowUpRight size={15} />
        </VButton>
      </div>
      <div className="kg-detail-section"><h3>主题归属</h3><p className="kg-topic-path"><Folder size={14} />{themeTitle}</p></div>
      <div className="kg-detail-note"><Info size={14} /><span>演示释义与来源占位，不代表实际库内内容。</span></div>
    </div>
  </VSurface> : undefined;

  const canvas = <div className="kg-canvas-workspace">
    <header className="kg-topic-toolbar">
      <div className="kg-title-group"><h1>{uncategorized ? "未归类" : themeTitle}</h1><span role="status">{search ? `${visible.length} 条匹配` : `${visible.length} 条知识`}</span></div>
      <div className="kg-toolbar-actions">
        <VTabs aria-label="图谱关系层" value={layer} onValueChange={value => setLayer(value as Layer)} items={Object.entries(layerNames).map(([id, label]) => ({ id, label }))} />
        <VButton variant="ghost" className="kg-settings-button" aria-label="显示设置" title="显示设置" icon={<Settings2 size={17} />} onClick={() => setSettingsOpen(true)} />
      </div>
    </header>
    <div className="kg-graph kg-real-3d" data-layer={layer}>
      {visible.length > 0 ? <VMemoryGraphCanvas nodes={graphNodes} edges={graphEdges}
        selectedNodeId={selectedId ?? ""} highlightIds={labelIds} focusToken={focusToken}
        onSelectNode={id => { if (id.startsWith("source-")) setSourceId(id.slice(7)); else if (id !== "owner") select(id); }}
        fallbackText="三维渲染不可用。当前显示节点列表，不代表 3D 预览已加载。"
        mode="galaxy" appearance="cosmos" groupByTopic />
        : <div className="kg-empty" role="status"><Search size={25} /><h2>{uncategorized ? "暂无未归类知识" : "没有找到相关知识"}</h2><p>试试中文短名或英文名称。</p><VButton variant="secondary" onClick={reset}>返回主题</VButton></div>}
    </div>
    <footer className="kg-legend" aria-label="图例"><span><i className="kg-legend-dot" />知识</span>{layer === "ownership" ? <><span><i className="kg-legend-square" />演示主题</span><span><i className="kg-legend-line kg-legend-dashed" />归属连接</span></> : showSources && <><span><i className="kg-legend-square" />示例来源</span><span><i className="kg-legend-line" />来源连接</span></>}</footer>
  </div>;

  return <VuiProvider><div className="kg-app">
    <header className="kg-app-header"><div className="kg-product-mark"><Network size={19} /><strong>Vibelution</strong></div><div className="kg-breadcrumb"><span>知识</span><ChevronRight size={13} /><span>知识图谱</span></div><span className="kg-header-preview">界面预览</span></header>
    <main className="kg-main"><VWorkbenchFrame><VCanvasWorkbenchPage hideHeader title="知识图谱" ariaLabel="知识图谱清理隔离预览" domainRecipe="memory-knowledge-workbench" className="kg-page !h-full !p-0" layoutId={WORKBENCH_LAYOUT_IDS.memory} rail={rail} canvas={canvas} inspector={inspector} railClassName="kg-rail-wrapper" canvasClassName="kg-canvas-wrapper" inspectorClassName="kg-inspector-wrapper" resize={{ sidebar: { id: "filters", defaultWidth: 224, minWidth: 208, maxWidth: 280 }, aside: { id: "inspector", defaultWidth: 330, minWidth: 300, maxWidth: 400 } }} responsive={{ enabled: true, rail: { label: "知识导航", open: railOpen, onOpenChange: setRailOpen }, inspector: { label: "知识详情", open: detailOpen, onOpenChange: open => { setDetailOpen(open); if (!open) setSelectedId(null); }, narrowPlacement: "bottom" } }} /></VWorkbenchFrame></main>
    <VDialog open={settingsOpen} onOpenChange={setSettingsOpen} title="显示设置" description="让画布只保留当前需要的信息。" size="md" contentClassName="kg-settings-dialog">
      <div className="kg-setting-list">
        {[
          { title: "英文标题", note: "切换英文原名与中文短名；完整内容在详情中阅读", value: showEnglish, toggle: () => setShowEnglish(value => !value) },
          { title: "示例来源与连接", note: "来源采用小方块，连线只表示映射", value: showSources, toggle: () => setShowSources(value => !value) },
        ].map(item => <div className="kg-setting-row" key={item.title}><div><strong>{item.title}</strong><p>{item.note}</p></div><VButton role="switch" aria-checked={item.value} aria-label={item.title} variant="secondary" className="kg-setting-toggle" data-on={item.value} onClick={item.toggle}>{item.value ? <Check size={14} /> : <Minus size={14} />}{item.value ? "显示" : "隐藏"}</VButton></div>)}
      </div>
      <div className="kg-settings-explanation"><h3><Info size={15} />预览范围</h3><p>本预览复用产品原生 Three.js 图谱引擎，保留真实 XYZ 坐标、透视、拖动旋转、平移、滚轮缩放和自动环绕。所有条目、中文释义和来源映射均为确定性演示数据，不连接 API。</p><h3>关系与分组</h3><p>知识层展示条目和示例来源；归属层展示演示主题归属；证据层展开来源名称。空间位置来自三维布局，不代表相似度、支持、反驳或因果关系。</p><h3>低频信息</h3><p>待确认状态与访问权限应从真实数据读取，本预览未模拟审核结果或权限结论；也不会把未读取的资料当作证据。</p></div>
    </VDialog>
    <VDialog open={Boolean(source)} onOpenChange={open => { if (!open) setSourceId(null); }} title={source?.title ?? "示例来源"} description="合成来源占位 · 未读取真实文档" size="md"><div className="kg-source-dialog"><FileText size={25} /><h3>{source?.description}</h3><p>该来源用于检验方块、连接与详情面板的阅读关系，不对应某篇真实文章或实验，也不提供支持或反驳结论。</p><p>正式接入时应在此显示真实标题、来源位置、版本和可读权限。</p></div></VDialog>
  </div></VuiProvider>;
}
