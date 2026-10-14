import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowUpRight, BookOpen, Clock3, Image, MapPin, Send, X } from "lucide-react";
import { VButton, VIconButton, VPopover, VSessionWorkbenchPage, VSurface, VTabs, VTextarea, VuiProvider } from "../../src/components/vui";
import "../../src/design/tokens.css";
import "../../src/design/base.css";
import "../../src/design/vui-provider-theme.css";
import "../../src/design/vui-native-controls.css";
import "./preview.css";

const assets: Record<string, string> = {
  "room-background-v1.png": new URL("../companion-ui-alignment/room-background-v1.png", import.meta.url).href,
  "library-background-v1.png": new URL("../companion-ui-alignment/library-background-v1.png", import.meta.url).href,
  "studio-background-v1.png": new URL("../companion-ui-alignment/studio-background-v1.png", import.meta.url).href,
  "park-background-v1.png": new URL("../companion-ui-alignment/park-background-v1.png", import.meta.url).href,
  "portrait-cutout-v1.png": new URL("../companion-ui-alignment/portrait-cutout-v1.png", import.meta.url).href,
};
const asset = (name: string) => assets[name];
const scenes = [
  { id: "home", place: "在家 · 书桌边", time: "19:30", activity: "整理今天的旋律想法", status: "正在进行", image: "room-background-v1.png", now: "示例中的她把纸上的两种结尾摆在一起，先留下比较轻的一版。整理还在继续，不能当作已经完成的作品。", nextTime: "20:10", nextPlace: "家里的书桌", next: "给四小节草稿写一句备注，再收起笔记本。", words: "今晚先慢慢整理这几小节。还有一个结尾拿不定主意。" },
  { id: "study", place: "图书馆 · 靠窗座位", time: "12:00", activity: "读一段配器笔记", status: "正在进行", image: "library-background-v1.png", now: "示例中的她读到弦乐和人声交接的地方，停下来圈了两个问题。阅读和整理都还在进行，暂时没有完成记录。", nextTime: "12:40", nextPlace: "图书馆靠窗座位", next: "把两个问题写进笔记，下午在工作室试一试。", words: "刚读到一个有意思的段落，想先把它看懂，再试着用进旋律里。" },
  { id: "create", place: "创作工作室 · 键盘前", time: "15:00", activity: "试写四小节旋律", status: "正在进行", image: "studio-background-v1.png", now: "示例中的她把第三小节的停顿拉长了一拍，再试一个更轻的尾音。这里只展示创作过程，草稿尚未完成。", nextTime: "15:40", nextPlace: "创作工作室", next: "回听这四小节，对比两种结尾，只留下值得继续的想法。", words: "第三小节留一点空白，好像更自然。先试试，还不急着定下来。" },
  { id: "walk", place: "公园 · 入口长椅", time: "17:50", activity: "沿湖散步", status: "计划中", image: "park-background-v1.png", now: "示例中的她在公园入口歇一会儿，准备沿湖走一段。散步尚未开始；画面里的公园不代表她已经走完了这条路。", nextTime: "18:00", nextPlace: "公园环湖步道", next: "沿湖慢慢走到小桥，留十分钟听一听周围的声音。", words: "先在入口坐一会儿。等会儿想沿着湖走到那座小桥。" },
] as const;
type Scene = typeof scenes[number];
const records = [
  {
    id: "dialogue", source: "原生对话记录示例", title: "聊到那段还没写完的旋律", date: "示例时间 · 10月13日 19:40",
    excerpt: "“结尾先别急着收住，留一点空白也很好。”",
    paragraphs: ["以下是虚构的对话正文，用来演示如何阅读一段原生对话记录。预览没有连接真实 Session，也没有读取人物的聊天历史。", "你：如果结尾先不落下来，会不会更像还在继续？", "天依：我也在想这个。刚才试了一下，最后一拍停住以后，前面那句反而更清楚了。", "你：可以先留着，明天再听。", "天依：好，今晚只记下两个版本。明天如果还是喜欢这个停顿，再慢慢往下写。", "这段设计示例只呈现一次讨论。讨论一个想法，并不证明已经完成或保存了作品。"],
    origin: "虚构的原生对话摘录；仅展示正文与来源的阅读方式。",
  },
  {
    id: "tool", source: "工具回执示例", title: "四小节草稿与两种结尾", date: "示例时间 · 10月13日 20:05",
    excerpt: "作品入口示例：一段短草稿，旁边留下了修改理由。",
    paragraphs: ["这是一份作品与工具回执的设计示例。预览没有执行保存工具，没有创建音乐文件，也没有新增真实作品。", "草稿示例：第一小节保持原来的节奏；第二小节把尾音缩短；第三小节留出一拍空白；第四小节保留两种结尾供比较。", "备注示例：较轻的结尾更像一次没有说完的对话，完整收束的结尾更适合单独成段。先保留两版，第二天再听。", "回执区域在真实界面中需要能追溯到原生 Session、回合、工具调用与成功回执。这里的链接和文字都只是展示位置，没有实际执行凭据。", "阅读这个示例不会下载文件、调用工具或更改人物的生活状态。"],
    origin: "虚构的作品正文和回执展示；没有实际文件或执行凭据。",
  },
  {
    id: "report", source: "人物自述示例", title: "为什么想留下这段空白", date: "示例时间 · 10月13日 20:15",
    excerpt: "“想让它慢一点，不必每次都赶着给出答案。”",
    paragraphs: ["以下是人物自述的设计示例，展示一种自然的记录语气，不是已验证的生活事实。", "想让这段旋律慢一点。今天试着少写几个音的时候，反而听到了前面没有注意的地方。", "如果明天再听觉得不合适，也可以改回来。不必每次都赶着给出答案，先让一个想法待一会儿。", "人物自述可以表达感受与想法，但不能单凭这段正文认定她完成了练习、保存了作品，或获得了新的能力。"],
    origin: "虚构的人物自述；不证明外部行动或作品产出。",
  },
  {
    id: "simulation", source: "旧模拟已隔离", title: "按日程推算的“学习完成”", date: "隔离记录 · 示例",
    excerpt: "这类旧摘要仅保留来源说明，不计入真实经历。",
    paragraphs: ["这条记录只用于展示旧模拟内容如何被隔离，没有导入任何真实历史数据。", "旧摘要示例：完成了复习和个人创作。", "这句话来自按日程或时间推算的模拟结果，没有对应的原生工具执行证据。时间经过不能证明事情发生。", "真实界面中，这类内容应独立标注来源，不能用于真实经历、记忆强化、技能成长或完成率。此预览只展示阅读状态。"],
    origin: "旧日程模拟展示样本；已隔离，不属于真实经历。",
  },
];
type RecordEntry = typeof records[number];

export default function App() {
  const [scene, setScene] = useState<Scene>(scenes[0]);
  const [sceneMenu, setSceneMenu] = useState(false);
  const [lifeOpen, setLifeOpen] = useState(true);
  const [tab, setTab] = useState("life");
  const [selected, setSelected] = useState<RecordEntry | null>(null);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");
  const lifeTrigger = useRef<HTMLButtonElement>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const returnFocusKey = useRef("");
  const panelScroll = useRef<HTMLDivElement>(null);

  function openRecord(record: RecordEntry) {
    returnFocus.current = document.activeElement as HTMLElement;
    returnFocusKey.current = returnFocus.current?.dataset.returnTo || "";
    setSelected(record);
  }
  function backToList() {
    setSelected(null);
    requestAnimationFrame(() => {
      const target = returnFocus.current?.isConnected
        ? returnFocus.current
        : document.querySelector<HTMLElement>(`[data-return-to="${returnFocusKey.current}"]`);
      target?.focus();
    });
  }
  function closeLife() {
    setSelected(null);
    setLifeOpen(false);
    lifeTrigger.current?.focus();
  }
  useEffect(() => {
    panelScroll.current?.scrollTo({ top: 0 });
    if (selected) detailHeading.current?.focus();
  }, [selected, tab]);
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape" || sceneMenu || !lifeOpen) return;
      event.preventDefault();
      if (selected) backToList();
      else closeLife();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [lifeOpen, sceneMenu, selected]);

  const panel = lifeOpen ? <VSurface as="aside" ariaLabel="天依的生活示例" tone="panel" padding="none" className="life-panel">
    <header className="panel-header"><div><span className="eyebrow">洛天依</span><h2>生活里的一点点</h2></div><VIconButton label="关闭生活面板" variant="ghost" icon={<X size={18} />} onPress={closeLife} /></header>
    <p className="sample-boundary">所有正文均为设计示例，不是真实经历。</p>
    {!selected ? <VTabs aria-label="生活与记忆" value={tab} onValueChange={setTab} items={[{ id: "life", label: "生活" }, { id: "memory", label: "记忆" }]} /> : <VButton className="detail-back" variant="ghost" icon={<ArrowLeft size={16} />} onPress={backToList}>返回{tab === "memory" ? "记忆" : "生活"}</VButton>}
    <div className="panel-scroll" ref={panelScroll}>
      {selected ? <article className="record-detail">
        <span className={`record-source ${selected.id === "simulation" ? "quarantined" : ""}`}>{selected.source}</span>
        <h3 ref={detailHeading} tabIndex={-1}>{selected.title}</h3><p className="record-time">{selected.date}</p>
        <div className="record-body">{selected.paragraphs.map((paragraph, index) => <p key={index}>{paragraph}</p>)}</div>
        <section className="origin-note"><h4>这段记录从哪里来</h4><p>{selected.origin}</p><p>未连接真实人物。这里没有实际对话、执行回执或作品可核验。</p></section>
      </article> : tab === "life" ? <>
        <section className="narrative-section"><div className="section-meta"><span>此刻</span><time>{scene.time} · 示例</time></div><h3>{scene.activity}</h3><p className="place-line"><MapPin size={14} />{scene.place}<span className="activity-status">{scene.status}</span></p><p>{scene.now}</p></section>
        <section className="narrative-section"><div className="section-meta"><span>最近留下</span><span>过程片段 · 设计示例</span></div><h3>一个停顿，两种结尾</h3><p>示例片段里，她先把第三小节拉长一拍，再删掉结尾多出的两个音。旁边的备注写着：“轻一点的版本更像在等下一句话。”</p><p>这里呈现的是记录的写法，没有新发生的经历或作品。</p><VButton variant="ghost" className="artifact-link" data-return-to="artifact" icon={<BookOpen size={16} />} trailingIcon={<ArrowUpRight size={15} />} onPress={() => openRecord(records[1])}>看看四小节草稿 · 作品示例</VButton></section>
        <section className="narrative-section"><div className="section-meta"><span>下一步</span><span>计划中 · 未发生</span></div><div className="next-plan"><Clock3 size={17} /><div><time>{scene.nextTime}</time><h3>{scene.next}</h3><p>{scene.nextPlace} · 示例安排</p></div></div><p className="ongoing-direction">慢慢写出自己的小作品<span>持续方向，没有完成百分比。</span></p></section>
      </> : <section className="memory-section"><h3>留下的文字，也有不同来处</h3><p className="memory-intro">点开一段，先读正文，再看来源。以下四条均为设计示例。</p><div className="record-list">{records.map(record => <VButton key={record.id} contentLayout="plain" variant="ghost" className="record-row" data-return-to={record.id} onPress={() => openRecord(record)}><span className={`record-source ${record.id === "simulation" ? "quarantined" : ""}`}>{record.source}</span><strong>{record.title}</strong><p>{record.excerpt}</p><span className="record-row-bottom"><time>{record.date}</time><ArrowUpRight size={15} /></span></VButton>)}</div></section>}
    </div>
    <footer className="panel-footer">{selected ? "Esc 返回上一层" : "Esc 关闭面板"} · 仅展示阅读与切换</footer>
  </VSurface> : null;

  const conversation = <VSurface tone="glass" padding="none" className="conversation-example" ariaLabel="对话界面示例">
    <div className="sample-conversation"><span className="eyebrow">对话正文示例 · 不是真实消息</span><p>{scene.words}</p></div>
    <div className="preview-composer"><VTextarea aria-label="预览输入，不发送消息" value={draft} onChange={event => setDraft(event.target.value)} rows={1} placeholder="试写一句，不会发送给人物…" /><VIconButton label="查看发送示例说明" icon={<Send size={17} />} onPress={() => setNotice("仅预览输入效果，没有发送消息或创建对话回合。")} /></div>
    <p className="composer-notice" role="status">{notice || "输入只留在此页面，未连接聊天。"}</p>
  </VSurface>;

  return <VuiProvider><div className="immersion-app" data-life-open={lifeOpen}>
    <div className="scene-background" aria-hidden="true"><img src={asset(scene.image)} alt="" /></div>
    <img className="scene-person" src={asset("portrait-cutout-v1.png")} alt="洛天依人物形象示例" />
    <header className="person-header"><div className="person-heading"><h1>洛天依</h1><p><MapPin size={13} />{scene.place} · {scene.time}</p></div><div className="header-controls">
      <VPopover open={sceneMenu} onOpenChange={setSceneMenu} aria-label="选择场景示例" align="end" trigger={<VIconButton label="切换场景示例" icon={<Image size={18} />} variant="ghost" />}><div className="scene-options"><h3>换一个场景示例</h3>{scenes.map(item => <VButton key={item.id} contentLayout="plain" variant="ghost" aria-pressed={scene.id === item.id} onPress={() => { setScene(item); setSceneMenu(false); }}><span>{item.place}</span><time>{item.time}</time></VButton>)}<p>地点、活动、下一步与画面一起切换。</p></div></VPopover>
      <VButton ref={lifeTrigger} variant="ghost" icon={<BookOpen size={17} />} aria-expanded={lifeOpen} onPress={() => { if (lifeOpen) closeLife(); else setLifeOpen(true); }}>生活</VButton>
    </div></header>
    <div className="preview-banner">界面示例 · 未连接真实人物</div>
    <VSessionWorkbenchPage ariaLabel="独立生活界面预览" className="immersion-workspace" session={conversation} statusRail={panel} />
  </div></VuiProvider>;
}
