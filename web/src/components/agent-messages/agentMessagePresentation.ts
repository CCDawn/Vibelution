import type { AgentMessageLang, AgentMessageReceipt, AgentMessageRecord } from "./types";

export type AgentMessageFilter = "all" | "pending" | "replied" | "exception";
export const messageText = (lang: AgentMessageLang, zh: string, en: string) => lang === "zh" ? zh : en;

export function deliveryLabel(value: AgentMessageReceipt["delivery"], lang: AgentMessageLang): string {
  const labels = {
    unknown: ["待确认", "Unconfirmed"], sending: ["发送中", "Sending"],
    delivered: ["已送达", "Delivered"], failed: ["投递失败", "Delivery failed"],
    revoked: ["已撤回", "Revoked"],
  } as const;
  return labels[value][lang === "zh" ? 0 : 1];
}

export function handlingLabel(value: AgentMessageReceipt["handling"], lang: AgentMessageLang): string {
  const labels = {
    unknown: ["待确认", "Unconfirmed"], waiting: ["待收取", "Awaiting collection"],
    received: ["已收取", "Collected"], queued: ["排队中", "Queued"],
    processing: ["处理中", "Processing"], replied: ["已回复", "Replied"],
    wake_failed: ["唤醒失败", "Wake failed"],
  } as const;
  return labels[value][lang === "zh" ? 0 : 1];
}

export function messageKind(record: AgentMessageRecord, lang: AgentMessageLang): string {
  if (record.type === "reply") return messageText(lang, "协作回复", "Reply");
  return record.type === "notification"
    ? messageText(lang, "通知", "Notification")
    : messageText(lang, "协作请求", "Request");
}

export function messageHasException(record: AgentMessageRecord): boolean {
  return record.recipients.some((r) => r.delivery === "failed" || r.delivery === "revoked" || r.handling === "wake_failed" || Boolean(r.error));
}

function receiptPending(record: AgentMessageRecord, receipt: AgentMessageReceipt): boolean {
  if (receipt.delivery === "failed" || receipt.delivery === "revoked" || receipt.handling === "wake_failed") return false;
  if (receipt.delivery !== "delivered") return true;
  if (record.type === "request") return receipt.handling !== "replied";
  return receipt.handling !== "received" && receipt.handling !== "replied";
}

export function messageMatches(record: AgentMessageRecord, query: string, filter: AgentMessageFilter): boolean {
  const text = [record.title, record.body, record.sender.name, record.sender.agentId,
    ...record.recipients.flatMap((r) => [r.name, r.agentId])].join(" ").toLocaleLowerCase();
  if (query.trim() && !text.includes(query.trim().toLocaleLowerCase())) return false;
  if (filter === "exception") return messageHasException(record);
  if (filter === "pending") return record.recipients.length === 0 || record.recipients.some((r) => receiptPending(record, r));
  if (filter === "replied") return record.type === "reply" || (record.recipients.length > 0 && record.recipients.every((r) => r.handling === "replied"));
  return true;
}

export function messageSummary(record: AgentMessageRecord, lang: AgentMessageLang): string {
  const receipts = record.recipients;
  if (receipts.length === 0) return messageText(lang, "回执待确认", "Receipt unconfirmed");
  if (receipts.length > 1) {
    const delivered = receipts.filter((r) => r.delivery === "delivered").length;
    const complete = receipts.filter((r) => record.type === "request" ? r.handling === "replied" : r.handling === "received" || r.handling === "replied").length;
    const status = record.type === "request" ? messageText(lang, "已回复", "replied") : messageText(lang, "已收取", "collected");
    const unknown = receipts.filter((r) => r.delivery === "unknown" || r.handling === "unknown").length;
    const confirmation = unknown ? messageText(lang, ` · ${unknown} 待确认`, ` · ${unknown} unconfirmed`) : "";
    const exception = messageHasException(record) ? messageText(lang, " · 存在异常", " · Exceptions") : "";
    return `${delivered}/${receipts.length} ${messageText(lang, "已送达", "delivered")} · ${complete}/${receipts.length} ${status}${confirmation}${exception}`;
  }
  const receipt = receipts[0];
  if (receipt.delivery !== "delivered") return deliveryLabel(receipt.delivery, lang);
  const awaitingReply = record.type === "request" && receipt.handling === "received" ? messageText(lang, " · 待回复", " · Awaiting reply") : "";
  return `${deliveryLabel(receipt.delivery, lang)} · ${handlingLabel(receipt.handling, lang)}${awaitingReply}`;
}

export function messageTime(createdAt: string, lang: AgentMessageLang): string {
  const date = new Date(createdAt);
  if (!Number.isFinite(date.getTime())) return messageText(lang, "时间待确认", "Time unconfirmed");
  return date.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
  });
}
