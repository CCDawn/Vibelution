import { useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUp, Bot, ChevronRight, Code2, FileCode2, Globe, ListTree, MessageSquare, MoreHorizontal, PanelRightClose, Plus, Terminal, X, Maximize2 } from "lucide-react";
import { VButton, VDropdownMenu, VNativeInput, VNativeTextarea } from "../../src/components/vui";
import { activeChatRightRailTab, chatRightRailKindLabel, closeChatRightRailTab, EMPTY_CHAT_RIGHT_RAIL, normalizeChatRightRailBrowserUrl, openChatRightRailTab, openFreshChatRightRailSideTab, updateChatRightRailSideDraft, type ChatRightRailKind, type ChatRightRailModel } from "../../src/routes/chat/chatRightRailModel";

export type ProjectPanel = "tasks" | "changes" | "notices";
export type ToolKind = Exclude<ChatRightRailKind, "review">;
export type RailPanel = ProjectPanel | ToolKind;
export const isProjectPanel = (kind: RailPanel | null): kind is ProjectPanel => kind === "tasks" || kind === "changes" || kind === "notices";
export const toolLabel = (kind: ToolKind) => kind === "terminal" ? "CLI" : chatRightRailKindLabel(kind, "zh");
const launcher: ToolKind[] = ["side", "browser", "terminal", "file", "directory", "plan", "workflow", "trajectory", "bash", "devtools"];
const icons = { side: MessageSquare, browser: Globe, terminal: Terminal, file: FileCode2, subagent: Bot, directory: ListTree, plan: ListTree, workflow: ListTree, trajectory: Code2, bash: Terminal, devtools: Code2 };
function initialModel(session: string) {
  let model = openChatRightRailTab(EMPTY_CHAT_RIGHT_RAIL, { kind: "side", title: "辅助对话" });
  if (session === "架构与导航整理") {
    model = openChatRightRailTab(model, { kind: "browser", url: "https://example.com/workbench" });
    model = openChatRightRailTab(model, { kind: "terminal" });
  }
  return model;
}

/** The real rail's tab/draft/close model is reused; tool bodies remain isolated fixtures. */
export function useWorkspaceTools(session: string) {
  const [models, setModels] = useState<Record<string, ChatRightRailModel>>({});
  const model = models[session] ?? initialModel(session);
  const active = activeChatRightRailTab(model);
  const [messages, setMessages] = useState<Record<string, string[]>>({});
  const [commands, setCommands] = useState<Record<string, string[]>>({});
  const [commandDrafts, setCommandDrafts] = useState<Record<string, string>>({});
  const [browserErrors, setBrowserErrors] = useState<Record<string, string>>({});
  const [urlDrafts, setUrlDrafts] = useState<Record<string, string>>({});
  function setModel(next: ChatRightRailModel) { setModels((current) => ({ ...current, [session]: next })); }
  function open(kind: ToolKind, id?: string) {
    const retained = id ? model.tabs.find((tab) => tab.id === id) ?? model.closed.find((tab) => tab.id === id) : undefined;
    const next = openChatRightRailTab(model, retained ?? { kind, title: toolLabel(kind), targetId: kind === "subagent" ? "research-helper" : undefined, filePath: kind === "file" ? "web/src/app/AppShell.tsx" : undefined });
    setModel(next);
  }
  function close(id: string) {
    const next = closeChatRightRailTab(model, id);
    setModel(next);
    return activeChatRightRailTab(next)?.kind as ToolKind | undefined;
  }
  function freshSide() { setModel(openFreshChatRightRailSideTab(model, { titleBase: "辅助对话" })); }
  const key = `${session}:${active?.id ?? ""}`;
  const browserError = browserErrors[key] ?? "";
  const currentMessages = messages[key] ?? [];
  const currentCommands = commands[session] ?? [];
  const commandDraft = commandDrafts[session] ?? "";
  const urlDraft = urlDrafts[key] ?? active?.url ?? "https://example.com/workbench";
  function updateUrl(value: string) {
    setUrlDrafts((current) => ({ ...current, [key]: value }));
    const url = normalizeChatRightRailBrowserUrl(value);
    if (!url) { setBrowserErrors((current) => ({ ...current, [key]: "请输入 http 或 https 地址。" })); return; }
    setBrowserErrors((current) => ({ ...current, [key]: "" }));
    setModel({ ...model, tabs: model.tabs.map((tab) => tab.id === active?.id ? { ...tab, url } : tab) });
  }
  return {
    model, active, open, close, freshSide,
    content: !active ? <div className="panel-state"><Plus size={24} /><h3>打开一个辅助工具</h3><p>使用右上角的 ＋ 选择工具。</p></div> : <>
      <div className="tool-context"><span>当前会话</span><strong>{session}</strong></div>
      {active.kind === "side" ? <div className="side-chat-preview"><div className="side-chat-head"><span className="assistant-avatar">V</span><div><strong>辅助助手</strong><span>独立讨论，主对话保持原样</span></div></div><div className="side-chat-scroll"><div className="side-answer">可以在这里讨论细节、核对一个问题，或整理主对话之外的思路。</div>{currentMessages.map((text, index) => <div key={index}><div className="side-user">{text}</div><div className="side-answer">这条消息已保留在当前辅助对话中。这里是交互示例，未调用真实模型。</div></div>)}</div><form className="side-composer" onSubmit={(event) => { event.preventDefault(); const text = active.draft?.trim(); if (!text) return; setMessages((current) => ({ ...current, [key]: [...currentMessages, text] })); setModel(updateChatRightRailSideDraft(model, active.id, "")); }}><VNativeTextarea rows={3} aria-label="辅助对话输入" placeholder="在辅助对话中提问…" value={active.draft ?? ""} onChange={(event) => setModel(updateChatRightRailSideDraft(model, active.id, event.target.value))} /><div><span>辅助助手</span><VButton variant="secondary" type="submit" className="icon-control" aria-label="发送辅助对话示例" isDisabled={!active.draft?.trim()}><ArrowUp size={16} /></VButton></div></form></div> : null}
      {active.kind === "browser" ? <div className="browser-preview"><form className="browser-address" onSubmit={(event) => { event.preventDefault(); updateUrl(urlDraft); }}><Globe size={15} /><VNativeInput aria-label="浏览器地址" value={urlDraft} onChange={(event) => setUrlDrafts((current) => ({ ...current, [key]: event.target.value }))} /><VButton type="submit" variant="ghost" className="icon-control" aria-label="打开示例地址"><ArrowRight size={15} /></VButton></form>{browserError ? <p className="browser-error" role="alert">{browserError}</p> : null}<div className="browser-page"><div className="browser-site-mark">V / WORKBENCH</div><h3>一个工作区，多个辅助工具</h3><p>任务、对话、浏览器和 CLI 在同一侧栏中按需打开。</p><div className="browser-article"><h4>保留当前工作</h4><p>切换工具后，草稿、浏览器地址和终端输出仍可继续查看。</p><h4>按需展开</h4><p>长页面和详细差异可以扩大显示，关闭后返回当前对话。</p></div></div><p className="tool-fixture-note">网页内容为本地示例，不访问输入的外部地址。</p></div> : null}
      {active.kind === "terminal" || active.kind === "bash" ? <div className="terminal-preview"><div className="terminal-heading"><Terminal size={14} /><span>{active.kind === "bash" ? "后台输出" : "CLI · 开发助手"}</span><span className="terminal-live">运行中</span></div><div className="terminal-output" role="log" aria-label="CLI 输出"><p className="terminal-dim">Vibelution · 示例工作区</p><p>› 正在核对导航与辅助工具入口</p><p><span className="terminal-ok">✓</span> 已读取 AppShell.tsx</p><p><span className="terminal-ok">✓</span> 已定位 ChatRightRail</p><p className="terminal-dim">切换或关闭标签不会停止运行。</p>{currentCommands.map((command, index) => <div key={index}><p>› {command}</p><p className="terminal-dim">示例输出：已保留命令文本，未执行 Shell。</p></div>)}</div>{active.kind === "terminal" ? <form className="terminal-command" onSubmit={(event) => { event.preventDefault(); const command = commandDraft.trim(); if (command) { setCommands((current) => ({ ...current, [session]: [...currentCommands, command] })); setCommandDrafts((current) => ({ ...current, [session]: "" })); } }}><span>›</span><VNativeInput aria-label="CLI 示例命令" placeholder="输入示例命令…" value={commandDraft} onChange={(event) => setCommandDrafts((current) => ({ ...current, [session]: event.target.value }))} /><VButton type="submit" variant="ghost" className="icon-control" aria-label="提交 CLI 示例命令" isDisabled={!commandDraft.trim()}><ArrowUp size={15} /></VButton></form> : null}</div> : null}
      {active.kind === "file" ? <section className="tool-file-preview"><div className="scope-row"><FileCode2 size={16} /><span>AppShell.tsx</span><span className="muted">只读示例</span></div><pre className="code-diff"><span>  1  export function AppShell() {'{'}</span><span>  2    return (</span><span>  3      {'<Workbench>'}</span><span>  4        {'<Conversation />'}</span><span>  5        {'<AuxiliaryRail />'}</span><span>  6      {'</Workbench>'}</span><span>  7    );</span><span>  8  {'}'}</span></pre></section> : null}
      {active.kind === "directory" || active.kind === "subagent" ? <section className="tool-directory-preview"><h3>{active.kind === "directory" ? "子 Agent" : "研究助手"}</h3><p className="muted">当前会话中的辅助工作</p><VButton variant="ghost" contentLayout="plain" className="list-row" onPress={() => open("subagent")}><Bot size={17} /><span className="row-main"><strong>研究助手</strong><span>界面参考 · 进行中</span></span><ChevronRight size={14} /></VButton>{active.kind === "subagent" ? <div className="side-answer">已找到 OpenCode 和 Zed 的面板设计。正在比较标签切换与会话保留方式。</div> : null}</section> : null}
      {active.kind === "plan" || active.kind === "workflow" || active.kind === "trajectory" || active.kind === "devtools" ? <section className="tool-directory-preview"><h3>{toolLabel(active.kind)}</h3><p className="muted">关联当前会话的只读详情</p><div className="tool-outline"><p>已确认：辅助工具共用右栏</p><p>正在进行：标签切换与状态保留</p><p>接下来：核对桌面与窄屏交互</p></div><p className="tool-fixture-note">保留现有详情入口，此处只模拟内容。</p></section> : null}
    </>,
  };
}

type RailHeaderProps = {
  panel: RailPanel | null;
  projectTabs: ProjectPanel[];
  projectLabels: Record<ProjectPanel, string>;
  tools: ReturnType<typeof useWorkspaceTools>;
  onProject: (panel: ProjectPanel) => void;
  onTool: (kind: ToolKind, id?: string) => void;
  onCloseProject: (panel: ProjectPanel) => void;
  onCloseTool: (id: string) => void;
  onFreshSide: () => void;
  onCollapse: () => void;
  onExpand: () => void;
};

export function WorkspaceRailHeader(props: RailHeaderProps) {
  const strip = useRef<HTMLDivElement>(null);
  const tabs = [
    ...props.projectTabs.map((kind) => ({ id: `project:${kind}`, label: props.projectLabels[kind], selected: props.panel === kind, activate: () => props.onProject(kind), close: () => props.onCloseProject(kind), project: true, Icon: kind === "tasks" ? ListTree : kind === "changes" ? FileCode2 : MessageSquare })),
    ...props.tools.model.tabs.map((tab) => ({ id: tab.id, label: tab.kind === "side" ? tab.title || "辅助对话" : toolLabel(tab.kind as ToolKind), selected: !isProjectPanel(props.panel) && props.panel !== null && props.tools.model.activeId === tab.id, activate: () => props.onTool(tab.kind as ToolKind, tab.id), close: () => props.onCloseTool(tab.id), project: false, Icon: icons[tab.kind as ToolKind] })),
  ];
  const activeId = tabs.find((tab) => tab.selected)?.id;
  useEffect(() => { strip.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" }); }, [activeId]);
  return <div className="workspace-rail-header">
    <div className="workspace-tabstrip" ref={strip} role="tablist" aria-label="辅助区" onKeyDown={(event) => {
      const index = tabs.findIndex((tab) => tab.id === (event.target as HTMLElement).dataset.tabId);
      if (index < 0) return;
      const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index - 1 + tabs.length) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
      if (next < 0) return;
      event.preventDefault(); tabs[next].activate(); strip.current?.querySelectorAll<HTMLElement>('[role="tab"]')[next]?.focus();
    }}>{tabs.map((tab) => <div className={`workspace-tab ${tab.selected ? "workspace-tab-active" : ""}`} key={tab.id} data-project={tab.project}><VButton variant="ghost" contentLayout="plain" role="tab" aria-selected={tab.selected} tabIndex={tab.selected ? 0 : -1} data-tab-id={tab.id} className="workspace-tab-label" title={`${tab.label} · ${tab.project ? "项目" : "当前会话"}`} onPress={tab.activate}><tab.Icon size={13} /><span>{tab.label}</span></VButton><VButton variant="ghost" className="workspace-tab-close" aria-label={`关闭标签 ${tab.label}`} title="关闭标签，不停止运行" onPress={tab.close}><X size={11} /></VButton></div>)}</div>
    <div className="workspace-rail-controls"><VDropdownMenu aria-label="打开辅助工具" align="end" contentClassName="rail-tool-menu" trigger={<VButton variant="ghost" className="icon-control" aria-label="打开辅助工具" title="打开辅助工具"><Plus size={16} /></VButton>} items={[...(["tasks", "changes", "notices"] as ProjectPanel[]).map((kind) => ({ id: `project:${kind}`, label: props.projectLabels[kind], icon: kind === "tasks" ? <ListTree size={15} /> : kind === "changes" ? <FileCode2 size={15} /> : <MessageSquare size={15} />, onSelect: () => props.onProject(kind) })), ...launcher.map((kind) => { const Icon = icons[kind]; return { id: kind, label: toolLabel(kind), icon: <Icon size={15} />, onSelect: () => props.onTool(kind) }; }), { id: "fresh-side", label: "新建辅助对话", icon: <MessageSquare size={15} />, onSelect: props.onFreshSide }]} /><VDropdownMenu aria-label="标签列表" align="end" trigger={<VButton variant="ghost" className="icon-control" aria-label="标签列表" title="已打开与最近关闭的标签"><MoreHorizontal size={16} /></VButton>} items={[...tabs.map((tab) => ({ id: tab.id, label: `${tab.selected ? "✓ " : ""}${tab.label}`, onSelect: tab.activate })), ...props.tools.model.closed.map((tab) => ({ id: `closed:${tab.id}`, label: `重新打开 ${toolLabel(tab.kind as ToolKind)}`, onSelect: () => props.onTool(tab.kind as ToolKind, tab.id) }))]} /><VButton variant="ghost" className="icon-control" aria-label="展开辅助工作区" title="展开" onPress={props.onExpand}><Maximize2 size={14} /></VButton><VButton variant="ghost" className="icon-control" aria-label="收起辅助区" title="收起，保留所有标签" onPress={props.onCollapse}><PanelRightClose size={16} /></VButton></div>
  </div>;
}
