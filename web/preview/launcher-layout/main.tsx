import { StrictMode, useEffect, useRef, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { Activity, ArrowLeft, ArrowRight, Box, Check, ChevronRight, Circle, Copy, Ellipsis, ExternalLink, Folder, GitBranch, Monitor, Play, Search, Settings2, ShieldCheck, Square, Wrench } from "lucide-react";
import { VButton, VChip, VConfirmDialog, VDenseOpsPage, VDropdownMenu, VEmptyState, VInput, VSplitWorkspace, VStringSelect, VTabs, VuiProvider } from "../../src/components/vui";
import "./preview.css";

type State = "running" | "stopped" | "starting" | "failed";
type Branch = { id: string; name: string; state: State; dirty: boolean; head: string; window: boolean; path: string; error?: string };
const fixtureRoot = "C:\\Users\\Example\\Projects\\Vibelution";
const initialBranches: Branch[] = [
  { id: "main", name: "main", state: "running", dirty: false, head: "56f4e3f9c", window: true, path: fixtureRoot },
  { id: "preview", name: "codex/workbench-preview-parity", state: "stopped", dirty: true, head: "5762cc27b", window: false, path: `${fixtureRoot}\\.worktrees\\workbench-preview-parity` },
  { id: "chat", name: "codex/chat-header-actions", state: "running", dirty: true, head: "642d67a95", window: false, path: `${fixtureRoot}\\.worktrees\\chat-header-actions` },
  { id: "recovery", name: "codex/workbench-identity-recovery-and-launcher-startup-verification", state: "failed", dirty: false, head: "5762cc27b", window: false, path: `${fixtureRoot}\\.worktrees\\workbench-identity-recovery-and-launcher-startup-verification`, error: "后端启动超时，尚未进入就绪状态。已有文件和未提交改动均保留。" },
];
const stateLabels: Record<State, string> = { running: "运行中", stopped: "已停止", starting: "启动中", failed: "启动失败" };
function Status({ state }: { state: State }) {
  return <VChip className="status-chip" tone={state === "running" ? "success" : state === "failed" ? "danger" : state === "starting" ? "info" : "neutral"}><span className={`status-dot ${state}`} aria-hidden="true" />{stateLabels[state]}</VChip>;
}
function InfoRow({ label, children }: { label: string; children: ReactNode }) {
  return <div className="info-row"><dt>{label}</dt><dd>{children}</dd></div>;
}
function LauncherPreview() {
  const [branches, setBranches] = useState(initialBranches);
  const [selected, setSelected] = useState(() => new URLSearchParams(location.search).get("view") === "detail" ? "preview" : "");
  const [tab, setTab] = useState("overview");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmStop, setConfirmStop] = useState<string | null>(null);
  const [dark, setDark] = useState(false);
  const [fullPath, setFullPath] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const mainScroll = useRef<HTMLDivElement>(null);
  useEffect(() => () => { timers.current.forEach(clearTimeout); }, []);
  useEffect(() => { mainScroll.current?.scrollTo({ top: 0 }); }, [selected]);
  useEffect(() => { document.documentElement.dataset.theme = dark ? "dark" : "light"; }, [dark]);
  const branch = branches.find((item) => item.id === selected);
  const runningCount = branches.filter((item) => item.state === "running").length;
  const visible = branches.filter((item) => (filter === "all" || item.state === filter) && item.name.toLowerCase().includes(query.toLowerCase()));
  function openDetail(id: string) { setSelected(id); setTab("overview"); setFullPath(false); setNotice(""); }
  function changeState(id: string, state: State) { setBranches((items) => items.map((item) => item.id === id ? { ...item, state, window: state === "running", error: state === "failed" ? "后端启动超时，尚未进入就绪状态。已有文件和未提交改动均保留。" : undefined } : item)); }
  function primaryAction(item: Branch) {
    if (item.state === "running") { setBranches((items) => items.map((entry) => entry.id === item.id ? { ...entry, window: true } : entry)); setNotice(`已模拟${item.window ? "聚焦" : "打开"}窗口，没有操作真实工作区。`); return; }
    changeState(item.id, "starting"); setNotice("正在模拟启动，未提交真实生命周期请求。");
    timers.current.push(setTimeout(() => { changeState(item.id, "running"); setNotice("模拟启动完成，工作区已就绪。"); }, 1600));
  }
  function actions(item: Branch, compact = false) {
    const label = item.state === "running" ? item.window ? "进入工作台" : "打开窗口" : item.state === "failed" ? "重新启动" : item.state === "starting" ? "正在启动" : "启动工作台";
    return <div className={`lifecycle-actions ${compact ? "compact" : ""}`}>
      <VButton variant="primary" className="primary-action" icon={item.state === "running" ? <ExternalLink size={15} /> : <Play size={15} />} isPending={item.state === "starting"} onPress={() => primaryAction(item)}>{label}</VButton>
      {item.state === "running" ? compact ? <VButton variant="secondary" isIconOnly aria-label={`${item.name} 停止工作台`} title="停止工作台" icon={<Square size={13} />} onPress={() => setConfirmStop(item.id)} /> : <VButton variant="secondary" icon={<Square size={13} />} onPress={() => setConfirmStop(item.id)}>停止</VButton> : null}
      <VDropdownMenu aria-label={`${item.name} 更多操作`} align="end" trigger={<VButton variant="ghost" isIconOnly aria-label={`${item.name} 更多操作`} icon={<Ellipsis size={18} />} />} items={[
        { id: "detail", label: "查看详情", onSelect: () => openDetail(item.id) },
        { id: "diagnostics", label: "查看启动信息", onSelect: () => { openDetail(item.id); setTab("startup"); } },
      ]} />
    </div>;
  }
  const previewControl = <footer className="preview-controls"><span><span className="preview-mark">预览</span>使用模拟数据，不影响真实工作区</span><div>
    {branch ? <VStringSelect ariaLabel="模拟运行状态" value={branch.state} onValueChange={(value) => { timers.current.forEach(clearTimeout); changeState(branch.id, value as State); setNotice(""); }} options={Object.entries(stateLabels).map(([value, label]) => ({ value, label }))} className="scene-select" /> : null}
    <VButton variant="ghost" onPress={() => setDark(!dark)}>{dark ? "浅色外观" : "深色外观"}</VButton>
  </div></footer>;
  return <VuiProvider><div className="launcher-preview" data-theme={dark ? "dark" : "light"}>
    <header className="app-header"><div className="brand"><span className="brand-symbol">V</span><strong>Vibelution</strong><span className="brand-product">Launcher</span></div><div className="header-right"><ShieldCheck size={15} /><span>本地运行</span><span className="header-separator" /><span className="version-state"><Check size={14} />已是最新版本</span></div></header>
    <VSplitWorkspace className="launcher-workspace" columnsClassName="launcher-columns" sidebar={<nav className="navigation" aria-label="Launcher 导航">
      <div className="project-switcher"><span className="project-avatar"><GitBranch size={18} /></span><div><span>本地项目</span><strong>Vibelution</strong></div></div>
      <div className="nav-group"><span className="nav-group-label">工作区</span>
        <VButton className="nav-item selected" variant="ghost" icon={<Box size={17} />} aria-current="page" onPress={() => { setSelected(""); setNotice(""); }}>分支<span className="nav-count">{branches.length}</span></VButton>
        <VButton className="nav-item" variant="ghost" icon={<Activity size={17} />} onPress={() => setNotice("诊断页沿用现有入口，本次预览只覆盖分支列表与详情。")}>诊断</VButton>
        <VButton className="nav-item" variant="ghost" icon={<Wrench size={17} />} onPress={() => setNotice("维护页不在本次预览范围内。")}>维护</VButton>
      </div>
      <div className="nav-bottom"><p><span className="status-dot running" />{runningCount} 个工作区运行中</p><VButton className="nav-item" variant="ghost" icon={<Settings2 size={17} />} onPress={() => setNotice("设置页沿用现有入口，本次不会修改设置。")}>设置</VButton></div>
    </nav>} main={<div className="main-scroll" ref={mainScroll}><div className="page-container">
      <div className="breadcrumb"><span>Vibelution</span><ChevronRight size={13} />{branch ? <><VButton variant="ghost" onPress={() => { setSelected(""); setNotice(""); }}>分支</VButton><ChevronRight size={13} /><span className="breadcrumb-current">详情</span></> : <span className="breadcrumb-current">分支</span>}</div>
      {branch ? <VDenseOpsPage className="detail-page" hideHeader fill={false} bodyClassName="preview-page-body" ariaLabel="分支详情">
        <VButton variant="ghost" className="back-link" icon={<ArrowLeft size={14} />} onPress={() => { setSelected(""); setNotice(""); }}>返回分支列表</VButton>
        <div className="detail-heading"><div className="detail-title"><span className="branch-icon"><GitBranch size={21} /></span><div><h1>{branch.name}</h1><div className="branch-meta"><Status state={branch.state} /><span>{branch.id === "main" ? "主工作区" : "独立工作区"}</span></div></div></div>{actions(branch)}</div>
        <VTabs className="page-tabs" listClassName="page-tabs-list" triggerClassName="page-tab" aria-label="分支详情" value={tab} onValueChange={setTab} items={[{ id: "overview", label: "概览" }, { id: "startup", label: "启动信息" }]} />
        {branch.state === "failed" ? <div className="failure-callout" role="alert"><Activity size={18} /><div><strong>启动未完成</strong><p>{branch.error}</p></div><VButton variant="ghost" trailingIcon={<ArrowRight size={14} />} onPress={() => setTab("startup")}>查看原因</VButton></div> : null}
        {tab === "overview" ? <div className="detail-grid">
          <section className="information-section"><h2><Monitor size={16} />运行情况</h2><p className="section-hint">工作台、服务与构建状态</p><dl>
            <InfoRow label="工作台"><span className="inline-state"><span className={`status-dot ${branch.state}`} />{stateLabels[branch.state]}</span></InfoRow>
            <InfoRow label="窗口">{branch.window ? "已打开" : "未打开"}</InfoRow>
            <InfoRow label="后端">{branch.state === "running" ? "已就绪" : branch.state === "starting" ? "正在启动" : branch.state === "failed" ? "未就绪" : "未运行"}</InfoRow>
            <InfoRow label="前端"><span className="inline-state"><Check size={14} />已构建</span></InfoRow>
          </dl><div className="section-footnote">{branch.state === "stopped" ? "工作区文件已保留，可随时重新启动。" : branch.state === "running" ? "服务已就绪，可进入工作台继续工作。" : branch.state === "starting" ? "等待服务就绪后即可进入工作台。" : "可查看启动信息并重新尝试。"}</div></section>
          <section className="information-section"><h2><Folder size={16} />工作区信息</h2><p className="section-hint">本地目录与当前代码版本</p><dl>
            <InfoRow label="类型">{branch.id === "main" ? "主工作区" : "任务分支"}</InfoRow>
            <InfoRow label="Git"><span className={branch.dirty ? "git-warning" : ""}>{branch.dirty ? "有未提交改动" : "工作区干净"}</span></InfoRow>
            <InfoRow label="提交"><code>{branch.head}</code></InfoRow>
          </dl><div className="path-block"><div><span>目录</span><VButton variant="ghost" isIconOnly aria-label="复制工作区路径" title="复制路径" icon={<Copy size={14} />} onPress={() => { void navigator.clipboard.writeText(branch.path).then(() => setNotice("模拟工作区路径已复制。"), () => { setFullPath(true); setNotice("浏览器未允许复制，已展开完整路径。可选中文本复制。"); }); }} /></div><code title={branch.path} className={fullPath ? "path-full" : "path-short"}>{fullPath ? branch.path : branch.id === "main" ? "Projects / Vibelution" : `.worktrees / ${branch.path.split("\\").at(-1)}`}</code><VButton variant="ghost" className="path-toggle" onPress={() => setFullPath(!fullPath)}>{fullPath ? "收起完整路径" : "查看完整路径"}</VButton></div></section>
        </div> : <section className="startup-section"><div className="startup-heading"><h2>启动信息</h2><Status state={branch.state} /></div><p className="section-hint">用于理解当前阶段，定位启动异常。</p><dl>
          <InfoRow label="当前阶段">{branch.state === "running" ? "服务就绪" : branch.state === "starting" ? "等待后端就绪" : branch.state === "failed" ? "后端启动超时" : "已停止，等待启动"}</InfoRow>
          <InfoRow label="错误信息">{branch.error || "当前没有启动错误"}</InfoRow>
          {branch.error ? <InfoRow label="错误代码"><code>BACKEND_START_TIMEOUT</code></InfoRow> : null}
        </dl><VButton variant="secondary" icon={<Activity size={15} />} onPress={() => setNotice("诊断入口为模拟展示，未访问真实日志。")}>查看运行诊断</VButton></section>}
      </VDenseOpsPage> : <VDenseOpsPage className="branches-page" hideHeader fill={false} bodyClassName="preview-page-body" ariaLabel="分支列表">
        <div className="list-heading"><div><h1>分支</h1><p>管理本地工作区，打开工作台继续工作。</p></div><span className="list-total">{branches.length} 个工作区</span></div>
        <div className="list-controls"><VTabs className="filter-tabs" aria-label="筛选分支" value={filter} onValueChange={setFilter} listClassName="filter-tabs-list" triggerClassName="filter-tab" items={[{ id: "all", label: `全部 ${branches.length}` }, { id: "running", label: `运行中 ${runningCount}` }, { id: "stopped", label: `已停止 ${branches.filter((item) => item.state === "stopped").length}` }, { id: "failed", label: `需关注 ${branches.filter((item) => item.state === "failed").length}` }]} /><div className="search-field"><Search size={15} /><VInput aria-label="搜索分支" placeholder="搜索分支…" value={query} onChange={(event) => setQuery(event.target.value)} /></div></div>
        <div className="branch-list" role="list" aria-label="工作区分支"><div className="list-column-head" aria-hidden="true"><span>工作区</span><span>状态</span><span>窗口</span><span>操作</span></div>
          {visible.length ? visible.map((item) => <div key={item.id} role="listitem" className="branch-row"><div className="branch-cell"><span className={`row-branch-icon ${item.id === "main" ? "main-branch" : ""}`}><GitBranch size={18} /></span><div><VButton variant="ghost" className="branch-name-button" title={item.name} onPress={() => openDetail(item.id)}>{item.name}</VButton><div className="row-meta"><span>{item.id === "main" ? "主工作区" : "任务分支"}</span><span>·</span><span className={item.dirty ? "git-warning" : ""}>{item.dirty ? "有未提交改动" : "Git 干净"}</span></div></div></div><Status state={item.state} /><span className="window-state">{item.window ? "已打开" : "未打开"}</span>{actions(item, true)}</div>) : <VEmptyState className="empty-state" title="没有匹配的分支" actions={<VButton variant="secondary" onPress={() => { setQuery(""); setFilter("all"); }}>清除筛选</VButton>}>试试其他关键词，或查看全部工作区。</VEmptyState>}
        </div><p className="list-caption"><Circle size={12} />每个分支使用独立工作区，操作只影响对应实例。</p>
      </VDenseOpsPage>}
      {notice ? <div className="operation-notice" role="status"><Check size={15} /><span>{notice}</span><VButton variant="ghost" className="notice-dismiss" onPress={() => setNotice("")}>关闭</VButton></div> : null}
    </div></div>} />
    {previewControl}
    <VConfirmDialog open={confirmStop !== null} onOpenChange={(open) => { if (!open) setConfirmStop(null); }} title="停止这个工作台？" description="这是模拟操作。正式停止会关闭对应窗口与后端，保留工作区文件和未提交改动。" confirmLabel="停止工作台" cancelLabel="取消" tone="danger" onConfirm={() => { if (confirmStop) changeState(confirmStop, "stopped"); setConfirmStop(null); setNotice("已模拟停止工作台，未操作任何真实进程。"); }} />
  </div></VuiProvider>;
}
const previewRoot = createRoot(document.getElementById("root")!);
previewRoot.render(<StrictMode><LauncherPreview /></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => previewRoot.unmount());
