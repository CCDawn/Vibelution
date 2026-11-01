import { useId, useLayoutEffect, useRef, useState } from "react";
import { AlertCircle, ArrowRight, Users } from "lucide-react";

import { VButton, VChip } from "../vui";
import { MessageActor, MessageState } from "./AgentMessageParts";
import { deliveryLabel, handlingLabel, messageKind, messageSummary, messageText, messageTime } from "./agentMessagePresentation";
import type { AgentMessageLang, AgentMessageRecord } from "./types";
import styles from "./AgentMessages.styles";

export interface AgentMessageDetailProps {
  records: readonly AgentMessageRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  lang: AgentMessageLang;
}

export function AgentMessageDetail({ records, selectedId, onSelect, lang }: AgentMessageDetailProps) {
  const detailRef = useRef<HTMLElement>(null);
  const [expanded, setExpanded] = useState(false);
  const recordBodyId = useId();
  const selected = records.find((record) => record.id === selectedId);
  const linkedReplies = selected ? records.filter((record) => record.replyToId === selected.id) : [];
  const original = selected?.replyToId ? records.find((record) => record.id === selected.replyToId) : undefined;
  useLayoutEffect(() => {
    setExpanded(false);
    if (detailRef.current) detailRef.current.scrollTop = 0;
  }, [selectedId]);
  if (!selected) return <article className={styles.detail} data-testid="agent-message-detail"><div className={styles.empty}>{selectedId ? messageText(lang, "该消息尚未加载或已不可用", "This message is not loaded or is no longer available") : messageText(lang, "选择一条消息查看详情", "Select a message to view its details")}</div></article>;

  return <article ref={detailRef} className={styles.detail} data-testid="agent-message-detail" data-selected-message-id={selected.id}>
    <div className={styles.detailMeasure}>
      <header>
        <div className={styles.eyebrow}><VChip className={styles.kind}>{messageKind(selected, lang)}</VChip><span>{selected.type === "notification" ? messageText(lang, "收取后结束，无需回复", "Complete when collected; no reply needed") : selected.type === "reply" ? messageText(lang, "与原消息关联", "Linked to the original message") : messageText(lang, "需要回复", "Reply required")}</span></div>
        <h1 className={styles.detailTitle}>{selected.title || messageText(lang, "无标题消息", "Untitled message")}</h1>
        <div className={styles.detailIdentity}><MessageActor actor={selected.sender} /><ArrowRight size={16} className={styles.arrow} aria-hidden="true" />{selected.recipients.length === 1 ? <MessageActor actor={selected.recipients[0]} /> : <span className={styles.group}><Users size={18} aria-hidden="true" />{messageText(lang, `${selected.recipients.length} 位接收 Agent`, `${selected.recipients.length} recipients`)}</span>}<time dateTime={selected.createdAt}>{messageTime(selected.createdAt, lang)}</time></div>
      </header>
      {selected.replyToId ? original ? <VButton className={styles.link} onPress={() => onSelect(original.id)} trailingIcon={<ArrowRight size={13} aria-hidden="true" />}>{messageText(lang, "查看原消息", "View original message")}</VButton> : <p className={styles.subheading}>{messageText(lang, "原消息尚未加载或已不可用", "The original message is not loaded or is no longer available")}</p> : null}
      <section className={styles.body} aria-label={messageText(lang, "消息正文", "Message body")}>{selected.body || messageText(lang, "暂无正文", "No message body")}</section>
      <section aria-label={messageText(lang, "接收方状态", "Recipient status")}>
        <div className={styles.sectionHeading}><h2>{messageText(lang, "接收方状态", "Recipient status")}</h2><span>{messageSummary(selected, lang)}</span></div>
        <div className={styles.receiptHead} aria-hidden="true"><span>{messageText(lang, "接收 Agent", "Recipient")}</span><span>{messageText(lang, "投递", "Delivery")}</span><span>{messageText(lang, "处理", "Handling")}</span></div>
        {selected.recipients.map((receipt) => <div key={receipt.agentId} className={styles.receiptRow} data-recipient-id={receipt.agentId}>
          <MessageActor actor={receipt} />
          <MessageState label={deliveryLabel(receipt.delivery, lang)} state={receipt.delivery} danger={receipt.delivery === "failed"} />
          <MessageState label={handlingLabel(receipt.handling, lang)} state={receipt.handling} danger={receipt.handling === "wake_failed"} />
          {receipt.error ? <div className={styles.error} role="note"><AlertCircle size={14} aria-hidden="true" /><span>{receipt.error}</span></div> : null}
        </div>)}
        {selected.recipients.length === 0 ? <p className={styles.subheading}>{messageText(lang, "接收方与回执待确认", "Recipients and receipts are unconfirmed")}</p> : null}
      </section>
      {linkedReplies.length > 0 ? <section className={styles.replies} aria-label={messageText(lang, "关联回复", "Linked replies")}><h2>{messageText(lang, "关联回复", "Linked replies")}</h2>{linkedReplies.map((reply) => <div key={reply.id} className={styles.replyBody} data-reply-id={reply.id}>
        <MessageActor actor={reply.sender} /><p>{reply.body}</p><VButton className={styles.link} onPress={() => onSelect(reply.id)} trailingIcon={<ArrowRight size={13} aria-hidden="true" />}>{messageText(lang, "在左栏定位这条回复", "Locate this reply in the sidebar")}</VButton>
      </div>)}</section> : null}
      <section className={styles.records}>
        <VButton className={styles.link} aria-expanded={expanded} aria-controls={recordBodyId} onPress={() => setExpanded((value) => !value)}>{expanded ? messageText(lang, "收起状态明细", "Hide status details") : messageText(lang, "展开状态明细", "Show status details")}</VButton>
        {expanded ? <div id={recordBodyId} className={styles.recordBody}>
          <p>{messageText(lang, "消息记录", "Message record")} {selected.id} · {messageTime(selected.createdAt, lang)}</p>
          {selected.recipients.map((receipt) => <p key={receipt.agentId}>{receipt.name || receipt.agentId}：{deliveryLabel(receipt.delivery, lang)} · {handlingLabel(receipt.handling, lang)}</p>)}
          <p>{messageText(lang, "“已收取”表示目标会话已取用消息；不表示已读。投递、收取与处理分别依据各自回执。", "Collected means the target session took the message; it is not a read receipt. Delivery, collection and handling each use their own receipt.")}</p>
        </div> : null}
      </section>
    </div>
  </article>;
}
