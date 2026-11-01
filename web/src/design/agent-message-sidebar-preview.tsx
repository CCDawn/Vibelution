/** Isolated interaction design. All identities, messages and receipts are synthetic. */
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { AlertCircle, ArrowRight, CheckCheck, Clock3, LoaderCircle, Reply, Send, Users } from "lucide-react";

import { VButton, VChip, VInput, VListDetailPage, VuiProvider } from "../components/vui";
import { ConversationTurnAvatarContent } from "../components/conversation/ConversationTurnAvatarContent";
import styles from "./agent-message-sidebar-preview.module.css";
import "./tokens.css";
import "./base.css";
import "./tailwind.css";
import "./vui-provider-theme.css";
import "./vui-native-controls.css";

type AgentId = "assistant" | "reviewer" | "tester" | "researcher";
type Delivery = "sending" | "delivered" | "failed" | "unknown";
type Handling = "waiting" | "queued" | "processing" | "received" | "replied" | "wake_failed";
type Receipt = { agentId: AgentId; delivery: Delivery; handling: Handling; error?: string; reply?: string };
type Message = { id: string; senderId: AgentId; type: "request" | "notification"; time: string; title: string; body: string; recipients: Receipt[]; replyTo?: string };
type Filter = "all" | "pending" | "replied" | "exception";

const agents: Record<AgentId, { name: string; initials: string; team: string }> = {
  assistant: { name: "个人助理", initials: "助", team: "协调" },
  reviewer: { name: "代码审查员", initials: "审", team: "开发团队" },
  tester: { name: "测试工程师", initials: "测", team: "质量团队" },
  researcher: { name: "资料研究员", initials: "研", team: "研究团队" },
};
const initialMessages: Message[] = [
  { id: "m1", senderId: "assistant", type: "request", time: "15:28", title: "核对消息左栏和状态展示", body: "请核对这次跨 Agent 消息的左栏展示。重点检查：每次发送都保留独立记录，头像和姓名能区分收发双方，处理状态与投递状态分别显示。完成后请回复检查结果。", recipients: [{ agentId: "reviewer", delivery: "delivered", handling: "processing" }] },
  { id: "m2", senderId: "assistant", type: "notification", time: "15:24", title: "新的构建资源已经准备就绪", body: "本轮构建资源已准备就绪，后续验证请使用新版本。此消息仅作同步，确认接收后即可结束，无需回复。", recipients: [{ agentId: "tester", delivery: "delivered", handling: "received" }] },
  { id: "m3", senderId: "assistant", type: "request", time: "15:21", title: "分别检查交互、回归与参考资料", body: "请代码审查员核对交互逻辑，测试工程师检查消息状态回归，资料研究员补充参考资料。每位 Agent 的结果分别记录，不用等待其他人一起完成。", recipients: [
    { agentId: "reviewer", delivery: "delivered", handling: "replied", reply: "交互逻辑已核对：每条发送记录独立显示，原消息与回复通过关联记录连接。" },
    { agentId: "tester", delivery: "delivered", handling: "processing" },
    { agentId: "researcher", delivery: "failed", handling: "waiting", error: "目标 Agent 当前不可用，消息尚未写入其收件箱。" },
  ] },
  { id: "m4", senderId: "assistant", type: "request", time: "15:18", title: "检查历史消息和关联回复", body: "请检查历史消息的身份和回复关系，确认重新打开后仍能定位到原消息。", recipients: [{ agentId: "reviewer", delivery: "delivered", handling: "replied", reply: "已核对。原消息和回复身份独立，回复保留与原消息的关联，可以分别定位。" }] },
  { id: "m5", senderId: "assistant", type: "request", time: "15:14", title: "补充窄屏下的回归检查", body: "请补充窄屏情况下的列表、详情与长文本检查。", recipients: [{ agentId: "tester", delivery: "delivered", handling: "wake_failed", error: "消息已经送达，但目标会话启动失败。可以重试唤醒，无需重复发送消息。" }] },
  { id: "m6", senderId: "assistant", type: "notification", time: "15:10", title: "参考资料已更新", body: "参考资料已更新到项目资料库，请在下一次研究时使用。", recipients: [{ agentId: "researcher", delivery: "delivered", handling: "waiting" }] },
  { id: "m7", senderId: "assistant", type: "request", time: "15:06", title: "核对每个接收方的状态回执", body: "请核对多接收方消息的投递与处理回执，不要将部分成功显示成全部成功。", recipients: [{ agentId: "tester", delivery: "delivered", handling: "queued" }] },
  { id: "m8", senderId: "reviewer", type: "request", time: "15:02", title: "消息状态核对结果", body: "已经完成消息状态核对。投递成功与处理完成分别展示，失败原因能在对应接收方下查看。", recipients: [{ agentId: "assistant", delivery: "delivered", handling: "received" }], replyTo: "m4" },
  { id: "m9", senderId: "assistant", type: "request", time: "14:58", title: "确认长时间未收到回执的消息", body: "请确认这条消息是否已被接收。当前没有足够的回执，保留待确认，不直接判为失败。", recipients: [{ agentId: "researcher", delivery: "unknown", handling: "waiting" }] },
];
const deliveryLabels: Record<Delivery, string> = { sending: "发送中", delivered: "已送达", failed: "投递失败", unknown: "待确认" };
const handlingLabels: Record<Handling, string> = { waiting: "待接收", queued: "排队中", processing: "处理中", received: "已接收", replied: "已回复", wake_failed: "唤醒失败" };
const filters: Array<{ id: Filter; label: string }> = [{ id: "all", label: "全部" }, { id: "pending", label: "待处理" }, { id: "replied", label: "已回复" }, { id: "exception", label: "异常" }];

function hasFailure(message: Message) {
  return message.recipients.some((r) => r.delivery === "failed" || r.handling === "wake_failed");
}
function isException(message: Message) {
  return hasFailure(message) || message.recipients.some((r) => r.delivery === "unknown");
}
function summary(message: Message) {
  const delivered = message.recipients.filter((r) => r.delivery === "delivered").length;
  const replied = message.recipients.filter((r) => r.handling === "replied").length;
  if (message.recipients.length > 1) return `${delivered}/${message.recipients.length} 已送达 · ${replied}/${message.recipients.length} 已回复`;
  const r = message.recipients[0];
  if (r.delivery !== "delivered") return deliveryLabels[r.delivery];
  if (message.type === "notification" && r.handling === "received") return "已接收";
  return `${deliveryLabels[r.delivery]} · ${handlingLabels[r.handling]}`;
}
function Actor({ id, compact = false }: { id: AgentId; compact?: boolean }) {
  const agent = agents[id];
  return <span className={compact ? styles.actorCompact : styles.actor} title={`${agent.name} · ${agent.team}`}>
    <span className={styles.avatar} data-agent={id} aria-hidden="true"><ConversationTurnAvatarContent content={{ fallback: agent.initials }} /></span>
    <span className={styles.actorName}>{agent.name}</span>
  </span>;
}
function State({ value, danger = false }: { value: string; danger?: boolean }) {
  const Icon = danger ? AlertCircle : value === "处理中" || value === "发送中" ? LoaderCircle : value === "已回复" ? Reply : value === "已送达" || value === "已接收" ? CheckCheck : Clock3;
  return <span className={styles.state} data-tone={danger ? "danger" : value === "处理中" || value === "发送中" ? "active" : "neutral"}>
    <Icon size={13} className={Icon === LoaderCircle ? styles.spinner : undefined} aria-hidden="true" />{value}
  </span>;
}

function Preview() {
  const [messages, setMessages] = useState(initialMessages);
  const [selectedId, setSelectedId] = useState("m1");
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [view, setView] = useState("当前对话");
  const [dark, setDark] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const selected = messages.find((m) => m.id === selectedId) ?? messages[0];
  const visible = messages.filter((m) => {
    const text = [m.title, m.body, agents[m.senderId].name, ...m.recipients.map((r) => agents[r.agentId].name)].join(" ");
    if (query && !text.includes(query)) return false;
    if (filter === "exception") return isException(m);
    if (filter === "replied") return m.recipients.every((r) => r.handling === "replied");
    if (filter === "pending") return m.recipients.some((r) => r.delivery === "sending" || (r.delivery === "delivered" && ["waiting", "queued", "processing"].includes(r.handling)));
    return true;
  });
  const choose = (id: string) => { setSelectedId(id); setExpanded(false); };
  function simulateSend() {
    const id = `demo-${messages.length + 1}`;
    setMessages((current) => [{ id, senderId: "assistant", type: "request", time: "15:32", title: "新增的消息已出现在左栏", body: "这条示例用于确认每次发送都会新增一条独立记录。当前选中的消息保持不变。", recipients: [{ agentId: "tester", delivery: "sending", handling: "waiting" }] }, ...current]);
    setFilter("all"); setQuery(""); setAnnouncement("新消息已加入左栏，当前查看内容保持不变。");
  }
  function simulateProgress() {
    setMessages((current) => current.map((m): Message => m.id !== selectedId ? m : {
      ...m, recipients: m.recipients.map((r): Receipt => r.delivery === "failed" || r.handling === "wake_failed"
        ? { ...r, delivery: "delivered", handling: "queued", error: undefined }
        : r.delivery !== "delivered" ? { ...r, delivery: "delivered" }
        : r.handling === "waiting" ? { ...r, handling: m.type === "notification" ? "received" : "queued" }
        : r.handling === "queued" ? { ...r, handling: "processing" }
        : r.handling === "processing" ? { ...r, handling: "replied", reply: "已完成这条协作请求，检查结果已回复。" } : r),
    }));
    setAnnouncement("示例回执已更新，左栏和详情同步变化。");
  }
  function retryRecipient(agentId: AgentId) {
    setMessages((current) => current.map((m): Message => m.id !== selectedId ? m : {
      ...m, recipients: m.recipients.map((r): Receipt => r.agentId === agentId
        ? { ...r, delivery: "delivered", handling: "queued", error: undefined } : r),
    }));
    setAnnouncement(`${agents[agentId].name} 的示例重试已记录，其他接收方状态保持不变。`);
  }
  const list = <div className={styles.sidebar}>
    <header className={styles.listHeader}><div><h2>已发送消息 <span data-testid="message-count">{messages.length}</span></h2><p>每条发送独立记录</p></div><Send size={18} aria-hidden="true" /></header>
    <div className={styles.search}><VInput aria-label="搜索消息或 Agent" placeholder="搜索消息或 Agent" value={query} onChange={(event) => setQuery(event.target.value)} /></div>
    <div className={styles.filters} aria-label="消息状态筛选">{filters.map((item) => <VButton key={item.id} className={styles.filter} aria-pressed={filter === item.id} onPress={() => setFilter(item.id)}>{item.label}</VButton>)}</div>
    <nav className={styles.messageList} aria-label="已发送跨 Agent 消息" data-testid="sent-message-list">
      {visible.map((m) => <VButton key={m.id} contentLayout="plain" className={styles.messageRow} aria-pressed={selected.id === m.id} data-message-id={m.id} onPress={() => choose(m.id)}>
        <span className={styles.identityLine}><Actor id={m.senderId} compact /><ArrowRight size={12} className={styles.arrow} aria-hidden="true" />{m.recipients.length === 1 ? <Actor id={m.recipients[0].agentId} compact /> : <span className={styles.recipientGroup} title={m.recipients.map((r) => agents[r.agentId].name).join("、")}><span className={styles.avatarStack} aria-hidden="true">{m.recipients.slice(0, 2).map((r) => <span key={r.agentId} className={styles.avatar} data-agent={r.agentId}><ConversationTurnAvatarContent content={{ fallback: agents[r.agentId].initials }} /></span>)}</span><span>{agents[m.recipients[0].agentId].name}等 {m.recipients.length} 位</span></span>}</span>
        <span className={styles.messageTitle}>{m.title}</span>
        <span className={styles.rowMeta}><span>{m.replyTo ? "协作回复" : m.type === "notification" ? "通知" : "协作请求"}</span><time>{m.time}</time></span>
        <span className={styles.rowState} data-tone={hasFailure(m) ? "danger" : m.recipients.some((r) => r.handling === "processing" || r.delivery === "sending") ? "active" : "neutral"}>{summary(m)}</span>
      </VButton>)}
      {visible.length === 0 ? <div className={styles.empty}>没有匹配的消息<VButton onPress={() => { setFilter("all"); setQuery(""); }}>查看全部消息</VButton></div> : null}
    </nav>
    <footer className={styles.listFooter}>显示 {visible.length} / {messages.length} 条 · 最新发送在前</footer>
  </div>;
  const detail = <article className={styles.detail} data-testid="message-detail" data-selected-message-id={selected.id}>
    <div className={styles.detailMeasure}>
      <header className={styles.detailHeader}>
        <div className={styles.detailEyebrow}><VChip className={styles.kind}>{selected.replyTo ? "协作回复" : selected.type === "notification" ? "通知" : "协作请求"}</VChip><span>{selected.type === "notification" ? "确认接收后结束" : selected.replyTo ? "与原消息关联" : "需要回复"}</span></div>
        <h1>{selected.title}</h1><div className={styles.detailIdentity}><Actor id={selected.senderId} /><ArrowRight size={16} aria-hidden="true" />{selected.recipients.length === 1 ? <Actor id={selected.recipients[0].agentId} /> : <span className={styles.group}><Users size={18} aria-hidden="true" />{selected.recipients.length} 位接收 Agent</span>}<time>今天 {selected.time}</time></div>
      </header>
      {selected.replyTo ? <VButton className={styles.originLink} onPress={() => choose(selected.replyTo!)}>查看原消息 <ArrowRight size={13} /></VButton> : null}
      <section className={styles.body} aria-label="消息正文"><p>{selected.body}</p></section>
      <section className={styles.receipts} aria-label="接收方状态">
        <div className={styles.sectionHeading}><h2>接收方状态</h2><span>{summary(selected)}</span></div>
        <div className={styles.receiptHead}><span>接收 Agent</span><span>投递</span><span>处理</span></div>
        {selected.recipients.map((r) => <div key={r.agentId} className={styles.receiptRow} data-recipient-id={r.agentId}>
          <div className={styles.agentCell}><Actor id={r.agentId} /><span className={styles.team}>{agents[r.agentId].team}</span></div>
          <State value={deliveryLabels[r.delivery]} danger={r.delivery === "failed"} />
          <State value={r.delivery === "failed" || r.delivery === "sending" || r.delivery === "unknown" ? "—" : handlingLabels[r.handling]} danger={r.handling === "wake_failed"} />
          {r.error ? <div className={styles.error}><AlertCircle size={14} aria-hidden="true" /><span>{r.error}</span><VButton onPress={() => retryRecipient(r.agentId)}>{r.handling === "wake_failed" ? "重试唤醒" : "重试投递"}</VButton></div> : null}
        </div>)}
      </section>
      {selected.recipients.some((r) => r.reply) ? <section className={styles.replies} aria-label="关联回复"><h2>关联回复</h2>{selected.recipients.filter((r) => r.reply).map((r) => <div className={styles.replyBody} key={r.agentId}><Actor id={r.agentId} /><p>{r.reply}</p></div>)}</section> : null}
      <section className={styles.records}><VButton aria-expanded={expanded} onPress={() => setExpanded((value) => !value)}>{expanded ? "收起状态明细" : "展开状态明细"}</VButton>{expanded ? <div className={styles.recordBody}>
        <p>消息记录 {selected.id} · 今天 {selected.time}</p>
        {selected.recipients.map((r) => <p key={r.agentId}>{agents[r.agentId].name}：{deliveryLabels[r.delivery]}{r.delivery === "delivered" ? ` · ${handlingLabels[r.handling]}` : ""}</p>)}
        <p>“已接收”表示消息已被目标会话取用；不会用它代替阅读回执。</p>
      </div> : null}</section>
    </div>
  </article>;
  return <div className={styles.preview}>
    <header className={styles.previewBar}><span>隔离设计预览 · 示例数据</span><div><VButton onPress={simulateSend}>模拟发送一条</VButton><VButton onPress={simulateProgress}>模拟回执更新</VButton><VButton onPress={() => { document.documentElement.dataset.theme = dark ? "light" : "dark"; setDark(!dark); }}>{dark ? "浅色" : "深色"}</VButton></div></header>
    <VListDetailPage title="跨 Agent 消息" meta="已发送记录" className={styles.page} workspaceClassName={styles.workspace} columnsClassName="" actions={<div className={styles.viewSwitch}>{["当前对话", "消息中心"].map((label) => <VButton key={label} aria-pressed={view === label} onPress={() => setView(label)}>{label}</VButton>)}</div>} list={list} detail={detail} />
    <div className={styles.announcement} role="status" aria-live="polite">{announcement || "当前对话与消息中心共用这份记录。"}</div>
  </div>;
}

document.documentElement.dataset.theme = "light";
createRoot(document.getElementById("root")!).render(<VuiProvider><Preview /></VuiProvider>);
