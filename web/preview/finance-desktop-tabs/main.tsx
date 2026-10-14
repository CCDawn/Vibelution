import { useEffect, useRef, useState } from "react";
import { Archive, ArrowUp, BookOpen, Bot, Check, ChevronDown, FileText, History, Maximize2, MessageSquare, MoreHorizontal, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Plus, Search, Settings2, Sparkles, Square, TrendingUp, Wallet, X } from "lucide-react";
import { VButton, VCheckbox, VChip, VConfirmDialog, VDialog, VDropdownMenu, VIconButton, VInput, VSelect, VSplitWorkspace, VStateSurface, VSurface, VTabs, VTextarea, VuiProvider } from "../../src/components/vui";
import { WORKBENCH_LAYOUT_IDS } from "../../src/components/layout/workbenchLayoutIds";
import { FINANCE_WORKSPACE_GROUPS } from "../../src/routes/finance/financeWorkspaceNavigation";
import { FinanceSessionMenu, type FinanceSessionAction } from "../../src/routes/finance/FinanceSessionMenu";
import type { SessionSummary } from "../../src/api/types";
import { FinanceToolPreview } from "./tools";
import { FinanceResearchDetailPreview } from "./research-detail";
import "./preview.css";

type PreviewSession = SessionSummary & { draft: string; scroll: number; detailArea?: string | null; detailScrolls?: Record<string, number>; messages: { role: "user" | "assistant"; text: string }[] };
const sessionTitles = ["贵州茅台 · 财报与估值", "宁德时代 · 现金流", "消费板块 · 横向比较", "招商银行 · 分红研究", "比亚迪 · 经营分析", "长江电力 · 分红与资本开支", "恒瑞医药 · 事件研究", "红利资产 · 组合复盘", "新能源产业链 · 景气跟踪", "三一重工 · 周期研究", "中国移动 · 年报研究", "贵州茅台 · 公告核对"];
const initialSessions: PreviewSession[] = sessionTitles.map((title, index) => ({
  id: `layout-preview-${index}`, title, agentId: "layout-preview-agent", status: index === 1 ? "running" : "completed",
  taskSummary: "", lastActive: "2026-10-13T17:20:00+08:00", updatedAt: "2026-10-13T17:20:00+08:00", currentPhase: "", terminalReason: index === 1 ? undefined : "success",
  archiveState: { status: index === 11 ? "archived" : "active" }, draft: "", scroll: 0, messages: [],
}));
const icons = { research: MessageSquare, market: TrendingUp, assets: Wallet, library: BookOpen };
const titleFor = (area: string) => area === "process" ? "研究过程" : area === "sources" ? "引用资料" : FINANCE_WORKSPACE_GROUPS.map(g => g.areas.find(a => a.id === area)).find(Boolean)?.zh || "工具";
const storageKey = "finance-desktop-tabs-preview.v1";
type SavedPreview = { sessions: PreviewSession[]; opened: string[]; selected: string; model: string };
function loadPreview(): SavedPreview {
  try {
    const raw = JSON.parse(localStorage.getItem(storageKey) || "null") as SavedPreview | null;
    if (raw && Array.isArray(raw.sessions) && Array.isArray(raw.opened) && typeof raw.model === "string") return raw;
  } catch { /* A fresh preview works when local storage is unavailable. */ }
  return { sessions: initialSessions, opened: initialSessions.slice(0, 3).map(s => s.id), selected: initialSessions[0].id, model: "flash" };
}

export function FinanceDesktopTabsPreview() {
  const [initial] = useState(loadPreview);
  const [sessions, setSessions] = useState(initial.sessions);
  const [opened, setOpened] = useState(initial.opened);
  const [selectedId, setSelectedId] = useState(initial.selected);
  const [model, setModel] = useState(initial.model);
  const [stagedModel, setStagedModel] = useState(initial.model);
  const [leftClosed, setLeftClosed] = useState(false);
  const [narrowDesktop, setNarrowDesktop] = useState(() => window.innerWidth < 1080);
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [emptyArea, setEmptyArea] = useState<string | null>(null);
  const [rightClosed, setRightClosed] = useState(false);
  const [toolExpanded, setToolExpanded] = useState(false);
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [collection, setCollection] = useState("recent");
  const [search, setSearch] = useState("");
  const [managing, setManaging] = useState(false);
  const [checked, setChecked] = useState<string[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<PreviewSession | null>(null);
  const [renameText, setRenameText] = useState("");
  const [deleteIds, setDeleteIds] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const workspaceRef = useRef<HTMLDivElement>(null);
  const detailRef = useRef<HTMLDivElement>(null);
  const conversationRef = useRef<HTMLDivElement>(null);
  const tabsRef = useRef<HTMLDivElement>(null);
  const selected = sessions.find(s => s.id === selectedId);
  const tool = selected ? selected.detailArea || null : emptyArea;
  const draft = selected?.draft || "";
  const running = selected?.status === "running";
  const visibleSessions = sessions.filter(s => (s.archiveState?.status === "archived") === (collection === "archived") && s.title.includes(search.trim()));
  const openedSessions = opened.map(id => sessions.find(s => s.id === id)).filter((s): s is PreviewSession => !!s && s.archiveState?.status !== "archived");
  const modelLabel = model === "flash" ? "Qwen3.8 Flash" : "模型 B · 示例";
  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify({ sessions, opened, selected: selectedId, model })); } catch { /* State remains usable in memory. */ }
  }, [sessions, opened, selectedId, model]);
  useEffect(() => { if (conversationRef.current) conversationRef.current.scrollTop = selected?.scroll || 0; }, [selectedId, tool, leftClosed, rightClosed]);
  useEffect(() => { if (detailRef.current) detailRef.current.scrollTop = selected?.detailScrolls?.[tool || "report"] || 0; }, [selectedId, tool, leftClosed, rightClosed, narrowDesktop]);
  useEffect(() => {
    const scroller = tabsRef.current;
    if (!scroller) return;
    const keepActiveVisible = () => scroller.querySelector<HTMLElement>('[data-state="active"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
    keepActiveVisible();
    const observer = new ResizeObserver(keepActiveVisible);
    observer.observe(scroller);
    return () => observer.disconnect();
  }, [selectedId, opened.length, tool, leftClosed, rightClosed]);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(""), 4500); return () => clearTimeout(timer); }, [notice]);
  useEffect(() => {
    const root = workspaceRef.current;
    if (!root) return;
    const observer = new ResizeObserver(entries => setNarrowDesktop(entries[0].contentRect.width < 1080));
    observer.observe(root);
    return () => observer.disconnect();
  }, []);
  function updateSession(id: string, patch: Partial<PreviewSession>) { setSessions(rows => rows.map(s => s.id === id ? { ...s, ...patch } : s)); }
  function setTool(next: string | null) { if (selected) updateSession(selected.id, { detailArea: next }); else setEmptyArea(next); }
  function openSession(id: string) {
    if (conversationRef.current && selected) updateSession(selected.id, { scroll: conversationRef.current.scrollTop });
    setOpened(ids => ids.includes(id) ? ids : [...ids, id]); setSelectedId(id);
  }
  function closeSession(id: string) {
    const ids = opened.filter(x => x !== id); setOpened(ids);
    if (selectedId === id) setSelectedId(ids[Math.max(0, opened.indexOf(id) - 1)] || "");
    setNotice("标签已关闭，会话保留在全部会话中");
  }
  function newSession(initialDraft = "") {
    const id = `layout-preview-new-${Date.now()}`;
    const row: PreviewSession = { id, title: "新会话", agentId: "layout-preview-agent", status: "idle", taskSummary: "", lastActive: new Date().toISOString(), updatedAt: new Date().toISOString(), currentPhase: "", draft: initialDraft, scroll: 0, messages: [] };
    setSessions(rows => [row, ...rows]); openSession(id);
  }
  function act(row: SessionSummary, action: FinanceSessionAction) {
    if (action === "delete") { setDeleteIds([row.id]); return; }
    updateSession(row.id, { archiveState: { status: action === "archive" ? "archived" : "active" } });
    if (action === "archive" && opened.includes(row.id)) closeSession(row.id);
    setNotice(action === "archive" ? "示例会话已归档，可在全部会话中恢复" : "示例会话已恢复");
  }
  function batchArchive() {
    const targets = checked.filter(id => sessions.find(s => s.id === id)?.status !== "running");
    setSessions(rows => rows.map(s => targets.includes(s.id) ? { ...s, archiveState: { status: collection === "archived" ? "active" : "archived" } } : s));
    if (collection !== "archived") { const remaining = opened.filter(id => !targets.includes(id)); setOpened(remaining); if (targets.includes(selectedId)) setSelectedId(remaining[0] || ""); }
    setChecked([]); setNotice(collection === "archived" ? "选中的示例会话已恢复" : "选中的示例会话已归档");
  }
  function ask(text: string) { setRightClosed(false); if (!selected) { newSession(text); return; } updateSession(selected.id, { draft: text }); }
  function send() {
    if (!selected || !draft.trim() || running) return;
    updateSession(selected.id, { title: selected.title === "新会话" ? draft.trim().slice(0, 22) : selected.title, draft: "", status: "completed", messages: [...selected.messages, { role: "user", text: draft.trim() }, { role: "assistant", text: "这是一条示例回复。正式接入后，这里继续显示原生 Agent 的执行过程、资料引用和研究结论。" }] });
  }
  function navigate(area: string) {
    setNavigationOpen(false);
    setToolExpanded(false);
    if (area === "workspace" || area === "general") { setTool(null); if (area === "general") ask("比较A股消费板块的盈利质量与估值"); else if (!selected) newSession(); }
    else setTool(area);
  }
  const sidebar = <VSurface tone="row" padding="none" className="functional-sidebar" ariaLabel="功能导航">
    <div className="sidebar-brand"><span className="brand-icon"><TrendingUp size={17} /></span><strong>A股智能体</strong><VIconButton variant="ghost" className="quiet" label="收起功能栏" icon={<PanelLeftClose size={16} />} onPress={() => { setLeftClosed(true); setNavigationOpen(false); }} /></div>
    <nav className="function-scroll" aria-label="股票智能体功能">{FINANCE_WORKSPACE_GROUPS.map(group => { const Icon = icons[group.id]; return <section key={group.id}><div className="function-group"><Icon size={13} /><span>{group.zh}</span></div>{group.areas.map(area => <VButton key={area.id} variant="ghost" className={`function-link quiet ${(tool === area.id || (!tool && area.id === "workspace")) ? "selected" : ""}`} aria-pressed={tool === area.id || (!tool && area.id === "workspace")} onPress={() => navigate(area.id)}><span>{area.zh}</span>{tool === area.id ? <span className="active-dot" /> : null}</VButton>)}</section>; })}</nav>
    <footer className="agent-footer"><div className="agent-line"><Bot size={16} /><strong>A股研究助手</strong><VIconButton className="quiet" variant="ghost" label="当前Agent设置" icon={<Settings2 size={15} />} onPress={() => { setNavigationOpen(false); setStagedModel(model); setSettingsOpen(true); }} /></div><VButton variant="ghost" className="model-button quiet" icon={<Sparkles size={14} />} trailingIcon={<ChevronDown size={13} />} onPress={() => { setNavigationOpen(false); setStagedModel(model); setSettingsOpen(true); }}>{modelLabel}</VButton><small>桌面预览 · 示例数据</small></footer>
  </VSurface>;
  const sessionBar = <div className="session-bar">
    {leftClosed || narrowDesktop ? <VIconButton className="quiet" variant="ghost" label="展开功能栏" icon={<PanelLeftOpen size={16} />} onPress={() => { if (narrowDesktop) setNavigationOpen(true); else setLeftClosed(false); }} /> : null}
    <div ref={tabsRef} className="session-tabs-scroll" data-preview-tabs-scroll>{openedSessions.length ? <VTabs aria-label="已打开的会话" value={selectedId} onValueChange={openSession} className="session-tabs" listClassName="session-tabs-list" triggerClassName="session-tab" items={openedSessions.map(row => ({ id: row.id, title: row.title, label: <span className="tab-label"><span className={`tab-status ${row.status === "running" ? "running" : ""}`} /><span className="tab-title">{row.title}</span>{row.status === "running" ? <span className="sr-only">研究中</span> : null}</span> }))} /> : <span className="no-open-tabs">打开或新建一个会话</span>}</div>
    <div className="session-bar-actions"><VIconButton className="quiet" variant="ghost" label="新建会话" icon={<Plus size={16} />} onPress={() => newSession()} /><VIconButton className="quiet" variant="ghost" label="全部会话" icon={<History size={16} />} onPress={() => { setDirectoryOpen(true); setChecked([]); }} />{selected ? <VDropdownMenu aria-label="当前会话菜单" align="end" trigger={<VIconButton className="quiet" variant="ghost" label="当前会话操作" icon={<MoreHorizontal size={16} />} />} items={[{ id: "close", label: "关闭标签", icon: <X size={14} />, onSelect: () => closeSession(selected.id) }, { id: "rename", label: "重命名", onSelect: () => { setRenameTarget(selected); setRenameText(selected.title); } }, { id: "archive", label: "归档会话", icon: <Archive size={14} />, disabled: running, onSelect: () => act(selected, "archive") }, { id: "delete", label: "删除会话", danger: true, disabled: running, onSelect: () => act(selected, "delete") }]} /> : null}</div>
  </div>;
  const conversation = <div className="conversation-main chat-rail"><div className="chat-header"><MessageSquare size={15} /><strong title={selected?.title}>{selected?.title || "当前会话"}</strong><VIconButton className="quiet" variant="ghost" label="收起会话栏" icon={<PanelRightClose size={16} />} onPress={() => setRightClosed(true)} /></div>
    <div className="conversation-scroll" ref={conversationRef} aria-label="研究对话" data-preview-conversation key={selectedId} onScroll={e => selected && updateSession(selected.id, { scroll: e.currentTarget.scrollTop })}>
      {!selected || selected.status === "idle" ? <div className="empty-conversation"><span className="empty-icon"><Sparkles size={26} /></span><h1>开始一项A股研究</h1><p>输入股票代码、公司名称或研究问题。</p><div className="suggestions">{["分析贵州茅台财报", "比较消费板块估值", "复盘模拟持仓"].map(t => <VButton variant="secondary" key={t} onPress={() => ask(t)}>{t}</VButton>)}</div>{!selected ? <VButton variant="primary" icon={<Plus size={15} />} onPress={() => newSession()}>新建会话</VButton> : null}</div> : <div className="transcript">
        <div className="user-message">{selectedId === "layout-preview-0" ? "分析贵州茅台的盈利质量、估值和主要风险，并列出财报依据。" : `研究${selected.title}，核对数据来源和主要风险。`}</div>
        <article className="assistant-message"><div className="assistant-byline"><span className="assistant-avatar"><Sparkles size={14} /></span><strong>A股研究助手</strong><span>{running ? "研究中" : "已完成"}</span></div>
          <h2>{selectedId === "layout-preview-0" ? "先核对现金回款，再判断估值" : selected.title}</h2><p>利润需要与经营现金流相互印证。估值判断结合历史区间、同业表现和分红安排，现有资料还不足以支持确定的买卖结论。</p>
          <VSurface tone="inset" padding="normal" className="conclusion"><div><span>经营质量</span><strong>核对利润与现金回款</strong></div><div><span>估值判断</span><strong>对照历史区间与同业</strong></div><div><span>主要风险</span><strong>需求变化与盈利预期</strong></div></VSurface>
          <h3>需要进一步核对</h3><ul><li>收入、经营现金流和应收项目是否相互印证。</li><li>分红与资本开支变化，是否影响未来现金回报。</li><li>增长预期是否已经反映在当前估值中。</li></ul>
          <div className="message-evidence"><VButton variant="ghost" className="quiet" icon={<FileText size={14} />} onPress={() => setTool("sources")}>3 条资料引用</VButton><VButton variant="ghost" className="quiet" icon={<Check size={14} />} onPress={() => setTool("process")}>查看研究过程</VButton></div>
        </article>{selected.messages.map((message, i) => message.role === "user" ? <div key={i} className="user-message">{message.text}</div> : <article key={i} className="assistant-message"><div className="assistant-byline"><Sparkles size={14} /><strong>A股研究助手</strong></div><p>{message.text}</p></article>)}
      </div>}
    </div>
    <div className="composer-area"><VSurface padding="normal" className="composer" ariaLabel="当前会话输入"><VTextarea aria-label="研究问题" placeholder={selected ? "继续追问，或输入股票代码…" : "先新建或打开会话"} disabled={!selected} value={draft} onChange={e => selected && updateSession(selected.id, { draft: e.target.value })} rows={2} className="composer-input" onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} /><div className="composer-actions"><VDropdownMenu aria-label="添加研究上下文" align="start" trigger={<VIconButton variant="ghost" className="quiet" label="添加附件或引用" icon={<Plus size={17} />} isDisabled={!selected} />} items={[{ id: "file", label: "添加附件", icon: <FileText size={14} />, onSelect: () => setNotice("附件位置预览，未上传真实文件") }, { id: "session", label: "引用会话", icon: <MessageSquare size={14} />, onSelect: () => setNotice("正式接入时复用现有会话引用菜单") }, { id: "knowledge", label: "引用知识", icon: <BookOpen size={14} />, onSelect: () => setTool("sources") }]} /><span className="composer-hint">{running ? "切换会话不影响研究" : "Enter 发送 · Shift+Enter 换行"}</span>{running ? <VIconButton variant="secondary" label="停止示例研究" icon={<Square size={14} />} onPress={() => selected && updateSession(selected.id, { status: "completed" })} /> : <VIconButton variant="primary" label="发送研究问题" icon={<ArrowUp size={17} />} isDisabled={!selected || !draft.trim()} onPress={send} />}</div></VSurface></div>
    {notice ? <div role="status" className="preview-notice">{notice}</div> : null}
  </div>;
  const main = <div className="detail-main">{sessionBar}<div className="detail-toolbar"><strong>{tool ? titleFor(tool) : "研究详情"}</strong><span title={selected?.title}>{selected?.title || "新研究"}</span><VChip tone="neutral">示例</VChip>{tool ? <VIconButton className="quiet" variant="ghost" label="放大详情" icon={<Maximize2 size={15} />} onPress={() => setToolExpanded(true)} /> : null}{rightClosed ? <VIconButton className="quiet" variant="ghost" label="展开会话栏" icon={<PanelRightOpen size={16} />} onPress={() => setRightClosed(false)} /> : null}</div><div ref={detailRef} className="detail-scroll" aria-label="详细内容" data-preview-detail key={`${selectedId}:${tool || "report"}`} onScroll={e => selected && updateSession(selected.id, { detailScrolls: { ...selected.detailScrolls, [tool || "report"]: e.currentTarget.scrollTop } })}>{tool ? <FinanceToolPreview area={tool} company={selected?.title.split(" · ")[0]} onAsk={ask} /> : <FinanceResearchDetailPreview title={selected?.title || "新研究"} empty={!selected || selected.status === "idle"} onAsk={ask} onSources={() => setTool("sources")} />}</div></div>;
  return <VuiProvider><div ref={workspaceRef} className="finance-desktop-preview" data-vui-domain-recipe="finance-desktop-tabs-preview"><VSplitWorkspace className="desktop-workspace" sidebar={sidebar} main={main} aside={conversation} resize={{ layoutId: WORKBENCH_LAYOUT_IDS.finance, sidebar: { defaultWidth: 216, minWidth: 200, maxWidth: 280 }, aside: { defaultWidth: narrowDesktop ? 360 : 420, minWidth: narrowDesktop ? 300 : 380, maxWidth: narrowDesktop ? 380 : 620 }, collapse: { sidebar: { placement: "header", collapsed: leftClosed || narrowDesktop, onCollapsedChange: setLeftClosed, separatorLabel: "调整功能栏宽度", collapseLabel: "收起功能栏", expandLabel: "展开功能栏" }, aside: { placement: "header", collapsed: rightClosed, onCollapsedChange: setRightClosed, separatorLabel: "调整会话栏宽度", collapseLabel: "收起会话栏", expandLabel: "展开会话栏" } } }} /></div>
    <VDialog open={navigationOpen && narrowDesktop} onOpenChange={setNavigationOpen} title="功能与助手" size="sm" contentClassName="compact-navigation-content">{sidebar}</VDialog>
    <VDialog open={directoryOpen} onOpenChange={setDirectoryOpen} title="全部会话" description="当前 A股研究助手" size="xl" contentClassName="session-directory-content" footer={<div className="directory-footer"><span>{managing ? `已选择 ${checked.length} 条` : `${visibleSessions.length} 条会话`}</span>{managing ? <><VButton variant="secondary" isDisabled={!checked.length} icon={<Archive size={14} />} onPress={batchArchive}>{collection === "archived" ? "批量恢复" : "批量归档"}</VButton><VButton variant="danger" isDisabled={!checked.length} onPress={() => setDeleteIds(checked)}>批量删除</VButton></> : null}<VButton variant="secondary" onPress={() => setDirectoryOpen(false)}>完成</VButton></div>}>
      <div className="directory-controls"><VTabs aria-label="会话范围" value={collection} onValueChange={v => { setCollection(v); setChecked([]); }} items={[{ id: "recent", label: "最近会话" }, { id: "archived", label: "已归档" }]} /><div className="directory-search"><Search size={14} /><VInput aria-label="搜索全部会话" placeholder="搜索会话" value={search} onChange={e => setSearch(e.target.value)} /></div><VButton variant="ghost" aria-pressed={managing} onPress={() => { setManaging(!managing); setChecked([]); }}>{managing ? "退出管理" : "批量管理"}</VButton></div>
      <div className="directory-list">{visibleSessions.length ? visibleSessions.map(row => <div className="directory-row" key={row.id}>{managing ? <VCheckbox aria-label={`选择会话：${row.title}`} isSelected={checked.includes(row.id)} isDisabled={row.status === "running"} onChange={value => setChecked(ids => value ? [...ids, row.id] : ids.filter(id => id !== row.id))} /> : <MessageSquare size={15} />}<VButton contentLayout="plain" className="directory-session quiet" variant="ghost" title={row.title} onPress={() => { if (collection === "archived") { setNotice("先恢复归档会话，再打开研究"); return; } openSession(row.id); setDirectoryOpen(false); }}><span>{row.title}</span></VButton><span className={`directory-status ${row.status === "running" ? "is-running" : ""}`}>{row.status === "running" ? "研究中" : row.archiveState?.status === "archived" ? "已归档" : row.status === "idle" ? "待开始" : "已完成"}</span><FinanceSessionMenu record={row} zh onAction={act} /></div>) : <VStateSurface tone="empty" density="compact" title="没有匹配的会话" />}</div>
    </VDialog>
    <VDialog open={settingsOpen} onOpenChange={setSettingsOpen} title="当前 Agent 的模型" description="A股研究助手" footer={<><VButton variant="secondary" onPress={() => setSettingsOpen(false)}>取消</VButton><VButton variant="primary" onPress={() => { setModel(stagedModel); setSettingsOpen(false); setNotice("示例模型设置已保存，从下一轮生效"); }}>保存</VButton></>}><div className="model-settings"><div className="field-line"><span>对话模型</span><VSelect aria-label="当前Agent对话模型" selectedKey={stagedModel} onSelectionChange={v => setStagedModel(String(v))} options={[{ id: "flash", label: "Qwen3.8 Flash" }, { id: "example", label: "模型 B · 示例" }]} /></div><p>仅影响当前 Agent 的后续对话，运行中的研究继续使用原模型。</p><small>预览只保存示例配置，不调用模型。</small></div></VDialog>
    <VDialog open={!!renameTarget} onOpenChange={open => { if (!open) setRenameTarget(null); }} title="重命名会话" footer={<><VButton variant="secondary" onPress={() => setRenameTarget(null)}>取消</VButton><VButton variant="primary" isDisabled={!renameText.trim()} onPress={() => { if (renameTarget) updateSession(renameTarget.id, { title: renameText.trim() }); setRenameTarget(null); }}>保存</VButton></>}><VInput aria-label="会话名称" maxLength={100} value={renameText} onChange={e => setRenameText(e.target.value)} /></VDialog>
    <VConfirmDialog open={!!deleteIds.length} onOpenChange={open => { if (!open) setDeleteIds([]); }} title={deleteIds.length === 1 ? "删除这个示例会话？" : `删除 ${deleteIds.length} 个示例会话？`} description="仅删除当前预览的数据，真实会话不受影响。" confirmLabel="删除" cancelLabel="取消" tone="danger" onCancel={() => setDeleteIds([])} onConfirm={() => { const remaining = opened.filter(id => !deleteIds.includes(id)); setSessions(rows => rows.filter(row => !deleteIds.includes(row.id))); setOpened(remaining); if (deleteIds.includes(selectedId)) setSelectedId(remaining[0] || ""); setChecked([]); setDeleteIds([]); setNotice("示例会话已删除"); }} />
    <VDialog open={!!tool && toolExpanded} onOpenChange={setToolExpanded} title={tool ? titleFor(tool) : "工具"} description={selected?.title} size="xl" contentClassName="expanded-tool-content">{tool ? <FinanceToolPreview area={tool} company={selected?.title.split(" · ")[0]} onAsk={text => { ask(text); setToolExpanded(false); }} /> : null}</VDialog>
  </VuiProvider>;
}
