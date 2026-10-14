import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, Bell, BookOpen, Clock3, MapPin, MoreHorizontal, Send, Settings } from "lucide-react";
import { VButton, VIconButton, VSurface, VTabs, VDialog, VPopover, VTextarea, VSessionWorkbenchPage, VuiProvider } from "../../src/components/vui";
import { CompanionPortrait } from "../../src/routes/companions/CompanionPortrait";
import type { VirtualHumanCompanion } from "../../src/api/types";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "./preview.css";

const asset = (name: string) => new URL(`./${name}`, import.meta.url).href;
const scenes = [
  { id: "home", place: "在家", activity: "自由活动", time: "19:30", mood: "放松", background: asset("room-background-v1.png"), words: ["回到家啦，想慢慢整理一下今天的想法。", "你今天过得怎么样？可以跟我说说。"] },
  { id: "study", place: "图书馆", activity: "复习功课", time: "12:00", mood: "专注", background: asset("library-background-v1.png"), words: ["我在图书馆，正把今天要复习的内容理一理。", "这边很安静。你要不要也找点自己的事情，我们一起专心一会儿？"] },
  { id: "create", place: "创作工作室", activity: "音乐创作", time: "15:00", mood: "有灵感", background: asset("studio-background-v1.png"), words: ["现在在工作室，想试试把刚才想到的旋律记下来。", "还只是一个小想法。等整理好了，再慢慢跟你分享。"] },
  { id: "walk", place: "公园", activity: "傍晚散步", time: "18:00", mood: "愉快", background: asset("park-background-v1.png"), words: ["出来走走啦，公园的晚风很舒服。", "天快暗下来了，路灯也亮了。你今天有没有遇到什么想分享的事？"] },
];
type Scene = typeof scenes[number];
const person = { agentId: "preview-companion", displayName: "洛天依", avatarImageUrl: asset("portrait-cutout-v1.png"), snapshot: { state: { lifePaused: false }, causal: { embodiment: { expressionId: "neutral", motionPreset: "still", sceneKey: "home-day" } } } } as unknown as VirtualHumanCompanion;
const moments = [
  { id: "a", date: "10月13日 21:00", activity: "复习和个人创作", text: "完成了复习和个人创作。" },
  { id: "b", date: "10月13日 12:00", activity: "学习与创作", text: "完成了专注处理自己的学习与创作。" },
];
type Moment = typeof moments[number];
type Message = { role: "person" | "user"; text: string; time?: string };
const sceneMessages = (scene: Scene): Message[] => scene.words.map((text, index) => ({ role: "person", text, time: index === 0 ? scene.time : undefined }));

function LifeContent({ scene, setScene, tab, setTab, onSelect }: { scene: Scene; setScene: (scene: Scene) => void; tab: string; setTab: (tab: string) => void; onSelect: (item: Moment) => void }) {
  const plan = [scenes[1], scenes[2], scenes[3], scenes[0]];
  const next = plan[plan.findIndex(item => item.id === scene.id) + 1];
  return <><VTabs aria-label="生活内容" value={tab} onValueChange={setTab} items={[{ id: "now", label: "现在" }, { id: "plan", label: "计划" }, { id: "memory", label: "记忆" }]} />
    <div className="life-content">{tab === "now" ? <>
      <div className="section-label">此刻 · 场景示例</div><h3 className="life-headline">{scene.activity}</h3><p>{scene.place} · {scene.time} · 心情{scene.mood}</p>
      {next ? <div className="next-moment"><Clock3 size={16} /><div><small>下一项计划 · {next.time}</small><strong>{next.activity}</strong><p>{next.place}</p></div></div> : <p>今天的安排已经结束，留一点自己的时间。</p>}
      <p className="sample-caption">背景、地点和活动来自同一个场景示例。</p>
    </> : tab === "plan" ? <>
      <div className="section-label">一天的安排 · 示例</div><div className="plan-list">{plan.map(item => <VButton key={item.id} contentLayout="plain" variant="ghost" className="plan-row" aria-pressed={item.id === scene.id} onPress={() => setScene(item)}><time>{item.time}</time><div><strong>{item.activity}</strong><p>{item.place}</p></div><span>{item.id === scene.id ? "当前" : "查看"}</span></VButton>)}</div>
      <p className="sample-caption">点击安排预览对应场景；不修改真实计划，也不执行定时行动。</p>
    </> : <>
      <div className="memory-intro"><h3>生活记忆</h3><p>读一段记录，看看它从哪里来。</p></div><div className="memory-list">{moments.map(item => <VButton contentLayout="plain" variant="ghost" className="memory-row" key={item.id} onPress={() => onSelect(item)}><div className="memory-row-meta"><time>{item.date}</time><ArrowUpRight size={15} /></div><strong>{item.activity}</strong><p>{item.text}</p><span className="source-label">模拟日程记录</span></VButton>)}</div><p className="sample-caption">示例引用已有摘要。记录有多长，就展示多长。</p>
    </>}</div></>;
}

export default function App() {
  const [scene, setScene] = useState(scenes[0]), [sceneMenu, setSceneMenu] = useState(false);
  const [lifeOpen, setLifeOpen] = useState(false), [tab, setTab] = useState("now");
  const [selected, setSelected] = useState<Moment | null>(null), [info, setInfo] = useState<"settings" | "actions" | "contact" | null>(null);
  const [message, setMessage] = useState(""), [messages, setMessages] = useState(() => sceneMessages(scenes[0])), [contact, setContact] = useState("quiet"), [notice, setNotice] = useState("");
  const memoryReturnFocus = useRef<HTMLElement | null>(null);
  const historyRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => { setMessages(sceneMessages(scene)); setMessage(""); setNotice(""); }, [scene]);
  useEffect(() => { const el = historyRef.current; if (el) el.scrollTop = el.scrollHeight; }, [messages]);
  const send = () => { if (!message.trim()) return; setMessages(current => [...current, { role: "user", text: message.trim(), time: "刚刚" }]); setMessage(""); setNotice("消息仅保留在预览中，没有发送给人物。"); };
  const chat = <VSurface className="chat-pane" tone="panel"><div className="conversation-scroll" ref={historyRef}><div className="conversation-inner">
    {messages.map((item, index) => <article className={`chat-message ${item.role}`} key={index}>{item.role === "person" ? <CompanionPortrait companion={person} compact /> : null}<div className="message-body">{item.time ? <div className="message-byline">{item.role === "person" ? "洛天依" : "你"}<time>{item.time}</time></div> : null}<p>{item.text}</p></div></article>)}
    </div></div><div className="composer-area"><div className="composer"><VTextarea aria-label="预览消息输入" placeholder="和天依聊聊…" value={message} onChange={e => setMessage(e.target.value)} /><VIconButton label="发送预览消息" variant="primary" isDisabled={!message.trim()} icon={<Send size={18} />} onPress={send} /></div><p className="composer-caption" role="status">{notice || "场景与对话为示例 · 输入内容不会发送"}</p></div></VSurface>;
  return <VuiProvider><div className="preview-app" data-scene={scene.id}>
    <div className="scene-backdrop" aria-hidden="true">{scenes.map(item => <img key={item.id} src={item.background} alt="" data-active={item.id === scene.id} />)}</div>
    <CompanionPortrait companion={person} className="scene-portrait" />
    <header className="workspace-header"><div className="header-person"><VIconButton label="返回人物大厅" variant="ghost" icon={<ArrowLeft size={18} />} onPress={() => setNotice("预览中的返回入口。")} /><div className="identity-copy"><h1>洛天依</h1><div className="identity-state"><span className="online-dot" />在线<span className="identity-separator">·</span><span>{scene.activity}</span></div></div></div>
      <div className="header-actions"><VPopover aria-label="场景示例" open={sceneMenu} onOpenChange={setSceneMenu} align="end" trigger={<VButton className="scene-switch" variant="ghost" icon={<MapPin size={16} />} aria-label="切换场景">{scene.place}<span className="scene-time">{scene.time}</span></VButton>}><div className="scene-options"><h3>场景示例</h3>{scenes.map(item => <VButton key={item.id} contentLayout="plain" variant="ghost" aria-pressed={item.id === scene.id} onPress={() => { setScene(item); setSceneMenu(false); }}><span>{item.place} · {item.activity}</span><time>{item.time}</time></VButton>)}<small>切换时，地点、活动和画面一起变化。</small></div></VPopover>
        <VPopover aria-label="主动联系偏好" align="end" trigger={<VIconButton label="主动联系偏好" variant="ghost" icon={<Bell size={18} />} />}><div className="contact-content"><h3>主动联系</h3><p>你希望她多久来找你聊聊？</p><VTabs aria-label="主动联系频率" value={contact} onValueChange={setContact} items={[{ id: "quiet", label: "安静" }, { id: "natural", label: "自然" }, { id: "active", label: "活跃" }]} /><small>仅预览选择效果。</small></div></VPopover>
        <VButton className="life-toggle" variant="ghost" icon={<BookOpen size={17} />} onPress={() => setLifeOpen(true)}>生活</VButton><VIconButton label="更多会话操作" variant="ghost" icon={<MoreHorizontal size={18} />} onPress={() => setInfo("actions")} /></div>
    </header><VSessionWorkbenchPage className="vn-workspace" session={chat} />
    <VDialog open={lifeOpen} onOpenChange={setLifeOpen} title="她的生活" description={`${scene.place} · ${scene.activity} · ${scene.time}`} className="life-dialog"><LifeContent scene={scene} setScene={setScene} tab={tab} setTab={setTab} onSelect={item => { memoryReturnFocus.current = document.activeElement as HTMLElement; setSelected(item); }} /></VDialog>
    <VDialog open={selected !== null} onOpenChange={open => !open && setSelected(null)} onCloseAutoFocus={event => { if (memoryReturnFocus.current?.isConnected) { event.preventDefault(); memoryReturnFocus.current.focus(); } }} title={selected?.activity || "生活记忆"} description={selected ? `${selected.date} · 模拟日程记录` : undefined} className="memory-dialog" footer={<VButton variant="secondary" onPress={() => setSelected(null)}>读完了</VButton>}>
      {selected ? <div className="record-detail"><div className="record-paper"><BookOpen size={20} /><p>{selected.text}</p></div><p className="record-note">这条记录只有以上一句摘要，没有更多正文。</p><div className="record-origin"><h3>记录来源</h3><dl><dt>来源</dt><dd>日程模拟完成</dd><dt>实际行动证据</dt><dd>没有工具执行记录或作品</dd></dl></div></div> : null}
    </VDialog><VDialog open={info !== null} onOpenChange={open => !open && setInfo(null)} title={info === "settings" ? "人物设置" : info === "contact" ? "主动联系" : "会话操作"} description="独立界面预览，不会修改真实人物或聊天。">
      {info === "settings" ? <p className="settings-preview">人物档案、形象和生活偏好集中在这里。</p> : info === "contact" ? <VTabs aria-label="主动联系频率" value={contact} onValueChange={setContact} items={[{id:"quiet",label:"安静"},{id:"natural",label:"自然"},{id:"active",label:"活跃"}]} /> : <div className="actions-preview"><VButton variant="secondary" onPress={() => { setInfo(null); setNotice("预览中没有真实聊天可导出。"); }}>导出对话</VButton><VButton variant="ghost" icon={<Bell size={16} />} onPress={() => setInfo("contact")}>主动联系</VButton><VButton variant="ghost" icon={<Settings size={16} />} onPress={() => setInfo("settings")}>人物设置</VButton></div>}
    </VDialog></div></VuiProvider>;
}
