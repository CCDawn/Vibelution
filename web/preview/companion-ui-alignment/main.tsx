import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { ArrowLeft, Bell, MoreHorizontal, PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen, Settings, Send, X } from "lucide-react";
import { VButton, VIconButton, VSurface, VTabs, VDialog, VTextarea, VSessionWorkbenchPage, VuiProvider } from "../../src/components/vui";
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
  { id: "b", date: "10月13日 12:00", activity: "专注处理自己的学习与创作", text: "完成了专注处理自己的学习与创作。" },
  { id: "c", date: "10月12日 22:15", activity: "整理明天的想法", text: "完成了整理明天的想法。" },
];

function App() {
  const [narrow, setNarrow] = useState(() => window.innerWidth <= 1000);
  const [left, setLeft] = useState(() => window.innerWidth > 1000), [right, setRight] = useState(() => window.innerWidth > 1000), [tab, setTab] = useState("memory");
  const [selected, setSelected] = useState<typeof moments[number] | null>(null), [message, setMessage] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const query = window.matchMedia("(max-width:1000px)");
    const update = () => { setNarrow(query.matches); setLeft(!query.matches); setRight(!query.matches); };
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  const toggleLeft = () => { setLeft(!left); if (narrow) setRight(false); };
  const toggleRight = () => { setRight(!right); if (narrow) setLeft(false); };
  const personPane = left ? <aside className="person-pane" aria-label="洛天依人物栏">
    <div className="person-tools">
      <VIconButton label="返回人物大厅" variant="ghost" icon={<ArrowLeft size={16}/>} onPress={() => setNotice("预览中的返回入口；不会打开真实人物大厅。")}/>
      <VIconButton label="人物设置" variant="ghost" icon={<Settings size={16}/>} onPress={() => setNotice("人物设置保留在这里；预览不会保存设置。")}/>
    </div>
    <header className="person-intro"><div className="person-name"><h1>洛天依</h1><span aria-label="心情愉快">☀️</span></div>
      <div className="person-state"><span className="online">在线</span><time>11:17</time></div>
      <p>自由活动 · 在家</p>
    </header>
    <CompanionPortrait companion={person} className="preview-portrait"/>
  </aside> : null;
  const chat = <VSurface className="chat-pane" tone="panel">
    <header className="chat-header"><VIconButton label={left ? "收起人物栏" : "展开人物栏"} variant="ghost" aria-pressed={left} icon={left ? <PanelLeftClose size={16}/> : <PanelLeftOpen size={16}/>} onPress={toggleLeft}/>
      <div className="chat-identity"><CompanionPortrait companion={person} compact/><strong>洛天依</strong></div>
      <VButton variant="ghost" density="compact" icon={<Bell size={14}/>} onPress={() => setNotice("主动联系：安静。预览没有真实消息或设置写入。")}>主动联系 · 安静</VButton>
      <VIconButton label="更多会话操作" variant="ghost" icon={<MoreHorizontal size={16}/>} onPress={() => setNotice("导出 HTML 收在会话操作里；预览不导出真实聊天。")}/>
      <VIconButton label={right ? "收起生活栏" : "展开生活栏"} variant="ghost" aria-pressed={right} icon={right ? <PanelRightClose size={16}/> : <PanelRightOpen size={16}/>} onPress={toggleRight}/>
    </header>
    <div className="chat-history"><article className="chat-message"><img src={person.avatarImageUrl} alt=""/><div><div className="message-byline">洛天依 <time>10/11 19:01</time></div><p>没事呀～就是刚散步回来，心情挺好的，想跟你分享一下。</p><p>今天傍晚外面的风挺舒服的，感觉整个人都放松了不少。你呢，今天过得怎么样？</p></div></article><p className="sample-note">示例对话，用于查看排版</p></div>
    <div className="composer"><VTextarea aria-label="预览消息输入" placeholder="和她聊聊…" value={message} onChange={e => setMessage(e.target.value)}/><VIconButton label="发送预览消息" variant="ghost" icon={<Send size={16}/>} onPress={() => { setNotice("这是界面预览，消息没有发送。"); setMessage(""); }}/></div>
  </VSurface>;
  const lifePane = right ? <aside className="life-pane" aria-label="洛天依的生活">
    <header className="life-header"><div className="life-title"><div><small>生活</small><h2>洛天依的生活</h2></div><VIconButton className="mobile-close" label="关闭生活栏" variant="ghost" icon={<X size={16}/>} onPress={() => setRight(false)}/></div>
      <VTabs aria-label="生活内容" value={tab} onValueChange={setTab} items={[{id:"now",label:"现在"},{id:"today",label:"今天"},{id:"memory",label:"记忆"}]}/>
    </header>
    <div className="life-content">{tab === "memory" ? <><div className="memory-heading"><h3>生活记录</h3><span>69 条</span></div><p className="memory-intro">记录按来源区分；模拟生活与真实行动分开标注。</p><div className="memory-list">{moments.map(item => <VButton contentLayout="plain" variant="ghost" className="memory-card" key={item.id} onPress={() => setSelected(item)}><div className="memory-card-meta"><span>模拟生活</span><time>{item.date}</time></div><strong>{item.activity}</strong><p>{item.text}</p><small>查看记录与来源 →</small></VButton>)}</div><VSurface className="preferences" tone="panel"><h3>陪伴偏好</h3><p>只显示你确认过的偏好，可随时更正或删除。</p><small>还没有已确认的陪伴偏好。</small></VSurface></> : tab === "now" ? <><VSurface className="plain-section" tone="panel"><small>此刻</small><h3>自由活动</h3><p>在家 · 心情愉快</p></VSurface><VSurface className="plain-section" tone="panel"><small>接下来</small><h3>傍晚散步</h3><p>18:00</p></VSurface></> : <VSurface className="plain-section" tone="panel"><h3>今天的安排</h3><p>12:00 · 学习与创作</p><p>18:00 · 傍晚散步</p></VSurface>}</div>
  </aside> : null;
  return <VuiProvider><div className={`preview-app ${left ? "person-open" : ""} ${right ? "life-open" : ""}`}>
    <div className="preview-topbar"><span>Vibelution · 人物对话</span><span className="preview-tag">布局预览</span></div>
    <VSessionWorkbenchPage className="preview-columns" hostStyle={{ gridTemplateColumns: `${left ? "300px " : ""}minmax(0,1fr)${right ? " 350px" : ""}` }} indexRail={personPane} session={chat} statusRail={lifePane}/>
    <div className="preview-footer" role="status">{notice || "仅预览布局与记忆展开方式；未连接写接口。"}</div>
    <VDialog open={selected !== null} onOpenChange={open => !open && setSelected(null)} title={selected?.activity || "生活记录"} className="memory-dialog" footer={<VButton variant="secondary" onPress={() => setSelected(null)}>关闭</VButton>}>
      {selected ? <div className="record-detail"><div className="record-source">模拟生活 · 日程记录 <time>{selected.date}</time></div><h3>已保存的正文</h3><p>{selected.text}</p><div className="record-note">这条记录只保存了以上一句摘要，没有更长的回忆正文。</div><h3>来源</h3><dl><dt>安排</dt><dd>{selected.activity}</dd><dt>记录方式</dt><dd>日程模拟完成</dd><dt>实际行动证据</dt><dd>没有工具执行记录或作品</dd></dl><p className="record-explain">原来的蓝条是规则算出的记忆权重，和内容长度、真实执行完成度无关。</p></div> : null}
    </VDialog>
  </div></VuiProvider>;
}
const root = createRoot(document.getElementById("root")!);
root.render(<App/>);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
