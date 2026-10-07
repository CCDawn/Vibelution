import { useEffect, useRef, useState } from "react";
import { Archive, ArrowUp, BookOpen, Check, ChevronDown, FileText, MessageSquare, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Plus, Search, Settings2, Sparkles, Star, TrendingUp, Wallet } from "lucide-react";
import { VButton, VChip, VConfirmDialog, VDenseTable, VDialog, VDropdownMenu, VIconButton, VInput, VSelect, VSplitWorkspace, VStateSurface, VSurface, VTabs, VTextarea, VToolbar, VuiProvider, type VDenseTableColumn } from "../../src/components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../src/components/layout/workbenchLayoutIds";
import { FinanceSessionMenu, type FinanceSessionAction } from "../../src/routes/finance/FinanceSessionMenu";
import { researchRecordStatus } from "../../src/routes/finance/stockResearchModel";
import type { SessionSummary } from "../../src/api/types";
import "./preview.css";

type Group = "research" | "market" | "assets" | "library";
const groups = [
  { id: "research", label: "研究", icon: MessageSquare, tabs: [{ id: "workspace", label: "股票研究" }, { id: "general", label: "主题研究" }, { id: "team", label: "分析员协作" }, { id: "tasks", label: "研究任务" }, { id: "dashboard", label: "总览" }] },
  { id: "market", label: "行情", icon: TrendingUp, tabs: [{ id: "watchlist", label: "自选行情" }, { id: "screen", label: "股票筛选" }] },
  { id: "assets", label: "资产", icon: Wallet, tabs: [{ id: "account", label: "模拟账户" }, { id: "portfolio", label: "组合研究" }, { id: "review", label: "交易复盘" }] },
  { id: "library", label: "资料", icon: FileText, tabs: [{ id: "reports", label: "报告中心" }, { id: "memory", label: "研究记忆" }, { id: "skills", label: "技能中心" }, { id: "learning", label: "学习中心" }] },
] as const;
const titles = ["贵州茅台 · 财报与估值", "宁德时代 · 现金流分析", "腾讯控股 · 业务增长", "A股消费板块 · 横向比较", "招商银行 · 分红与风险", "美股科技股 · 组合研究", "比亚迪 · 海外业务", "中国移动 · 年报研究", "贵州茅台 · 财报引用核对", "恒瑞医药 · 事件研究", "红利资产 · 组合复盘", "新能源产业链 · 景气跟踪", "腾讯控股 · 估值区间", "三一重工 · 周期研究", "长江电力 · 分红研究", "港股互联网 · 主题研究"];
const initialRecords: SessionSummary[] = titles.map((title, index) => ({ id: `preview-${index}`, title, agentId: "preview-finance", status: "completed", taskSummary: "", lastActive: "2026-10-07T09:30:00+08:00", updatedAt: index < 8 ? "2026-10-07T09:30:00+08:00" : "2026-10-06T15:00:00+08:00", currentPhase: "", terminalReason: "success" }));
type Quote = { id: string; name: string; ticker: string; price: string; change: string; market: string };
const quotes: Quote[] = [
  { id: "600519", name: "贵州茅台", ticker: "600519", price: "1,450.00", change: "+0.68%", market: "CN" },
  { id: "300750", name: "宁德时代", ticker: "300750", price: "265.20", change: "+1.12%", market: "CN" },
  { id: "600036", name: "招商银行", ticker: "600036", price: "41.80", change: "−0.45%", market: "CN" },
  { id: "00700", name: "腾讯控股", ticker: "00700", price: "512.00", change: "+0.39%", market: "HK" },
  { id: "AAPL", name: "Apple", ticker: "AAPL", price: "228.40", change: "+0.26%", market: "US" },
];
type Message = { role: "user" | "assistant"; content: string };
const ghostAction = "!border-transparent !bg-transparent !shadow-none hover:!bg-[var(--vui-control-muted)]";
const sectionLabel = "text-xs font-medium text-vui-fg-tertiary";

export function FinanceConversationPreview() {
  const [group, setGroup] = useState<Group>("research"), [area, setArea] = useState("workspace");
  const [records, setRecords] = useState(initialRecords), [selectedId, setSelectedId] = useState("preview-0");
  const [search, setSearch] = useState(""), [archived, setArchived] = useState(false);
  const [leftClosed, setLeftClosed] = useState(false), [rightClosed, setRightClosed] = useState(false);
  const [inspectorTab, setInspectorTab] = useState("process"), [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<Message[]>([]), [notice, setNotice] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false), [deleteTarget, setDeleteTarget] = useState<SessionSummary | null>(null);
  const sessionListRef = useRef<HTMLDivElement>(null);
  const selected = records.find(row => row.id === selectedId);
  const activeGroup = groups.find(item => item.id === group)!;
  const selectedTitle = selected?.title || "新研究";
  const researchComplete = selected?.status === "completed";
  const currentQuote = quotes.find(row => selectedTitle.startsWith(row.name));
  const filtered = records.filter(row => (row.archiveState?.status === "archived") === archived && row.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  useEffect(() => {
    const list = sessionListRef.current;
    const active = list?.querySelector<HTMLElement>('button[aria-pressed="true"]');
    if (list && active) active.scrollIntoView({ block: "nearest" });
  }, [selectedId, archived]);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(""), 4500);
    return () => clearTimeout(timer);
  }, [notice]);
  function navigate(next: Group, nextArea?: string) { setGroup(next); setArea(nextArea || groups.find(item => item.id === next)!.tabs[0].id); }
  function openRecord(row: SessionSummary) { setSelectedId(row.id); setMessages([]); setDraft(""); navigate("research"); }
  function newResearch() {
    const now = new Date().toISOString();
    const row: SessionSummary = { id: `preview-new-${Date.now()}`, title: "新研究", status: "idle", taskSummary: "", lastActive: now, updatedAt: now, currentPhase: "" };
    setRecords(current => [row, ...current]); setArchived(false); setSearch(""); openRecord(row);
  }
  function sessionAction(row: SessionSummary, action: FinanceSessionAction) {
    if (action === "delete") { setDeleteTarget(row); return; }
    setRecords(current => current.map(item => item.id === row.id ? { ...item, archiveState: { status: action === "archive" ? "archived" : "active" } } : item));
    if (row.id === selectedId && action === "archive") { setSelectedId(""); setMessages([]); }
    setNotice(action === "archive" ? "示例会话已归档，可在「已归档」中恢复" : "示例会话已恢复");
  }
  function send() {
    if (!draft.trim()) return;
    setMessages(current => [...current, { role: "user", content: draft.trim() }, { role: "assistant", content: "这是一条预览回复，用于查看追问后的布局。" }]);
    setDraft("");
  }
  const sidebar = <VSurface tone="row" padding="none" className="flex h-full min-h-0 flex-col !rounded-none !border-0" ariaLabel="研究会话栏">
    <div className="flex shrink-0 items-center justify-between px-4 pb-2 pt-4"><strong className="text-sm font-semibold">研究会话</strong><VIconButton variant="ghost" label="收起会话栏" icon={<PanelLeftClose size={16} />} className={ghostAction} onPress={() => setLeftClosed(true)} /></div>
    <div className="shrink-0 px-3"><VButton className="!w-full !justify-start" variant="secondary" icon={<Plus size={16} />} onPress={newResearch}>新研究</VButton><div className="relative mt-3"><Search className="pointer-events-none absolute left-2.5 top-2" size={14} /><VInput className="!w-full !pl-8" value={search} onChange={event => setSearch(event.target.value)} aria-label="搜索会话" placeholder="搜索会话" /></div></div>
    <div className="flex shrink-0 items-center justify-between px-4 pb-1 pt-3"><VDropdownMenu aria-label="会话范围" align="start" trigger={<VButton variant="ghost" className={`${ghostAction} !h-6 !min-h-6 !px-0 !text-xs`} icon={archived ? <Archive size={13} /> : undefined} trailingIcon={<ChevronDown size={12} />}>{archived ? "已归档" : "最近会话"}</VButton>} items={[{ id: "recent", label: "最近会话", onSelect: () => setArchived(false) }, { id: "archived", label: "已归档", icon: <Archive size={14} />, onSelect: () => setArchived(true) }]} /><span className={sectionLabel}>{filtered.length}</span></div>
    <div ref={sessionListRef} className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" data-preview-session-scroll aria-label="会话列表">
      {filtered.length ? <>{["今天", "昨天"].map((label, index) => { const rows = filtered.filter(row => (new Date(row.updatedAt).toLocaleDateString("en-CA", { timeZone: "Asia/Shanghai" }) < "2026-10-07") === Boolean(index)); return rows.length ? <section className="mb-3" key={label}><div className={`${sectionLabel} px-2 pb-2 pt-2`}>{label}</div><PreviewSessionRows records={rows} selectedId={selectedId} onOpen={openRecord} onAction={sessionAction} /></section> : null; })}</> : <VStateSurface density="compact" tone="empty" title={search ? "没有匹配的会话" : "暂无会话"} />}
    </div>
    <footer className="shrink-0 border-t border-vui-border-subtle px-3 pb-3 pt-2"><div className={`${sectionLabel} px-1 pb-1.5`}>工作台</div><nav aria-label="工作台功能分组" className="grid grid-cols-2 gap-1">{groups.map(item => <VButton key={item.id} variant="ghost" className={`!w-full !justify-start !border-transparent !shadow-none ${group === item.id ? "!bg-[color-mix(in_srgb,var(--accent-cool)_9%,transparent)] !text-[var(--accent-cool)]" : ghostAction}`} aria-pressed={group === item.id} icon={<item.icon size={16} />} onPress={() => navigate(item.id)}>{item.label}</VButton>)}</nav><div className="mt-2 flex items-center justify-between border-t border-vui-border-subtle pt-2"><span className="text-xs text-vui-fg-tertiary">布局预览 · 示例数据</span><VIconButton variant="ghost" label="助手设置" className={ghostAction} icon={<Settings2 size={15} />} onPress={() => setSettingsOpen(true)} /></div></footer>
  </VSurface>;
  const aside = <VSurface tone="row" padding="none" className="flex h-full min-h-0 flex-col !rounded-none !border-0" ariaLabel="研究辅助面板">
    <div className="flex shrink-0 items-center gap-1 px-3 pb-3 pt-4"><VTabs className="min-w-0 flex-1" value={inspectorTab} onValueChange={setInspectorTab} aria-label="研究辅助内容" items={[{ id: "process", label: "研究过程" }, { id: "sources", label: "引用与资料" }]} /><VIconButton label="收起辅助栏" variant="ghost" className={ghostAction} icon={<PanelRightClose size={16} />} onPress={() => setRightClosed(true)} /></div>
    <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
      {inspectorTab === "process" ? <>
        <div className="mb-3 flex min-w-0 items-center gap-2 border-b border-vui-border-subtle pb-3" data-preview-inline>
          <strong className="min-w-0 flex-1 truncate text-sm font-medium" title={selectedTitle}>{selectedTitle}</strong>
          <span className={`inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-xs ${researchComplete ? "text-[var(--state-success)]" : "text-vui-fg-tertiary"}`}>
            {researchComplete ? <Check size={13} /> : <MessageSquare size={13} />}{researchComplete ? "已完成" : "待开始"}
          </span>
        </div>
        <ol className="m-0 list-none space-y-1 p-0">
          {["读取财报资料", "核对财务指标", "检索新闻公告", "比较估值与风险", "整理研究报告"].map((label, index) => <li className="flex min-w-0 items-center gap-2 py-2" data-preview-inline key={label}>
            <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs ${researchComplete ? "bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]" : "bg-vui-surface-inset text-vui-fg-tertiary"}`}>{researchComplete ? <Check size={12} /> : index + 1}</span>
            <span className="min-w-0 flex-1 truncate text-sm" title={label}>{label}</span>
            <span className="shrink-0 whitespace-nowrap text-xs text-vui-fg-tertiary">{researchComplete ? "已完成" : "待执行"}</span>
          </li>)}
        </ol>
        <VButton variant="ghost" className={`${ghostAction} mt-4 !text-xs`} icon={<FileText size={14} />} onPress={() => { navigate("library"); setInspectorTab("sources"); }}>查看研究报告</VButton>
      </> : <>
        <div className="mb-3 flex items-center justify-between"><span className="whitespace-nowrap text-sm font-medium">财报资料</span><VChip tone="neutral">3</VChip></div>
        {["2024 年度报告", "财务报表及附注", "董事会报告"].map((title, index) => <VButton key={title} title={`${title} · PDF 第 ${[5, 63, 18][index]} 页`} variant="ghost" contentLayout="plain" className="mb-1 !min-h-9 !w-full !justify-start !px-2 !py-2 !text-left" onPress={() => setNotice(`已选择示例引用：${title}`)}>
          <span className="flex w-full min-w-0 items-center gap-2" data-preview-inline><FileText size={15} className="shrink-0 text-vui-fg-tertiary" /><strong className="min-w-0 flex-1 truncate text-xs font-medium">{title}</strong><span className="shrink-0 whitespace-nowrap text-xs tabular-nums text-vui-fg-tertiary">p.{[5, 63, 18][index]}</span></span>
        </VButton>)}
        <VButton variant="ghost" className={`${ghostAction} mt-3 !text-xs`} icon={<BookOpen size={14} />} onPress={() => navigate("library", "memory")}>管理研究资料</VButton>
      </>}
    </div>
  </VSurface>;
  const main = <div className="flex h-full min-h-0 flex-col bg-vui-surface-panel">
    <VToolbar ariaLabel="当前研究操作" wrap={false} className="shrink-0 !justify-between border-b border-vui-border-subtle px-5 py-3">
      <div className="flex min-w-0 flex-1 items-center gap-3" data-preview-inline>{leftClosed ? <VIconButton variant="ghost" label="展开会话栏" className={ghostAction} icon={<PanelLeftOpen size={16} />} onPress={() => setLeftClosed(false)} /> : null}<h1 className="m-0 min-w-0 truncate text-sm font-semibold" title={group === "research" ? selectedTitle : activeGroup.label}>{group === "research" ? selectedTitle : activeGroup.label}</h1>{group === "research" && currentQuote ? <span className="shrink-0 whitespace-nowrap text-xs tabular-nums text-vui-fg-tertiary">{currentQuote.ticker}</span> : null}</div>
      <div className="flex shrink-0 items-center gap-2"><VChip tone="neutral">示例</VChip>{group === "research" ? <VButton variant="ghost" className={ghostAction} icon={<FileText size={14} />} onPress={() => navigate("library")}>报告</VButton> : null}{rightClosed ? <VIconButton variant="ghost" label="展开辅助栏" className={ghostAction} icon={<PanelRightOpen size={16} />} onPress={() => setRightClosed(false)} /> : null}</div>
    </VToolbar>
    <div className="shrink-0 px-5 py-3"><VTabs value={area} onValueChange={setArea} aria-label={`${activeGroup.label}功能`} items={activeGroup.tabs.map(item => ({ ...item }))} listClassName="!justify-start" /></div>
    {group === "research" && (area === "workspace" || area === "general") ? <>
      <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6" aria-label="研究对话" data-preview-conversation>
        {selected?.status === "idle" || !selected ? <div className="mx-auto max-w-2xl py-16"><div className="mb-3 flex items-center gap-2" data-preview-inline><Sparkles size={20} className="shrink-0 text-[var(--accent-cool)]" /><h2 className="m-0 truncate text-xl font-semibold">开始一项研究</h2></div><p className="mb-6 text-sm text-vui-fg-secondary">输入股票代码、公司名称或你想研究的问题。</p><div className="flex flex-nowrap gap-2 overflow-x-auto">{["分析贵州茅台财报", "比较两家公司的估值", "复盘我的模拟持仓"].map(label => <VButton key={label} variant="secondary" onPress={() => setDraft(label)}>{label}</VButton>)}</div></div> : <div className="mx-auto max-w-3xl"><div className="ml-auto mt-3 w-fit max-w-[85%] rounded-xl bg-vui-surface-inset px-4 py-3 text-sm leading-6">分析{currentQuote?.name || selectedTitle}的盈利质量、估值和主要风险，并列出财报依据。</div><article className="mt-6"><div className="mb-4 flex items-center gap-2 text-xs font-medium text-vui-fg-secondary"><Sparkles size={15} className="text-[var(--accent-cool)]" />炒股智能体</div><h2 className="mb-3 mt-0 text-lg font-semibold">先看盈利质量，再看估值与分红</h2><p className="m-0 text-sm leading-7 text-vui-fg-secondary">结合利润、现金回款与资本开支判断经营质量；估值需要与历史区间和同业对照。</p><VSurface tone="inset" padding="normal" className="mt-5"><div className="grid gap-3">{[{ title: "经营质量", value: "核对现金回款" }, { title: "估值判断", value: "对照历史区间" }, { title: "主要风险", value: "关注需求变化" }].map(item => <div key={item.title} className="flex min-w-0 items-center gap-4" data-preview-inline><span className="shrink-0 whitespace-nowrap text-xs text-vui-fg-tertiary">{item.title}</span><span className="min-w-0 truncate text-sm font-medium" title={item.value}>{item.value}</span></div>)}</div></VSurface><h3 className="mb-2 mt-5 text-sm font-semibold">需要进一步核对</h3><ul className="m-0 space-y-2 pl-5 text-sm leading-6 text-vui-fg-secondary"><li>收入、经营现金流和应收项目是否相互印证。</li><li>分红与资本开支变化，是否影响未来现金回报。</li></ul><div className="mt-5 flex flex-nowrap items-center gap-2"><VButton variant="ghost" className={`${ghostAction} !text-xs`} icon={<FileText size={14} />} onPress={() => { setInspectorTab("sources"); setRightClosed(false); }}>3 条财报引用</VButton><VButton variant="ghost" className={`${ghostAction} !text-xs`} onPress={() => navigate("library")}>查看完整报告</VButton></div></article></div>}
        {messages.map((message, index) => <div key={index} className={`mx-auto mt-4 max-w-3xl text-sm leading-7 ${message.role === "user" ? "rounded-lg bg-vui-surface-inset px-4 py-3" : "px-1"}`}>{message.content}</div>)}
      </div>
      <div className="shrink-0 px-5 pb-4 pt-2"><VSurface padding="normal" className="mx-auto max-w-3xl" ariaLabel="研究输入"><VTextarea aria-label="研究问题" placeholder="继续追问，或输入股票代码…" value={draft} onChange={event => setDraft(event.target.value)} rows={2} className="!min-h-12 !resize-none !border-0 !bg-transparent !p-0 !shadow-none focus-visible:!ring-0" onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); } }} /><div className="mt-2 flex items-center justify-between"><VButton variant="ghost" className={`${ghostAction} !text-xs`} icon={<Settings2 size={13} />} onPress={() => setSettingsOpen(true)}>研究设置</VButton><VIconButton variant="primary" label="发送研究问题" icon={<ArrowUp size={16} />} isDisabled={!draft.trim()} onPress={send} /></div></VSurface></div>
    </> : <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5"><AreaPreview area={area} onResearch={() => navigate("research")} onNotice={setNotice} /></div>}
    {notice ? <div role="status" className="shrink-0 border-t border-vui-border-subtle bg-vui-surface-inset px-5 py-2 text-xs text-vui-fg-secondary">{notice}</div> : null}
  </div>;
  return <VuiProvider><div className="finance-preview flex h-dvh min-h-0 flex-col overflow-hidden bg-vui-surface-workspace text-vui-fg-primary" data-vui-domain-recipe="financial-assistant-workspace-preview"><VSplitWorkspace className="h-full !gap-0" sidebar={sidebar} main={main} aside={aside} resize={{ layoutId: WORKBENCH_LAYOUT_IDS.finance, sidebar: { defaultWidth: 244, minWidth: 220, maxWidth: 340 }, aside: { defaultWidth: 292, minWidth: 260, maxWidth: 380 }, collapse: { sidebar: { placement: "header", collapsed: leftClosed, onCollapsedChange: setLeftClosed, separatorLabel: "调整会话栏宽度", collapseLabel: "收起会话栏", expandLabel: "展开会话栏" }, aside: { placement: "header", collapsed: rightClosed, onCollapsedChange: setRightClosed, separatorLabel: "调整辅助栏宽度", collapseLabel: "收起辅助栏", expandLabel: "展开辅助栏" } } }} /></div>
    <VDialog open={settingsOpen} onOpenChange={setSettingsOpen} title="研究设置" description="示例设置，仅在预览中查看。" footer={<VButton onPress={() => setSettingsOpen(false)}>完成</VButton>}><div className="grid gap-4"><label className="flex items-center gap-4 whitespace-nowrap text-sm">研究范围<VSelect className="min-w-0 flex-1" aria-label="研究范围" defaultSelectedKey="comprehensive" options={[{ id: "comprehensive", label: "综合研究" }, { id: "financial", label: "财报分析" }, { id: "risk", label: "风险评估" }]} /></label><label className="flex items-center gap-4 whitespace-nowrap text-sm">研究深度<VSelect className="min-w-0 flex-1" aria-label="研究深度" defaultSelectedKey="brief" options={[{ id: "brief", label: "简明" }, { id: "detailed", label: "详细核对" }]} /></label></div></VDialog>
    <VConfirmDialog open={Boolean(deleteTarget)} onOpenChange={open => { if (!open) setDeleteTarget(null); }} title="删除示例会话？" description={deleteTarget?.title} tone="danger" confirmLabel="删除" cancelLabel="取消" onCancel={() => setDeleteTarget(null)} onConfirm={() => { const id = deleteTarget?.id; setRecords(current => current.filter(row => row.id !== id)); if (selectedId === id) setSelectedId(""); setDeleteTarget(null); setNotice("示例会话已删除；真实会话未修改"); }} />
  </VuiProvider>;
}

function PreviewSessionRows({ records, selectedId, onOpen, onAction }: {
  records: SessionSummary[];
  selectedId: string;
  onOpen: (record: SessionSummary) => void;
  onAction: (record: SessionSummary, action: FinanceSessionAction) => void;
}) {
  return <div className="grid min-w-0 gap-1" data-preview-session-rows>{records.map(row => <div key={row.id} className="flex min-w-0 items-center gap-1" data-preview-session-row>
    <VButton variant="ghost" contentLayout="plain" title={row.title} className={`!min-h-8 min-w-0 flex-1 !justify-start !px-2 !py-1.5 !text-left ${row.id === selectedId ? "!bg-[color-mix(in_srgb,var(--accent-cool)_9%,transparent)]" : ghostAction}`} aria-pressed={row.id === selectedId} onPress={() => onOpen(row)}>
      <span className="flex w-full min-w-0 items-center gap-2" data-preview-inline>
        <strong className="min-w-0 flex-1 truncate text-xs font-medium">{row.title}</strong>
        <span className="inline-flex shrink-0 items-center whitespace-nowrap text-xs text-vui-fg-tertiary" title={researchRecordStatus(row, true)}>{researchRecordStatus(row, false) === "Completed" ? <Check size={13} className="text-[var(--state-success)]" /> : <MessageSquare size={13} />}<span className="sr-only">{researchRecordStatus(row, true)}</span></span>
      </span>
    </VButton>
    <FinanceSessionMenu record={row} zh onAction={onAction} />
  </div>)}</div>;
}

function AreaPreview({ area, onResearch, onNotice }: { area: string; onResearch: () => void; onNotice: (message: string) => void }) {
  const [stockSearch, setStockSearch] = useState(""), [market, setMarket] = useState("CN");
  const matchingQuotes = quotes.filter(row => row.market === market && `${row.name} ${row.ticker}`.toLowerCase().includes(stockSearch.toLowerCase()));
  const quoteColumns: VDenseTableColumn<Quote>[] = [{ id: "name", header: "股票", fill: true, minWidth: 160, render: row => <span className="flex min-w-0 items-center gap-2" data-preview-inline><strong className="min-w-0 truncate font-medium" title={row.name}>{row.name}</strong><span className="shrink-0 whitespace-nowrap text-xs tabular-nums text-vui-fg-tertiary">{row.ticker}</span></span> }, { id: "price", header: "现价", width: 105, align: "right", render: row => row.price }, { id: "change", header: "涨跌幅", width: 105, align: "right", render: row => <span className={row.change.startsWith("−") ? "text-[var(--state-success)]" : "text-[var(--state-danger)]"}>{row.change}</span> }, { id: "action", header: "", width: 100, align: "right", render: () => <VButton variant="ghost" className={ghostAction} onPress={onResearch}>研究</VButton> }];
  if (area === "watchlist" || area === "screen") return <><VToolbar ariaLabel="查找股票" wrap={false} className="mb-5 gap-3"><VSelect aria-label="股票市场" selectedKey={market} onSelectionChange={key => setMarket(String(key))} options={[{ id: "CN", label: "A股" }, { id: "HK", label: "港股" }, { id: "US", label: "美股" }]} className="w-28" /><VInput aria-label="查找股票" placeholder="公司名称 / 股票代码" value={stockSearch} onChange={event => setStockSearch(event.target.value)} className="min-w-0 flex-1" /><VButton variant="secondary" icon={<Star size={14} />} onPress={() => onNotice("自选管理为预览操作，不会保存真实股票")}>管理自选</VButton></VToolbar><h2 className="mb-4 text-sm font-semibold">{area === "screen" ? "筛选结果" : "我的自选"}</h2><VDenseTable ariaLabel="示例股票行情" rows={matchingQuotes} getRowKey={row => row.id} columns={quoteColumns} emptyText="没有匹配股票" /></>;
  if (area === "reports") return <><VToolbar ariaLabel="报告筛选" wrap={false} className="mb-5"><VInput placeholder="查找报告" aria-label="查找报告" className="min-w-0 flex-1" /><VButton variant="secondary" icon={<FileText size={14} />} onPress={() => onNotice("这是示例报告列表，未导出真实报告")}>导出</VButton></VToolbar><h2 className="mb-3 text-sm font-semibold">已完成报告</h2>{titles.slice(0, 5).map((title, index) => <div className="flex min-w-0 items-center gap-3 border-b border-vui-border-subtle py-2" data-preview-inline key={title}><FileText size={15} className="shrink-0 text-vui-fg-tertiary" /><strong className="min-w-0 flex-1 truncate text-sm font-medium" title={title}>{title}</strong><span className="shrink-0 whitespace-nowrap text-xs text-vui-fg-tertiary">{index < 3 ? "今天" : "昨天"}</span><VButton variant="ghost" className={`${ghostAction} shrink-0`} onPress={onResearch}>打开研究</VButton></div>)}</>;
  if (["account", "portfolio", "review"].includes(area)) return <><h2 className="mb-4 text-sm font-semibold">{area === "account" ? "模拟账户" : area === "portfolio" ? "组合研究" : "交易复盘"}</h2><VSurface tone="inset" padding="normal" className="mb-5"><div className="grid gap-3">{[{ title: "总资产", value: "100,000.00" }, { title: "可用资金", value: "46,200.00" }, { title: "持仓市值", value: "53,800.00" }].map(item => <div key={item.title} className="flex min-w-0 items-center justify-between gap-3" data-preview-inline><span className="shrink-0 whitespace-nowrap text-xs text-vui-fg-tertiary">{item.title}</span><strong className="truncate text-sm font-semibold tabular-nums">{item.value}</strong></div>)}</div></VSurface><VDenseTable ariaLabel="示例持仓" rows={quotes.slice(0, 3)} getRowKey={row => row.id} columns={quoteColumns} /><VButton className="mt-5" variant="secondary" onPress={onResearch}>研究当前组合</VButton></>;
  if (area === "team" || area === "tasks" || area === "dashboard") return <><h2 className="mb-3 text-sm font-semibold">{area === "team" ? "分析员协作" : area === "tasks" ? "研究任务" : "工作台总览"}</h2>{["财报分析", "市场与新闻", "估值比较", "风险评估"].map((title, index) => <div key={title} className="flex min-w-0 items-center gap-3 border-b border-vui-border-subtle py-2" data-preview-inline><Check size={15} className="shrink-0 text-[var(--state-success)]" /><strong className="shrink-0 whitespace-nowrap text-sm font-medium">{title}</strong><span className="min-w-0 flex-1 truncate text-xs text-vui-fg-tertiary" title={["利润与现金回款", "公司公告与行业动态", "历史估值与同业对比", "风险因素与证据缺口"][index]}>{["利润与现金回款", "公司公告与行业动态", "历史估值与同业对比", "风险因素与证据缺口"][index]}</span><VChip tone="success">已完成</VChip><VButton variant="ghost" className={`${ghostAction} shrink-0 !text-xs`} onPress={onResearch}>打开研究</VButton></div>)}</>;
  const content = area === "memory" ? ["已保存的研究结论", "财报引用与资料"] : area === "skills" ? ["财报分析", "估值比较", "持仓风险评估"] : ["财务报表阅读", "估值方法", "研究与复盘"];
  return <><h2 className="mb-3 text-sm font-semibold">{area === "memory" ? "研究记忆" : area === "skills" ? "技能中心" : "学习中心"}</h2>{content.map(title => <div key={title} className="flex min-w-0 items-center gap-3 border-b border-vui-border-subtle py-2" data-preview-inline><BookOpen size={15} className="shrink-0 text-vui-fg-tertiary" /><span className="min-w-0 flex-1 truncate text-sm" title={title}>{title}</span><VButton variant="ghost" className={`${ghostAction} shrink-0`} onPress={() => onNotice(`已选择示例内容：${title}`)}>查看</VButton></div>)}</>;
}
