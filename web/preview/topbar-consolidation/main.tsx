/// <reference types="vite/client" />
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowLeft, ArrowUp, Bell, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, FileCode2, GitBranch, LoaderCircle, Maximize2, MessageSquare, Moon, Plus, RefreshCw, Search, Settings, SlidersHorizontal, Sun, X } from "lucide-react";
import { VButton, VConfirmDialog, VDialog, VNativeSelect, VNativeTextarea, VPopover, VSplitWorkspace, VSurface, VTabs, VuiProvider } from "../../src/components/vui";
import { isProjectPanel, toolLabel, useWorkspaceTools, WorkspaceRailHeader, type ProjectPanel, type RailPanel, type ToolKind } from "./WorkspaceTools";
import { WORKBENCH_LAYOUT_IDS } from "../../src/components/layout/workbenchLayoutIds";
import "../../src/design/base.css";
import "../../src/design/tokens.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "./preview.css";

type Panel = RailPanel;
type Scene = "normal" | "empty" | "loading" | "error";
const projectLabels: Record<ProjectPanel, string> = { tasks: "任务", changes: "变更", notices: "通知" };
const panelLabel = (kind: Panel) => isProjectPanel(kind) ? projectLabels[kind] : toolLabel(kind);
const taskRows = [
  { id: "review", title: "整理工作台导航", owner: "开发助手", kind: "会话", state: "进行中", detail: "正在对照入口与页面布局，整理需要合并的辅助功能。", parent: "架构与导航整理" },
  { id: "source", title: "检索界面参考", owner: "研究助手", kind: "后台任务", state: "进行中", detail: "正在归纳 OpenCode、VS Code 与 Zed 的工具面板模式。", parent: "架构与导航整理" },
  { id: "done", title: "核对会话草稿保留", owner: "开发助手", kind: "会话", state: "已完成", detail: "切换辅助区时，当前会话与输入草稿保持不变。", parent: "会话可靠性" },
];
const files = [
  { name: "AppShell.tsx", path: "web/src/app", adds: 18, deletes: 9 },
  { name: "ChatRightRail.tsx", path: "web/src/routes/chat", adds: 24, deletes: 6 },
  { name: "AppShell.styles.ts", path: "web/src/app", adds: 8, deletes: 12 },
];
const sessions = ["架构与导航整理", "会话可靠性", "知识库整理"];

function App() {
  const [panel, setPanel] = useState<Panel | null>(() => window.matchMedia("(max-width: 1050px)").matches ? null : "tasks");
  const [scene, setScene] = useState<Scene>("normal");
  const [mobile, setMobile] = useState(() => window.matchMedia("(max-width: 1050px)").matches);
  const [expanded, setExpanded] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [allSettings, setAllSettings] = useState(false);
  const [dark, setDark] = useState(false);
  const [session, setSession] = useState(sessions[0]);
  const tools = useWorkspaceTools(session);
  const [projectTabs, setProjectTabs] = useState<ProjectPanel[]>(["tasks"]);
  const [drafts, setDrafts] = useState<Record<string, string>>({ [sessions[0]]: "继续看看通知入口的交互" });
  const [task, setTask] = useState<string | null>(null);
  const [taskFilter, setTaskFilter] = useState("running");
  const [scope, setScope] = useState("project");
  const [file, setFile] = useState<string | null>(null);
  const [read, setRead] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [broadcast, setBroadcast] = useState(false);
  const [broadcastDraft, setBroadcastDraft] = useState("");
  const [stopTarget, setStopTarget] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [sent, setSent] = useState<Record<string, string[]>>({});
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1050px)");
    const change = () => setMobile(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useEffect(() => { document.documentElement.dataset.theme = dark ? "dark" : "light"; }, [dark]);
  useEffect(() => { if (panel === "notices" && scene === "normal") setRead(true); }, [panel, scene]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      const inDialog = event.target instanceof Element && Boolean(event.target.closest('[role="dialog"],[role="alertdialog"],[role="menu"]'));
      if (event.key === "Escape" && !event.defaultPrevented && !inDialog && !settingsOpen && !stopTarget && !allSettings && !broadcast) { setPanel(null); setExpanded(false); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [settingsOpen, stopTarget, allSettings, broadcast]);
  function retainProject(next: ProjectPanel) { setProjectTabs((current) => current.includes(next) ? current : [...current, next]); }
  function open(next: ProjectPanel) { retainProject(next); setSettingsOpen(false); setPanel((current) => current === next ? null : next); }
  function selectProject(next: ProjectPanel) { retainProject(next); setSettingsOpen(false); setPanel(next); }
  function selectTool(kind: ToolKind, id?: string) { tools.open(kind, id); setSettingsOpen(false); setPanel(kind); }
  function closeProject(next: ProjectPanel) { setProjectTabs((current) => current.filter((kind) => kind !== next)); if (panel === next) setPanel(tools.active?.kind as ToolKind ?? projectTabs.find((kind) => kind !== next) ?? null); }
  function closeTool(id: string) { const wasActive = tools.model.activeId === id; const next = tools.close(id); if (wasActive && !isProjectPanel(panel)) setPanel(next ?? projectTabs[0] ?? null); }
  function freshSide() { tools.freshSide(); setPanel("side"); }
  useEffect(() => { if (panel && !isProjectPanel(panel)) setPanel(tools.active?.kind as ToolKind ?? "side"); }, [session]);
  function close() { setPanel(null); setExpanded(false); }
  const selectedTask = taskRows.find((item) => item.id === task);
  const selectedFile = files.find((item) => item.name === file);
  const scopedTasks = taskRows.filter((item) => scope !== "session" || item.parent === session);
  const runningCount = scopedTasks.filter((item) => item.state === "进行中").length;
  const visibleTasks = scopedTasks.filter((item) => taskFilter !== "running" || item.state === "进行中");

  function stateContent() {
    if (scene === "normal") return null;
    const config = scene === "loading" ? { icon: LoaderCircle, title: "正在读取…", copy: "当前对话可以继续使用。" }
      : scene === "error" ? { icon: CircleAlert, title: "暂时无法读取", copy: "已有对话和草稿已保留，可以稍后重试。" }
      : { icon: CheckCircle2, title: panel === "tasks" ? "没有正在运行的任务" : panel === "changes" ? "工作区干净" : "没有新通知", copy: panel === "tasks" ? "开始新的工作后，任务会出现在这里。" : panel === "changes" ? "修改文件后，可在这里查看差异。" : "需要你处理的消息会出现在这里。" };
    const Icon = config.icon;
    return <div className="panel-state" role="status"><Icon size={23} className={scene === "loading" ? "spin" : ""} /><h3>{config.title}</h3><p>{config.copy}</p>{scene === "error" ? <VButton variant="secondary" onPress={() => setScene("normal")} icon={<RefreshCw size={14} />}>重试</VButton> : null}</div>;
  }

  function content() {
    if (panel && !isProjectPanel(panel)) return tools.content;
    const state = stateContent();
    if (state) return state;
    if (panel === "tasks") return <>
      <div className="scope-row"><VNativeSelect aria-label="任务范围" value={scope} onChange={(event) => setScope(event.target.value)}><option value="project">整个项目</option><option value="session">当前会话</option></VNativeSelect><span className="muted"><span className="connection-dot" />连接正常</span></div>
      <VTabs aria-label="任务筛选" value={taskFilter} onValueChange={(value) => { setTaskFilter(value); setTask(null); }} items={[{ id: "running", label: `运行中 · ${runningCount}` }, { id: "all", label: `全部 · ${scopedTasks.length}` }]} />
      <div className="section-caption">{scope === "project" ? "项目中的工作" : "这段会话的工作"}</div>
      <div className="rows">{visibleTasks.map((item) => <VButton key={item.id} variant="ghost" contentLayout="plain" className={`list-row ${task === item.id ? "selected" : ""}`} onPress={() => setTask(item.id)}><span className="row-icon">{item.state === "进行中" ? <LoaderCircle size={16} className="spin" /> : <CheckCircle2 size={16} />}</span><span className="row-main"><strong>{item.title}</strong><span>{item.owner} · {item.kind}</span></span><span className="row-state">{item.id === "source" && stopping ? "停止中" : item.state}</span></VButton>)}</div>
      {!visibleTasks.length ? <p className="inline-empty">这段会话没有正在运行的任务。</p> : null}
      {selectedTask ? <section className="detail-block" aria-label="任务详情"><div className="detail-heading"><h3>{selectedTask.title}</h3><VButton variant="ghost" className="icon-control" aria-label="关闭任务详情" onPress={() => setTask(null)}><X size={15} /></VButton></div><p>{selectedTask.detail}</p><div className="detail-meta">来自 {selectedTask.parent}</div><div className="detail-actions"><VButton variant="secondary" onPress={() => { setSession(selectedTask.parent); setFeedback("已定位到关联会话"); }}>定位会话</VButton>{selectedTask.kind === "后台任务" ? <VButton variant="ghost" isDisabled={stopping} onPress={() => setStopTarget(true)}>{stopping ? "停止中…" : "停止任务"}</VButton> : null}</div></section> : <div className="panel-footnote">选择任务查看详情，当前对话会留在这里。</div>}
    </>;
    if (panel === "changes") return <>
      <div className="scope-row"><span className="branch-label"><GitBranch size={15} />当前项目 · main</span><span className="muted">3 个文件</span></div>
      <div className="rows">{files.map((item) => <VButton key={item.name} variant="ghost" contentLayout="plain" className={`list-row file-row ${file === item.name ? "selected" : ""}`} onPress={() => setFile(item.name)}><FileCode2 size={17} /><span className="row-main"><strong>{item.name}</strong><span>{item.path}</span></span><span className="diff-count"><i>+{item.adds}</i><em>−{item.deletes}</em></span></VButton>)}</div>
      {selectedFile ? <section className="detail-block diff-detail" aria-label="文件差异"><div className="detail-heading"><h3>{selectedFile.name}</h3><VButton variant="ghost" className="icon-control" aria-label="关闭文件差异" onPress={() => setFile(null)}><X size={15} /></VButton></div><div className="diff-meta">web/src · 工作区与 HEAD 比较</div><pre className="code-diff"><span>  3150  {'<ShellUtilities>'}</span><span className="removed">− 3151    navigate("/git");</span><span className="added">+ 3151    openPanel("changes");</span><span className="added">+ 3152    keepCurrentConversation();</span><span>  3153  {'</ShellUtilities>'}</span></pre><p className="muted">此处为示例差异，未读取或修改真实文件。</p></section> : <div className="panel-state quiet-state"><FileCode2 size={24} /><h3>选择文件查看差异</h3><p>变更在旁边展开，对话继续留在原处。</p></div>}
      <div className="secondary-links"><VButton contentLayout="plain" variant="ghost" onPress={() => { setExpanded(true); setFeedback("已展开变更工作区"); }}>提交记录<ChevronRight size={14} /></VButton><VButton contentLayout="plain" variant="ghost" onPress={() => { setExpanded(true); setFeedback("已展开分支工作区"); }}>分支与同步<ChevronRight size={14} /></VButton></div>
    </>;
    return <>
      <div className="scope-row"><span>项目通知</span><span className="muted">最近</span></div>
      <div className="rows notice-rows">{[{ id: "result", title: "界面参考已整理", copy: "研究助手已完成参考整理，可以查看结果。", time: "刚刚", action: "查看结果" }, { id: "decision", title: "有一项方案等待确认", copy: "开发助手需要你确认任务入口的收拢方向。", time: "5 分钟前", action: "定位会话" }].map((item) => <section key={item.id} className={`notice-row ${notice === item.id ? "notice-selected" : ""}`}><div className="notice-meta"><MessageSquare size={14} /><span>{item.id === "result" ? "研究助手" : "开发助手"}</span><time>{item.time}</time></div><h3>{item.title}</h3><p>{item.copy}</p><VButton variant="ghost" contentLayout="plain" className="inline-action" onPress={() => { setNotice(item.id); setFeedback(item.id === "result" ? "已打开示例结果" : "已定位到关联会话"); }}>{item.action}<ChevronRight size={14} /></VButton>{notice === item.id ? <div className="notice-result">{item.id === "result" ? "参考结论：把辅助工具放在当前工作旁边，复杂操作按需展开。" : "关联会话：架构与导航整理。对话和输入草稿已保留。"}</div> : null}</section>)}</div>
      <div className="panel-footnote">通知只显示消息与结果。</div><VButton variant="ghost" contentLayout="plain" className="broadcast-link" onPress={() => setBroadcast(true)}>发送广播<ChevronRight size={14} /></VButton>
    </>;
  }
  const panelBody = <VSurface as="section" className="utility-panel" padding="none" aria-label="工作台辅助区">
    <WorkspaceRailHeader panel={panel} projectTabs={projectTabs} projectLabels={projectLabels} tools={tools} onProject={selectProject} onTool={selectTool} onCloseProject={closeProject} onCloseTool={closeTool} onFreshSide={freshSide} onCollapse={close} onExpand={() => setExpanded(true)} />
    <div className={`panel-scroll ${panel && !isProjectPanel(panel) ? "panel-tool-body" : ""}`}>{content()}</div>
  </VSurface>;
  const conversation = <VSurface as="main" className="conversation" padding="none" aria-label="当前对话"><header className="conversation-heading"><div><span className="eyebrow">开发助手</span><h1>{session}</h1></div><span className="muted">当前项目</span></header><div className="conversation-scroll" data-testid="conversation-scroll"><div className="thread"><div className="user-message">右上角的几个入口如何收拢？希望查看任务和通知时，可以继续留在当前对话。</div><article className="assistant-message"><div className="assistant-label"><span className="assistant-avatar">V</span><strong>开发助手</strong></div><h2>右栏保留所有工具，主对话留在这里。</h2><p>辅助对话、浏览器、CLI、文件与子 Agent 都保留在右栏。任务、变更、通知也进入同一条标签栏，按需打开。</p><p>需要审查长差异或查看完整历史时，再主动展开工作区。关闭后，会回到这段对话。</p><div className="answer-files"><FileCode2 size={15} /><span>已定位 3 个相关文件</span><span className="muted">AppShell · ChatRightRail</span></div><p className="muted">试试右栏的 ＋：打开辅助对话、浏览器或 CLI，再切回任务。草稿和工具状态都会保留。</p></article>{(sent[session] ?? []).map((text, index) => <div className="user-message" key={index}>{text}</div>)}</div></div><form className="composer-wrap" onSubmit={(event) => { event.preventDefault(); const value = drafts[session]?.trim(); if (value) { setSent((current) => ({ ...current, [session]: [...(current[session] ?? []), value] })); setDrafts((current) => ({ ...current, [session]: "" })); } }}><div className="composer"><VNativeTextarea rows={2} aria-label="继续对话" placeholder="继续对话…" value={drafts[session] ?? ""} onChange={(event) => setDrafts((current) => ({ ...current, [session]: event.target.value }))} /><div className="composer-bottom"><VButton variant="ghost" className="icon-control" aria-label="添加附件" onPress={() => setFeedback("附件上传未接入，预览不会上传文件")}><Plus size={18} /></VButton><span className="muted">开发助手</span><VButton type="submit" variant="secondary" className="send-button" aria-label="发送示例消息" isDisabled={!drafts[session]?.trim()}><ArrowUp size={17} /></VButton></div></div><div className="composer-caption">辅助区展开时，仍可继续这段对话。</div></form></VSurface>;
  const sidebar = <VSurface as="aside" className="session-list" padding="none" tone="rail" aria-label="会话列表"><div className="session-list-heading"><strong>会话</strong><Search size={15} /></div><div className="section-caption">最近</div>{sessions.map((item) => <VButton variant="ghost" contentLayout="plain" className={`session-row ${item === session ? "selected" : ""}`} key={item} onPress={() => setSession(item)}><MessageSquare size={15} /><span>{item}</span></VButton>)}<div className="session-bottom">Vibelution<span>当前项目</span></div></VSurface>;

  return <VuiProvider><div className="preview-app"><header className="topbar"><div className="topbar-left"><VButton variant="ghost" className="icon-control back-control" aria-label="返回" onPress={() => setFeedback("当前仍在示例对话中")}><ArrowLeft size={16} /></VButton><nav aria-label="主导航"><span className="nav-active">对话</span><span>智能体<ChevronDown size={12} /></span><span>团队</span><span>进化</span><span>记忆库</span></nav><span className="mobile-brand">Vibelution</span></div><div className="topbar-tools"><VButton variant="ghost" contentLayout="plain" className={`tasks-trigger ${panel === "tasks" ? "tool-active" : ""}`} title="任务与连接状态" aria-label="打开任务" aria-pressed={panel === "tasks"} onPress={() => open("tasks")}><span className={`connection-dot ${scene === "error" ? "warning-dot" : ""}`} /><span>{scene === "error" ? "连接异常" : "任务"}</span><strong>{scene === "loading" ? "…" : scene === "empty" ? "0" : "2"}</strong><ChevronDown size={12} /></VButton><VButton variant="ghost" className={`icon-control tool-trigger ${panel === "changes" ? "tool-active" : ""}`} aria-label="打开变更" aria-pressed={panel === "changes"} title="变更 · 3 个文件" onPress={() => open("changes")}><GitBranch size={18} /><span className="tool-badge">3</span></VButton><VButton variant="ghost" className={`icon-control tool-trigger ${panel === "notices" ? "tool-active" : ""}`} aria-label="打开通知" aria-pressed={panel === "notices"} title="通知" onPress={() => open("notices")}><Bell size={18} />{!read ? <span className="unread-dot" /> : null}</VButton><VPopover open={settingsOpen} onOpenChange={setSettingsOpen} align="end" sideOffset={8} aria-label="设置菜单" contentClassName="settings-popover" trigger={<VButton variant="ghost" className={`icon-control ${settingsOpen ? "tool-active" : ""}`} aria-label="设置" title="设置"><Settings size={18} /></VButton>}><div className="settings-heading">设置</div><VButton variant="ghost" contentLayout="plain" className="settings-row" icon={<SlidersHorizontal size={16} />} onPress={() => { setSettingsOpen(false); setAllSettings(true); }}>全部设置<ChevronRight size={14} /></VButton><VButton variant="ghost" contentLayout="plain" className="settings-row" icon={dark ? <Moon size={16} /> : <Sun size={16} />} onPress={() => setDark(!dark)}>外观<span className="muted">{dark ? "深色" : "浅色"}</span><ChevronRight size={14} /></VButton><VButton variant="ghost" contentLayout="plain" className="settings-row" onPress={() => setFeedback("示例用量：本周 12 次会话")}>用量统计<ChevronRight size={14} /></VButton><div className="settings-divider" /><VButton variant="ghost" contentLayout="plain" className="settings-row" onPress={() => setFeedback("高级与诊断在正式设置中提供")}>高级与诊断<ChevronRight size={14} /></VButton></VPopover></div></header>
    <div className={`workbench ${panel && !mobile ? "with-panel" : ""}`}><VSplitWorkspace className="preview-split" main={conversation} sidebar={!mobile ? sidebar : undefined} aside={panel && !mobile && !expanded ? panelBody : undefined} resize={!mobile ? { layoutId: WORKBENCH_LAYOUT_IDS.chat, sidebar: { defaultWidth: 212, minWidth: 180, maxWidth: 280 }, aside: { defaultWidth: 420, minWidth: 340, maxWidth: 600 } } : false} /></div>
    <footer className="preview-footer"><span>交互预览 · 模拟数据</span><span className="preview-feedback" role="status">{feedback}</span><label>示例状态<VNativeSelect aria-label="示例状态" value={scene} onChange={(event) => { setScene(event.target.value as Scene); setFeedback(""); }}><option value="normal">正常</option><option value="empty">空状态</option><option value="loading">加载中</option><option value="error">异常</option></VNativeSelect></label></footer>
    <VDialog open={Boolean(panel) && (mobile || expanded)} onOpenChange={(value) => { if (!value) close(); }} title={panel ? panelLabel(panel) : "辅助区"} size="xl" contentClassName={`utility-dialog ${expanded ? "expanded-dialog" : ""}`} hideClose>{panelBody}</VDialog>
    <VDialog open={allSettings} onOpenChange={setAllSettings} title="全部设置" description="预览只展示入口层级，配置修改未接入。" size="lg"><div className="settings-preview-body"><h3>模型与服务</h3><p>厂商、模型和运行时配置继续集中管理。</p><h3>界面与偏好</h3><VButton variant="secondary" onPress={() => setDark(!dark)}>{dark ? "切换浅色" : "切换深色"}</VButton><p>关闭设置后，回到原对话和草稿。</p></div></VDialog>
    <VDialog open={broadcast} onOpenChange={setBroadcast} title="发送广播" description="这条消息会发给项目中的助手。预览不会实际发送。" footer={<VButton variant="primary" isDisabled={!broadcastDraft.trim()} onPress={() => { setBroadcast(false); setBroadcastDraft(""); setFeedback("示例广播已提交，未向真实助手发送"); }}>发送示例广播</VButton>}><VNativeTextarea aria-label="广播内容" rows={4} value={broadcastDraft} onChange={(event) => setBroadcastDraft(event.target.value)} placeholder="输入要发送给助手的消息…" /></VDialog>
    <VConfirmDialog open={stopTarget} onOpenChange={setStopTarget} title="停止检索任务？" description="已有记录和结果会保留。预览只模拟停止状态。" tone="danger" confirmLabel="停止任务" cancelLabel="继续运行" onConfirm={() => { setStopping(true); setStopTarget(false); setFeedback("已模拟停止请求，等待任务结束"); }} />
  </div></VuiProvider>;
}

const root = createRoot(document.getElementById("root")!);
root.render(<StrictMode><App /></StrictMode>);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
