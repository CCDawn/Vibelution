import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, Bell, BookOpen, Clock3, MapPin, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Send, Settings, X } from "lucide-react";
import { VButton, VIconButton, VSurface, VTabs, VDialog, VPopover, VTextarea, VSessionWorkbenchPage, VuiProvider } from "../../src/components/vui";
import { CompanionPortrait } from "../../src/routes/companions/CompanionPortrait";
import type { VirtualHumanCompanion } from "../../src/api/types";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "./preview.css";

const person = { agentId: "preview-companion", displayName: "洛天依", avatarImageUrl: new URL("./portrait.png", import.meta.url).href,
  snapshot: { state: { lifePaused: false }, causal: { embodiment: { expressionId: "neutral", motionPreset: "still", sceneKey: "home-day" } } },
} as unknown as VirtualHumanCompanion;
const moments = [
  { id: "a", date: "10月13日 21:00", activity: "复习和个人创作", text: "完成了复习和个人创作。" },
  { id: "b", date: "10月13日 12:00", activity: "学习与创作", text: "完成了专注处理自己的学习与创作。" },
];
type Moment = typeof moments[number];
type Message = { role: "person" | "user"; text: string; time?: string };
const initialMessages: Message[] = [
  { role: "person", text: "没事呀～就是刚散步回来，心情挺好的，想跟你分享一下。", time: "19:01" },
  { role: "person", text: "今天傍晚外面的风挺舒服的，感觉整个人都放松了不少。你呢，今天过得怎么样？" },
];

function LifeContent({ tab, setTab, onSelect }: { tab: string; setTab: (tab: string) => void; onSelect: (item: Moment) => void }) {
  return <><VTabs aria-label="生活内容" value={tab} onValueChange={setTab} items={[{ id: "now", label: "现在" }, { id: "plan", label: "计划" }, { id: "memory", label: "记忆" }]} />
    <div className="life-content">{tab === "now" ? <>
      <div className="section-label">此刻</div><h3 className="life-headline">在家，自由活动</h3><p>心情愉快，享受一会儿自己的时间。</p>
      <div className="next-moment"><Clock3 size={16} /><div><small>下一项计划 · 18:00</small><strong>傍晚散步</strong></div></div>
      <div className="section-label spaced">最近的生活</div><div className="recent-note"><time>10月13日</time><p>完成了复习和个人创作。</p><span className="source-label">模拟日程记录</span></div>
      <p className="sample-caption">状态和计划为示例，未连接人物服务。</p>
    </> : tab === "plan" ? <>
      <div className="section-label">今天的计划 · 示例</div><div className="plan-row"><time>12:00</time><div><h3>学习与创作</h3><p>已结束</p></div></div><div className="plan-row"><time>18:00</time><div><h3>傍晚散步</h3><p>待开始</p></div></div>
      <p className="plan-explain">下一次计划时间到达时，人物会开始判断下一步。应用关闭期间暂停。</p><p className="sample-caption">仅展示计划排版，不执行定时行动。</p>
    </> : <>
      <div className="memory-intro"><h3>生活记忆</h3><p>读一段记录，看看它从哪里来。</p></div><div className="memory-list">{moments.map(item => <VButton contentLayout="plain" variant="ghost" className="memory-row" key={item.id} onPress={() => onSelect(item)}>
        <div className="memory-row-meta"><time>{item.date}</time><ArrowUpRight size={15} /></div><strong>{item.activity}</strong><p>{item.text}</p><span className="source-label">模拟日程记录</span>
      </VButton>)}</div><p className="sample-caption">示例引用已有摘要。记录有多长，就展示多长。</p>
    </>}</div></>;
}

export default function App() {
  const [narrow, setNarrow] = useState(() => window.innerWidth <= 1000);
  const [personOpen, setPersonOpen] = useState(() => window.innerWidth > 1000), [lifeOpen, setLifeOpen] = useState(false), [tab, setTab] = useState("now");
  const [selected, setSelected] = useState<Moment | null>(null), [info, setInfo] = useState<"settings" | "actions" | null>(null);
  const [message, setMessage] = useState(""), [messages, setMessages] = useState(initialMessages), [contact, setContact] = useState("quiet"), [notice, setNotice] = useState("");
  const memoryReturnFocus = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const query = window.matchMedia("(max-width:1000px)");
    const update = () => { setNarrow(query.matches); setPersonOpen(!query.matches); setLifeOpen(false); };
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  const togglePerson = () => { setPersonOpen(!personOpen); if (narrow) setLifeOpen(false); };
  const toggleLife = () => { setLifeOpen(!lifeOpen); if (narrow) setPersonOpen(false); };
  const portrait = <div className="person-stage"><div className="stage-caption"><span><MapPin size={14} /> 在家 · 自由活动</span><span>心情愉快</span></div><CompanionPortrait companion={person} className="preview-portrait" /></div>;
  const send = () => { if (!message.trim()) return; setMessages(current => [...current, { role: "user", text: message.trim(), time: "刚刚" }]); setMessage(""); setNotice("消息仅保留在当前预览中，没有发送给人物。"); };
  const chat = <VSurface className="chat-pane" tone="panel"><div className="conversation-scroll" ref={el => { if (el) el.scrollTop = el.scrollHeight; }}><div className="conversation-inner"><div className="day-label">10月11日 · 示例对话</div>
    {messages.map((item, index) => <article className={`chat-message ${item.role}`} key={index}>{item.role === "person" ? <CompanionPortrait companion={person} compact /> : null}<div className="message-body">{item.time ? <div className="message-byline">{item.role === "person" ? "洛天依" : "你"}<time>{item.time}</time></div> : null}<p>{item.text}</p></div></article>)}
    </div></div><div className="composer-area"><div className="composer"><VTextarea aria-label="预览消息输入" placeholder="和天依聊聊…" value={message} onChange={e => setMessage(e.target.value)} /><VIconButton label="发送预览消息" variant="primary" isDisabled={!message.trim()} icon={<Send size={18} />} onPress={send} /></div><p className="composer-caption" role="status">{notice || "界面预览 · 输入内容不会发送给人物"}</p></div></VSurface>;
  const life = <LifeContent tab={tab} setTab={setTab} onSelect={item => { memoryReturnFocus.current = document.activeElement as HTMLElement; setSelected(item); }} />;
  const leftVisible = !narrow && personOpen, rightVisible = !narrow && lifeOpen;
  return <VuiProvider><div className="preview-app"><header className="workspace-header">
    <div className="header-person"><VIconButton label="返回人物大厅" variant="ghost" icon={<ArrowLeft size={18} />} onPress={() => setNotice("这里是返回人物大厅的入口；预览保持在当前页。")} /><div className="identity-copy"><h1>洛天依</h1><div className="identity-state"><span className="online-dot" />在线<span className="identity-separator">·</span><span>与你聊天</span></div></div><span className="preview-tag">预览</span></div>
    <div className="header-actions"><VIconButton label={personOpen ? "收起人物栏" : "展开人物栏"} variant="ghost" aria-pressed={personOpen} icon={personOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />} onPress={togglePerson} />
      <VPopover aria-label="主动联系偏好" align="end" trigger={<VIconButton label="主动联系偏好" variant="ghost" icon={<Bell size={18} />} />}><div className="contact-content"><h3>主动联系</h3><p>你希望她多久来找你聊聊？</p><VTabs aria-label="主动联系频率" value={contact} onValueChange={setContact} items={[{ id: "quiet", label: "安静" }, { id: "natural", label: "自然" }, { id: "active", label: "活跃" }]} /><small>仅预览选择效果，不保存到人物设置。</small></div></VPopover>
      <VButton className="life-toggle" variant={lifeOpen ? "secondary" : "ghost"} icon={<BookOpen size={17} />} aria-pressed={lifeOpen} onPress={toggleLife}>生活</VButton><VIconButton label="更多会话操作" variant="ghost" icon={<MoreHorizontal size={18} />} onPress={() => setInfo("actions")} /></div>
    </header><VSessionWorkbenchPage className={`preview-columns ${leftVisible ? "with-person" : ""} ${rightVisible ? "with-life" : ""}`} hostStyle={{ gridTemplateColumns: `${leftVisible ? "minmax(280px,30%) " : ""}minmax(0,1fr)${rightVisible ? " 320px" : ""}` }} indexRail={leftVisible ? <aside className="person-pane" aria-label="洛天依人物栏">{portrait}<VIconButton className="person-settings" label="人物设置" variant="ghost" icon={<Settings size={17} />} onPress={() => setInfo("settings")} /></aside> : null} session={chat} statusRail={rightVisible ? <aside className="life-pane" aria-label="洛天依的生活"><div className="life-heading"><h2>她的生活</h2><VIconButton label="关闭生活栏" variant="ghost" icon={<X size={17} />} onPress={() => setLifeOpen(false)} /></div>{life}</aside> : null} />
    <VDialog open={narrow && personOpen} onOpenChange={setPersonOpen} title="洛天依" className="portrait-dialog" description="在家 · 自由活动 · 心情愉快">{portrait}</VDialog>
    <VDialog open={narrow && lifeOpen} onOpenChange={setLifeOpen} title="她的生活" className="life-dialog" contentClassName="life-dialog-content">{life}</VDialog>
    <VDialog open={selected !== null} onOpenChange={open => !open && setSelected(null)} onCloseAutoFocus={event => { if (memoryReturnFocus.current?.isConnected) { event.preventDefault(); memoryReturnFocus.current.focus(); } }} title={selected?.activity || "生活记忆"} description={selected ? `${selected.date} · 模拟日程记录` : undefined} className="memory-dialog" footer={<VButton variant="secondary" onPress={() => setSelected(null)}>读完了</VButton>}>
      {selected ? <div className="record-detail"><div className="record-paper"><BookOpen size={20} /><p>{selected.text}</p></div><p className="record-note">这条记录只有以上一句摘要，没有更多正文。</p><div className="record-origin"><h3>记录来源</h3><dl><dt>来源</dt><dd>日程模拟完成</dd><dt>实际行动证据</dt><dd>没有工具执行记录或作品</dd></dl></div></div> : null}
    </VDialog><VDialog open={info !== null} onOpenChange={open => !open && setInfo(null)} title={info === "settings" ? "人物设置" : "会话操作"} description="这是独立界面预览，不会修改真实人物或聊天。">
      {info === "settings" ? <p className="settings-preview">人物档案、形象和生活偏好集中在这里。日常聊天页面保持简洁。</p> : <div className="actions-preview"><VButton variant="secondary" onPress={() => { setInfo(null); setNotice("预览中没有真实聊天可导出。"); }}>导出对话</VButton><VButton variant="ghost" icon={<Settings size={16} />} onPress={() => setInfo("settings")}>人物设置</VButton></div>}
    </VDialog></div></VuiProvider>;
}
