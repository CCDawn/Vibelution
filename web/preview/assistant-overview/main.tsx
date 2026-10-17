import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ArrowRight, Bot, Check, CheckCircle2, ChevronDown, CircleAlert, Clock3, ExternalLink, ListTodo, MessageSquare, Minus, Monitor, PanelRightClose, PanelRightOpen, Paperclip, RefreshCw, Search, Send, Settings2, SlidersHorizontal, Wrench, X } from "lucide-react";
import { VButton, VDropdownMenu, VIconButton, VInput, VNativeButton, VTabs, VTextarea } from "../../src/components/vui";
import { VuiProvider } from "../../src/components/vui/VuiProvider";
import { WhaleRigCharacter } from "../../src/routes/desktopPet/WhaleRigCharacter";
import { queryKeys } from "../../src/api/queryKeys";
import type { PetAnimationState, PetActivityTone } from "../../src/api/types/petActivity";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/tailwind.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/route-css/desktop-pet.tailwind.css";
import "./preview.css";

const previewClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
previewClient.setQueryData(queryKeys.configPublic(), { language: "zh" });

function Character({ compact = false, animationState, tone }: { compact?: boolean; animationState: PetAnimationState; tone: PetActivityTone }) {
  return <div className={`character-stage ${compact ? "character-stage-small" : ""}`} data-animation={animationState} data-tone={tone}><WhaleRigCharacter animationState={animationState} name="大肥鲸" tone={tone} /></div>;
}

const motionModes = {
  idle: { label: "空闲，随时找我", action: "轻呼吸、自然眨眼", animation: "idle", tone: "idle" },
  thinking: { label: "正在思考", action: "抬眼、轻微歪头思考", animation: "thinking", tone: "running" },
  reading: { label: "正在阅读资料", action: "目光下移，跟随阅读", animation: "reading", tone: "running" },
  tooling: { label: "正在执行操作", action: "手部动作、专注执行", animation: "tooling", tone: "running" },
  verifying: { label: "正在验证结果", action: "侧目检查、核对结果", animation: "verifying", tone: "running" },
  answering: { label: "正在回复你", action: "嘴型随回复动作变化", animation: "answering", tone: "running" },
  message: { label: "有 1 条新消息", action: "短暂招呼一次，未读提示保留", animation: "celebrating", tone: "completed" },
  approval: { label: "有操作等你确认", action: "举手示意，保持等待", animation: "waiting", tone: "approval" },
  error: { label: "有任务遇到问题", action: "担忧表情、克制提醒", animation: "alert", tone: "error" },
  completed: { label: "任务刚刚完成", action: "短暂庆祝后恢复待机", animation: "celebrating", tone: "completed" },
} satisfies Record<string, { label: string; action: string; animation: PetAnimationState; tone: PetActivityTone }>;
type MotionMode = keyof typeof motionModes;

const shortcuts = [
  { label: "智能体", icon: Bot }, { label: "后台任务", icon: ListTodo },
  { label: "配置", icon: Settings2 }, { label: "运行诊断", icon: Wrench },
];
const titles = ["个人助理", "通用助手", "SCI-002 · Will the Navier–Stokes problem ever be solved?", "洛天依", "炒股智能体", "新会话", "平安银行 · 审慎情景分析", "近期新闻线索评估"];
const sessions = Array.from({ length: 124 }, (_, i) => ({ id: `session-${i}`, title: i === 0 ? "ttft 修复" : i === 1 ? "治理发现实测 · research · 2026-10-04" : titles[(i - 2) % titles.length], status: i < 2 ? "异常" : i === 2 ? "已完成" : "就绪" }));
const agents = Array.from({ length: 51 }, (_, i) => ({ id: `agent-${i}`, title: i < titles.length ? titles[i] : `研究助理 ${i + 1}`, status: "就绪" }));
type Tab = "attention" | "sessions" | "agents";
type Scene = "errors" | "busy" | "quiet";

function App() {
  const [tab, setTab] = useState<Tab>("attention");
  const [scene, setScene] = useState<Scene>("errors");
  const [motionMode, setMotionMode] = useState<MotionMode>("error");
  const [motionEvent, setMotionEvent] = useState(0);
  const [animationState, setAnimationState] = useState<PetAnimationState>("alert");
  const motion = motionModes[motionMode];
  const working = ["thinking", "reading", "tooling", "verifying", "answering"].includes(motionMode);
  useEffect(() => {
    const oneShot = motionMode === "message" || motionMode === "completed";
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setAnimationState(oneShot && reduced ? "idle" : motionModes[motionMode].animation);
    if (!oneShot) return;
    const timer = window.setTimeout(() => setAnimationState("idle"), 1400);
    return () => window.clearTimeout(timer);
  }, [motionMode, motionEvent]);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [toast, setToast] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [wide, setWide] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [desktop, setDesktop] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [messages, setMessages] = useState<Array<{role:"user"|"assistant";text:string}>>([
    {role:"assistant",text:"我在。想聊点什么，或者需要我帮你做件事？"},
  ]);
  const send = () => { if(!draft.trim())return; setMessages(current=>[...current,{role:"user",text:draft.trim()},{role:"assistant",text:"可以。先告诉我今天最重要的三件事，我帮你排个有余量的计划。"}]); setDraft(""); };
  const counts = { running: working ? 3 : motionMode === "approval" ? 2 : 0, waiting: motionMode === "approval" ? 1 : 0, failed: motionMode === "error" ? 2 : 0 };
  const scenarioSessions = sessions.map((row, i) => ({ ...row,
    title: motionMode === "approval" && i === 0 ? "研究报告发布前确认" : row.title,
    status: motionMode === "approval" ? (i === 0 ? "待确认" : i < 3 ? "运行中" : "就绪") : working ? (i < 3 ? "运行中" : "就绪") : scene === "quiet" ? "就绪" : row.status,
  }));
  const attention = motionMode === "error" ? scenarioSessions.slice(0, 2) : motionMode === "approval" ? scenarioSessions.slice(0, 1) : [];
  const choose = (id: string) => { setTab(id as Tab); setSearch(""); setPage(1); setFilter("all"); };
  const chooseMotion = (id: MotionMode) => { setMotionMode(id); setMotionEvent(value => value + 1); setScene(id === "error" ? "errors" : id === "approval" || ["thinking","reading","tooling","verifying","answering"].includes(id) ? "busy" : "quiet"); choose("attention"); };
  const toggleChat = () => { setChatOpen(!chatOpen); if (motionMode === "message") chooseMotion("idle"); };
  const navigate = (label: string) => setToast(`预览：打开${label}，正式版将进入现有页面。`);
  const rows = (tab === "agents" ? agents : scenarioSessions).filter(row => (!search || row.title.toLowerCase().includes(search.toLowerCase())) && (tab !== "sessions" || filter === "all" || row.status === filter));
  const pages = Math.max(1, Math.ceil(rows.length / 8));
  const activeRows = rows.slice((Math.min(page, pages) - 1) * 8, Math.min(page, pages) * 8);
  const selectStatus = (status: string) => { choose("sessions"); setFilter(status); };
  return <VuiProvider><main className="preview-app">
    <header className="preview-heading"><div><span className="preview-eyebrow">个人助理 / 工作台与桌面模式</span><h1>{desktop ? "点击角色，就能聊。" : "角色在左，聊天居中，操作在手边。"}</h1><p>隔离交互预览 · 模拟数据与消息，不连接真实写操作。</p></div>
      <div className="preview-tools"><VTabs value={desktop ? "desktop" : "workbench"} onValueChange={value=>setDesktop(value === "desktop")} aria-label="预览模式" items={[{id:"workbench",label:"工作台"},{id:"desktop",label:"桌面模式"}]}/>{!desktop ? <VButton variant="secondary" onPress={() => setWide(!wide)}>{wide ? "窄右栏" : "宽右栏"}</VButton> : null}<VDropdownMenu aria-label="角色状态演示" align="end" trigger={<VButton variant="secondary" icon={<ChevronDown size={13}/>}>状态演示：{motion.label}</VButton>} items={(Object.keys(motionModes) as MotionMode[]).map(id=>({id,label:motionModes[id].label,onSelect:()=>chooseMotion(id)}))}/></div>
    </header>
    {desktop ? <section className="desktop-stage" aria-label="桌面模式预览"><div className="desktop-watermark"><Monitor size={19}/><span>你的桌面</span></div>
      {chatOpen ? <section className="chat-popover" aria-label="个人助理聊天小窗"><header className="popup-header"><div className="popup-avatar"><Bot size={19}/></div><div className="popup-identity"><strong>大肥鲸</strong><span data-tone={motion.tone}><i/>{motion.label}</span></div><div className="popup-actions"><VIconButton variant="ghost" label="返回完整工作台" icon={<ExternalLink size={15}/>} onClick={()=>setDesktop(false)}/><VIconButton variant="ghost" label="收起聊天小窗" icon={<Minus size={16}/>} onClick={()=>setChatOpen(false)}/><VIconButton variant="ghost" label="关闭聊天小窗" icon={<X size={16}/>} onClick={()=>setChatOpen(false)}/></div></header>
        <div className="popup-messages"><div className="popup-date">今天</div>{messages.map((message,i)=><div key={i} className={`popup-message ${message.role}`}><p>{message.text}</p></div>)}</div>
        <div className="popup-composer"><VTextarea aria-label="给大肥鲸发消息" placeholder="说点什么，或者交给我一件事…" value={draft} onChange={e=>setDraft(e.target.value)} onKeyDown={e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();send();}}}/><div className="popup-compose-actions"><VIconButton variant="ghost" label="添加附件（预览）" icon={<Paperclip size={16}/>} onClick={()=>setToast("附件入口示意，预览不上传文件。")}/><span>Enter 发送 · Shift + Enter 换行</span><VIconButton variant="primary" label="发送消息" icon={<ArrowRight size={17}/>} isDisabled={!draft.trim()} onClick={send}/></div></div>
      </section> : <div className="desktop-idle-note"><span>{motionMode === "idle" ? "大肥鲸在这里陪着你" : motion.label}</span><p>点击角色，打开聊天小窗</p></div>}
      <VNativeButton className="desktop-character" aria-label="点击大肥鲸打开聊天小窗" onClick={toggleChat}><Character compact animationState={animationState} tone={motion.tone}/>{motionMode === "message" ? <span className="unread-badge">1</span> : null}<span className="character-cue"><MessageSquare size={13}/>{motionMode === "message" ? "有新消息" : chatOpen ? "收起聊天" : working ? motion.label : "聊一聊"}</span></VNativeButton>
    </section> : <div className={`workbench ${wide ? "wide-rail" : ""} ${collapsed ? "rail-closed" : ""}`}>
      <aside className="character-rail" aria-label="个人助理角色"><header><span>个人助理</span></header><div className="character-portrait"><Character animationState={animationState} tone={motion.tone}/>{motionMode === "message" ? <VButton variant="secondary" className="rail-new-message" onPress={()=>{chooseMotion("idle");setToast("已查看当前个人助理的新消息（预览）。");}}>查看 1 条新消息</VButton> : null}</div><div className="character-identity" data-tone={motion.tone}><h2>大肥鲸</h2><span><i/>{motion.label}</span></div><p className="character-line">陪你理清思路，也帮你把事情做好。</p><div className="character-rail-bottom"><VButton variant="secondary" className="desktop-switch" icon={<Monitor size={15}/>} onPress={()=>setDesktop(true)}>切换桌面模式</VButton><VButton variant="ghost" icon={<Settings2 size={14}/>} onPress={()=>navigate("助理设置")}>助理设置</VButton></div></aside>
      <section className="conversation"><header className="conversation-header"><div className="avatar"><Bot size={18}/></div><strong>个人助理</strong><span>大肥鲸</span>{collapsed ? <VIconButton variant="ghost" label="展开平台概览" icon={<PanelRightOpen size={17}/>} onClick={() => setCollapsed(false)}/> : null}</header>
        <div className="conversation-content"><div className="date">今天</div><div className="chat-question">帮我看看平台现在有没有需要处理的事项。</div><div className="assistant-answer"><div className="answer-mark"><Bot size={17}/></div><div><p>当前有 {attention.length} 项需要关注。</p><p className="muted">你可以从右侧直接进入对应会话；管理入口一直保留在上方。</p><div className="answer-links"><span><Check size={13}/> 会话状态已汇总</span><span><Check size={13}/> 管理入口可直接访问</span></div></div></div></div>
        <div className="composer"><span>告诉个人助理你想做什么…</span><VIconButton variant="ghost" label="发送消息（预览）" icon={<Send size={16}/>} onClick={() => setToast("这是右栏预览，未发送消息。")}/></div>
      </section>
      {!collapsed ? <aside className="overview" aria-label="平台概览">
        <div className="overview-pinned"><header className="overview-heading"><div><h2>平台概览</h2><span>刚刚更新</span></div><div className="header-actions"><VIconButton variant="ghost" label="刷新平台概览" isPending={refreshing} icon={<RefreshCw size={15}/>} onClick={() => {setRefreshing(true);setTimeout(()=>{setRefreshing(false);setToast("预览数据已刷新。");},500);}}/><VIconButton variant="ghost" label="收起平台概览" icon={<PanelRightClose size={16}/>} onClick={() => setCollapsed(true)}/></div></header>
          <nav className="shortcuts" aria-label="常用管理入口">{shortcuts.map(({label,icon:Icon})=><VButton key={label} variant="secondary" className="shortcut" contentLayout="plain" onPress={()=>navigate(label)}><Icon size={15}/><span>{label}</span><ArrowRight size={13}/></VButton>)}</nav>
          <div className="more-line"><span>常用管理</span><VDropdownMenu aria-label="更多管理入口" align="end" trigger={<VButton variant="ghost" className="more-button" icon={<ChevronDown size={13}/>}>更多管理</VButton>} items={["团队管理","工具管理","记忆管理","知识管理"].map(label=>({id:label,label,onSelect:()=>navigate(label)}))}/></div>
          <div className="status-strip" aria-label="平台运行状态"><VButton variant="ghost" contentLayout="plain" className="status-item" onPress={()=>selectStatus("运行中")}><span className="status-dot running"/>运行中 <strong>{counts.running}</strong></VButton><VButton variant="ghost" contentLayout="plain" className="status-item" onPress={()=>selectStatus("待确认")}><span className="status-dot waiting"/>待确认 <strong>{counts.waiting}</strong></VButton><VButton variant="ghost" contentLayout="plain" className={`status-item ${counts.failed ? "has-errors" : ""}`} onPress={()=>selectStatus("异常")}><span className="status-dot error"/>异常 <strong>{counts.failed}</strong></VButton></div>
          <VTabs className="overview-tabs" listClassName="overview-tab-list" triggerClassName="overview-tab" value={tab} onValueChange={choose} aria-label="概览内容" items={[{id:"attention",label:<>需关注 <span>{attention.length}</span></>},{id:"sessions",label:<>会话 <span>124</span></>},{id:"agents",label:<>智能体 <span>51</span></>}]}/>
          {tab !== "attention" ? <div className="list-controls"><div className="search"><Search size={14}/><VInput aria-label={tab === "sessions" ? "搜索会话" : "搜索智能体"} placeholder={tab === "sessions" ? "搜索会话…" : "搜索智能体…"} value={search} onChange={e=>{setSearch(e.target.value);setPage(1);}}/></div>{tab === "sessions" ? <VDropdownMenu aria-label="筛选会话状态" align="end" trigger={<VIconButton variant="ghost" label={`筛选状态：${filter === "all" ? "全部" : filter}`} icon={<SlidersHorizontal size={15}/>}/>} items={[{id:"all",label:"全部会话"},{id:"运行中",label:"运行中"},{id:"待确认",label:"待确认"},{id:"异常",label:"异常"}].map(item=>({...item,onSelect:()=>{setFilter(item.id);setPage(1);}}))}/> : null}</div> : null}
        </div>
        <div className="overview-content" key={`${tab}-${filter}`}>
          {tab === "attention" ? <>{attention.length ? <><p className="section-intro">{scene === "errors" ? "2 个异常需要查看" : "1 项操作等待你的确认"}</p><div className="attention-list">{attention.map((item,i)=><VButton key={item.id} variant="ghost" contentLayout="plain" className="attention-row" onPress={()=>setToast(`预览：打开会话「${item.title}」`)}><span className={`attention-icon ${scene === "busy" ? "approval" : ""}`}>{scene === "busy" ? <Clock3 size={16}/> : <CircleAlert size={16}/>}</span><span className="attention-copy"><strong title={item.title}>{item.title}</strong><span>{scene === "busy" ? "查看操作详情后确认" : i ? "上次运行异常退出" : "模型请求未完成"}</span></span><ArrowRight size={14}/></VButton>)}</div></> : <div className="healthy"><CheckCircle2 size={25}/><strong>当前没有待处理事项</strong><p>运行和待确认状态会在这里集中出现。</p></div>}{scene === "busy" ? <div className="active-note"><span className="status-dot running"/><span>还有 {counts.running} 个会话正在运行</span><VButton variant="ghost" onPress={()=>selectStatus("运行中")}>查看</VButton></div> : null}<div className="quiet-note"><CheckCircle2 size={14}/><span>{scene === "quiet" ? "平台运行正常" : "其余会话未运行，不占用关注列表"}</span></div></> : <><div className="list-summary"><span>{tab === "sessions" ? (filter === "all" ? "全部会话" : filter) : "全部智能体"}</span><span>{rows.length} 项</span></div>{activeRows.length ? <ul className="entity-list">{activeRows.map(item=><li key={item.id}><VButton variant="ghost" contentLayout="plain" className="entity-row" onPress={()=>navigate(`${tab === "sessions" ? "会话" : "智能体"}「${item.title}」`)}><span className="entity-icon">{tab === "sessions" ? <MessageSquare size={15}/> : <Bot size={15}/>}</span><span className="entity-title" title={item.title}>{item.title}</span><span className={`entity-status ${item.status === "异常" ? "failed" : ""}`}>{item.status}</span></VButton></li>)}</ul> : <div className="no-results">{search ? "没有匹配的结果" : "当前没有此状态的会话"}</div>}<div className="pagination"><span>{rows.length ? `${(Math.min(page,pages)-1)*8+1}–${Math.min(Math.min(page,pages)*8,rows.length)} / ${rows.length}` : "0 项"}</span><div><VButton variant="ghost" isDisabled={page<=1} onPress={()=>setPage(page-1)}>上一页</VButton><VButton variant="ghost" isDisabled={page>=pages} onPress={()=>setPage(page+1)}>下一页</VButton></div></div></>}
        </div>
      </aside> : null}
    </div>}
    <footer className="preview-footnote">{desktop ? "点击桌面上的角色打开聊天。可试发消息、收起小窗、返回工作台；消息仅保存在预览页面。" : "左侧角色不脱离工作台。右侧可切换列表、搜索、翻页和筛选；点击「桌面模式」预览聊天小窗。"}<span className="motion-explanation">当前动作：{motion.action}。状态为演示，尚未接入实时事件。</span></footer>
    {toast ? <div role="status" className="preview-toast" onClick={()=>setToast("")}>{toast}<VButton variant="ghost" onPress={()=>setToast("")}>关闭</VButton></div> : null}
  </main></VuiProvider>;
}
createRoot(document.getElementById("root")!).render(<QueryClientProvider client={previewClient}><App/></QueryClientProvider>);
