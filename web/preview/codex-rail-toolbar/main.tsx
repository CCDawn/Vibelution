import { useState, type CSSProperties } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ArrowLeft, Bell, Bot, ChevronDown, ChevronRight, Code2, FileDiff, FileSearch, GitBranch, Globe, List, ListTodo, MessageSquare, MoreHorizontal, PanelLeftClose, PanelRightClose, PanelRightOpen, Plus, Search, Settings, Terminal, X } from "lucide-react";
import { VButton, VIconButton, VDropdownMenu, VSplitWorkspace, VTextarea } from "../../src/components/vui";
import { ChatCenterTabStrip } from "../../src/routes/chat/ChatCenterTabStrip";
import { ChatRightRail, type ChatRightRailReview, type ChatRightRailSideClient } from "../../src/routes/chat/ChatRightRail";
import { EMPTY_CHAT_RIGHT_RAIL, type ChatRightRailModel } from "../../src/routes/chat/chatRightRailModel";
import routeStyles from "../../src/routes/ChatCodingRoute.styles";
import "../../src/design/base.css";
import "../../src/design/tokens.css";
import "../../src/design/tailwind.css";
import "./preview.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const review: ChatRightRailReview = {
  sessionTitle: "会话文件", sessionEmptyLabel: "这场会话还没有文件改动", sessionPaths: [], sessionSelectedPath: null, sessionChangedPaths: new Set(),
  gitTitle: "Git 改动", gitEmptyLabel: "没有未提交的改动", gitPending: false, gitPendingLabel: "正在读取", gitUnavailableLabel: "暂无 Git 信息",
  gitPaths: [], gitSelectedPath: null, diff: undefined, diffLoading: false, hasDiff: false, file: null, fileLoading: false, fileError: "", sourceLabel: "来源", onSelectSessionFile: () => {}, onSelectGitFile: () => {},
};
const mockSideClient: ChatRightRailSideClient = {
  createChild: async () => ({ childSessionId: "preview-child", parentSessionId: "preview-parent" }),
  submit: async () => {}, fetchDetail: async () => ({ status: "idle", currentPhase: "idle", messages: [] }),
};
const icons = [MessageSquare, FileSearch, Terminal, Globe, Code2, ListTodo, FileDiff, Bell];
const iconStyles = Object.fromEntries(icons.map((Icon, index) => [`--launcher-icon-${index + 1}`, `url("data:image/svg+xml,${encodeURIComponent(renderToStaticMarkup(<Icon size={16} strokeWidth={1.6} color="#63676d"/>))}")`])) as CSSProperties;
const headerStyles = { ...routeStyles, tabStrip: "preview-tab-strip", tabStripSessions: "preview-session-tabs", overlayPaneControls: "preview-controls", overlayPaneToggle: "preview-quiet preview-toggle", tabActive: "preview-toggle-active" };
const FINANCE_TITLE = "主题 · 人工智能算力产业链的竞争格局与风险";

function App() {
  const [railModel, setRailModel] = useState<ChatRightRailModel>(EMPTY_CHAT_RIGHT_RAIL);
  const [railOpen, setRailOpen] = useState(true);
  const [browse, setBrowse] = useState(false);
  const [title, setTitle] = useState(FINANCE_TITLE);
  const [text, setText] = useState("");
  return <div className="codex-alignment-preview" style={iconStyles}>
    <header className="preview-global-bar">
      <VIconButton label="返回" icon={<ArrowLeft size={16}/>} className="preview-quiet"/>
      <nav aria-label="主导航">{["对话", "智能体", "团队", "进化", "记忆库", "Agent 管理"].map(label => <VButton key={label} className={`preview-quiet ${label === "对话" ? "preview-nav-active" : ""}`}>{label}</VButton>)}</nav>
      <div className="preview-global-tools"><span className="preview-running">• 进行中 0 <ChevronDown size={12}/></span><span className="preview-connected">● 已连接</span><VIconButton label="Git" icon={<GitBranch size={16}/>} className="preview-quiet"/><VIconButton label="通知" icon={<Bell size={16}/>} className="preview-quiet"/><VIconButton label="设置" icon={<Settings size={16}/>} className="preview-quiet"/></div>
    </header>
    <VSplitWorkspace className={`preview-workspace ${railOpen ? "" : "preview-rail-closed"}`} columnsClassName={railOpen ? "grid-cols-[240px_minmax(0,1fr)_300px]" : "grid-cols-[240px_minmax(0,1fr)]"}
      sidebar={<div className="preview-left">
        <div className="preview-index-title"><strong>会话</strong><VIconButton label="搜索 Agent 或团队" icon={<Search size={16}/>} className="preview-quiet"/><VIconButton label="新建任务" icon={<Plus size={16}/>} className="preview-quiet"/><VIconButton label="收起会话列" icon={<PanelLeftClose size={16}/>} className="preview-quiet"/></div>
        <VButton className="preview-sort" trailingIcon={<ChevronDown size={14}/>}>按更新时间</VButton>
        {["会话 Agent", "监督进化团队", "知识库内容扩充团队"].map((label, index) => <VButton key={label} className="preview-group" icon={<ChevronRight size={12}/>} trailingIcon={<span>{[2,5,4][index]}</span>}>{label}</VButton>)}
        <div className="preview-group-caption"><ChevronDown size={12}/>特殊 Agent <span>13</span></div>
        {["炒股智能体", "资料 Agent", "能力顾问"].map((label, index) => <VButton key={label} className={`preview-agent ${index === 0 ? "preview-agent-selected" : ""}`} contentLayout="plain"><span className="preview-avatar"><Bot size={23}/></span><span><strong>{label}</strong><small>{["阿里云 DashScope Qwen3.8 Flash", "广域检索", "科研组织顾问"][index]}</small></span></VButton>)}
      </div>}
      main={<section className="preview-center">
        <ChatCenterTabStrip styles={headerStyles} lang="zh" agentSessionLabel={title} chatReturnTarget={null} chatReturnLabel="返回" groupPanelActive={false} projectBusActive={false} showSessionTabs showAgentFallbackTab={false} workspaceActiveTab="agent"
          sessionTabs={<><VButton role="tab" aria-selected={title === "炒股智能体"} className={`preview-session-tab ${title === "炒股智能体" ? "preview-session-tab-active" : ""}`} contentLayout="plain" onClick={() => setTitle("炒股智能体")} icon={<Bot size={14} strokeWidth={1.5}/>}><span>炒股智能体</span><X size={13} strokeWidth={1.5}/></VButton><VButton role="tab" aria-selected={title !== "炒股智能体"} className={`preview-session-tab ${title !== "炒股智能体" ? "preview-session-tab-active" : ""}`} contentLayout="plain" onClick={() => setTitle(FINANCE_TITLE)} icon={<Bot size={14} strokeWidth={1.5}/>}><span>{title === "炒股智能体" ? FINANCE_TITLE : title}</span><X size={13} strokeWidth={1.5}/></VButton><VIconButton label="在当前 Agent 下新建会话" className="preview-quiet preview-tab-add" icon={<Plus size={16} strokeWidth={1.5}/>}/></>}
          fileTabs={null} sessionBrowserControl={<div className="preview-controls"><VIconButton label="浏览会话" className={`preview-quiet preview-browse ${browse ? "preview-toggle-active" : ""}`} icon={<List size={16} strokeWidth={1.5}/>} aria-pressed={browse} onClick={() => setBrowse(!browse)}/><VIconButton label="侧栏" className="preview-quiet preview-browse" icon={railOpen ? <PanelRightClose size={16} strokeWidth={1.5}/> : <PanelRightOpen size={16} strokeWidth={1.5}/>} aria-expanded={railOpen} onClick={() => setRailOpen(!railOpen)}/></div>}
          leftOverlayVisible rightOverlayVisible={false} statusRailAvailable={false} rightRailLabel={undefined} rightRailOpen={railOpen} conversationIndexOverlayOpen={false} statusRailOverlayOpen={railOpen} onActivateAgentFallbackTab={() => {}} onToggleLeftOverlay={() => {}} onToggleRightOverlay={() => setRailOpen(!railOpen)}/>
        <div className="preview-main-body">
          <div className="preview-body-tools"><VDropdownMenu aria-label="会话操作" trigger={<VIconButton label="会话操作" icon={<MoreHorizontal size={16}/>} className="preview-quiet"/>} items={[{id:"export",label:"导出 HTML",onSelect:()=>{}}]}/></div>
          {browse ? <div className="preview-browse-page"><h2>会话</h2><p>炒股智能体</p>{["问候", "继续对话", "新会话"].map((name,index)=><VButton className="preview-session-row" key={name} contentLayout="plain" onClick={()=>{setTitle(name);setBrowse(false);}}><Bot size={18}/><span><strong>{name}</strong><small>{["今天 10:32","昨天 18:10","10 月 10 日"][index]}</small></span><ChevronRight size={14}/></VButton>)}</div> : <><div className="preview-transcript"><div className="preview-user-heading">Administrator <small>今天 10:32</small><span>A</span></div><div className="preview-user-message">帮我梳理当前资料，并给出下一步建议。</div><div className="preview-assistant-heading"><Bot size={24}/><span>炒股智能体</span><small>今天 10:32</small></div><p>可以先核对资料来源，再整理关键结论与待确认的问题。</p></div><div className="preview-composer"><VTextarea aria-label="发送消息" placeholder="描述下一步要做什么..." value={text} onChange={event=>setText(event.target.value)}/><div><VIconButton label="选择附件" icon={<Plus size={16}/>} className="preview-quiet"/><span>请求批准 <ChevronDown size={11}/></span><span className="preview-model">OpenAI GPT-5.5 <ChevronDown size={11}/></span></div></div></>}
        </div>
      </section>}
      aside={railOpen ? <div className="preview-right"><ChatRightRail className="preview-real-rail" lang="zh" sessionId="preview-parent" model={railModel} onModelChange={update=>setRailModel(current=>typeof update==="function"?update(current):update)} onCollapse={()=>setRailOpen(false)} review={review} devtools={{phase:"idle",status:"completed",messages:[{role:"user"},{role:"assistant"}]}} terminalRun={null} terminalMountedInCenter={false} onOpenFile={()=>{}} sideClient={mockSideClient}/></div> : undefined}/>
    <div className="preview-disclosure">设计预览 · 会话与工具数据为模拟</div>
  </div>;
}
const previewRoot = createRoot(document.getElementById("root")!);
if (import.meta.hot) import.meta.hot.dispose(() => previewRoot.unmount());
previewRoot.render(<QueryClientProvider client={queryClient}><BrowserRouter><App/></BrowserRouter></QueryClientProvider>);
