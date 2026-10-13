import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Bot, Download, List, MoreHorizontal, PanelRightClose, PanelRightOpen, Plus, X } from "lucide-react";
import { VButton, VDialog, VDropdownMenu, VIconButton, VSplitWorkspace, VTabs, VTextarea, VuiProvider } from "../../src/components/vui";
import { ChatCenterTabStrip } from "../../src/routes/chat/ChatCenterTabStrip";
import routeStyles from "../../src/routes/ChatCodingRoute.styles";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "./preview.css";

const stripStyles = { ...routeStyles, tabStrip: "preview-tab-strip", tabStripSessions: "preview-tabs" };
const title = "主题 · 人工智能算力产业链的竞争格局与风险";
function App() {
  const [browse, setBrowse] = useState(false);
  const [rail, setRail] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [range, setRange] = useState("all");
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const [tab, setTab] = useState("main");
  const [mobile, setMobile] = useState(window.innerWidth < 720);
  useEffect(() => {
    const resize = () => setMobile(window.innerWidth < 720);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const railBody = <section className="preview-rail" aria-label="辅助工具">
    <div className="preview-rail-header"><strong>辅助工具</strong><VIconButton variant="ghost" label="收起侧栏" icon={<PanelRightClose size={16}/>} className="preview-action" onPress={() => setRail(false)}/></div>
    {["辅助对话", "浏览器", "CLI", "文件", "子 Agent", "计划"].map(label => <div className="preview-tool-row" key={label}>{label}<span>会话工具</span></div>)}
    <p>继续复用原有右侧栏及其工具。</p>
  </section>;
  const actions = <div className="preview-actions" role="toolbar" aria-label="会话视图与操作">
    <VIconButton variant="ghost" label="浏览会话" icon={<List size={16} strokeWidth={1.6}/>} className={`preview-action ${browse ? "preview-action-selected" : ""}`} aria-pressed={browse} onPress={() => setBrowse(value => !value)}/>
    <VIconButton variant="ghost" label={rail ? "收起侧栏" : "展开侧栏"} tooltip="侧栏" icon={rail ? <PanelRightClose size={16} strokeWidth={1.6}/> : <PanelRightOpen size={16} strokeWidth={1.6}/>} className={`preview-action ${rail ? "preview-action-selected" : ""}`} aria-expanded={rail} onPress={() => setRail(value => !value)}/>
    <span className="preview-action-divider" aria-hidden="true"/>
    <VDropdownMenu aria-label="会话操作" align="end" trigger={<VIconButton variant="ghost" label="更多会话操作" icon={<MoreHorizontal size={16} strokeWidth={1.6}/>} className="preview-action"/>} items={[{id: "export", label: "导出 HTML…", onSelect: () => { setExportOpen(true); setNotice(""); }}]}/>
  </div>;
  return <main className="header-actions-preview">
    <header className="preview-intro"><span>会话工具栏</span><h1>把三个入口收成一组</h1><p>布局控制留在标签行；导出放进更多菜单。统一高度、图标与悬停反馈。</p></header>
    <section className="preview-before" aria-label="当前问题"><span className="preview-label">当前</span><div className="preview-before-bar"><VButton variant="ghost">浏览会话</VButton><VButton icon={<PanelRightOpen size={16}/>}>侧栏</VButton></div><div className="preview-before-export">导出 HTML</div></section>
    <section className="preview-proposal" aria-label="优化后">
      <div className="preview-context"><span className="preview-label">优化后</span><span>普通对话 · 实际 VUI 控件</span></div>
      <VSplitWorkspace className="preview-workspace" columnsClassName={rail && !mobile ? "grid-cols-[minmax(0,1fr)_280px]" : "grid-cols-1"}
        main={<section className="preview-conversation">
          <ChatCenterTabStrip styles={stripStyles} lang="zh" agentSessionLabel={title} chatReturnTarget={null} chatReturnLabel="返回" groupPanelActive={false} projectBusActive={false} showSessionTabs showAgentFallbackTab={false} workspaceActiveTab="agent"
            sessionTabs={<><VButton role="tab" aria-selected={tab === "agent"} variant="ghost" contentLayout="plain" className={`preview-tab ${tab === "agent" ? "preview-tab-selected" : ""}`} onPress={() => setTab("agent")}><Bot size={14}/><span>炒股智能体</span><X size={12}/></VButton><VButton role="tab" aria-selected={tab === "main"} variant="ghost" contentLayout="plain" className={`preview-tab preview-long-tab ${tab === "main" ? "preview-tab-selected" : ""}`} onPress={() => setTab("main")}><Bot size={14}/><span title={title}>{title}</span><X size={12}/></VButton><VIconButton variant="ghost" label="新建会话" icon={<Plus size={15}/>} className="preview-action preview-add"/></>}
            fileTabs={null} sessionBrowserControl={actions} leftOverlayVisible rightOverlayVisible statusRailAvailable={false} rightRailLabel={undefined} conversationIndexOverlayOpen={false} statusRailOverlayOpen={rail} onActivateAgentFallbackTab={() => {}} onToggleLeftOverlay={() => {}} onToggleRightOverlay={() => setRail(value => !value)}/>
          <div className="preview-content">
            {browse ? <div className="preview-session-list"><h2>浏览会话</h2>{["资料整理与下一步建议", "模型部署记录", "界面布局讨论"].map(label => <VButton variant="ghost" key={label} className="preview-session-row" onPress={() => setBrowse(false)}><Bot size={16}/>{label}</VButton>)}</div> : <div className="preview-transcript"><p className="preview-user">帮我梳理当前资料，并给出下一步建议。</p><div className="preview-assistant"><Bot size={20}/><strong>项目助手</strong><span>刚刚</span></div><p>先核对资料来源，再整理关键结论和待确认的问题。</p></div>}
            <div className="preview-composer"><VTextarea aria-label="主对话草稿" placeholder="描述下一步要做什么…" value={draft} onChange={event => setDraft(event.target.value)} minRows={2}/><span>主对话和草稿继续保留</span></div>
          </div>
        </section>}
        aside={rail && !mobile ? railBody : undefined}/>
    </section>
    <p className="preview-footnote">预览只演示布局与入口，不发送消息，不执行 CLI，不生成真实导出文件。</p>
    <VDialog open={rail && mobile} onOpenChange={setRail} title="辅助工具" hideClose contentClassName="preview-rail-dialog">{railBody}</VDialog>
    <VDialog open={exportOpen} onOpenChange={setExportOpen} title="导出对话 HTML" description="导出能力保持原样，这里只演示新的入口位置。" size="sm" footer={<><VButton variant="secondary" onPress={() => setExportOpen(false)}>取消</VButton><VButton variant="primary" icon={<Download size={15}/>} onPress={() => setNotice("这是设计预览，不生成真实文件。")}>导出</VButton></>}>
      <div className="preview-export-form"><span>导出范围</span><VTabs aria-label="导出范围" value={range} onValueChange={setRange} items={[{id:"all",label:"全部对话"},{id:"selected",label:"选择轮次"}]}/>{notice ? <p role="status">{notice}</p> : null}</div>
    </VDialog>
  </main>;
}
document.documentElement.dataset.theme = "light";
const root = createRoot(document.getElementById("root")!);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
root.render(<VuiProvider><BrowserRouter><App/></BrowserRouter></VuiProvider>);
