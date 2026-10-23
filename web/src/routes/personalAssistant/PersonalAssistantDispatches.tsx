import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Send } from "lucide-react";

import {
  fetchPersonalAssistantDispatches,
  personalAssistantDispatchesQueryKey,
  type PersonalAssistantDispatchReceipt,
  type PersonalAssistantDispatchStatus,
  type PersonalAssistantTaskStatus,
} from "../../api/personalAssistantDispatches";
import { VButton, VStateSurface } from "../../components/vui";
import { useShellI18n } from "../../i18n/useShellI18n";
import styles from "./PersonalAssistantDispatches.styles";

/** Interface copy only; dispatch and receipt values arrive from the backend closed enums. */
const COPY = {
  zh: {
    title: "派遣",
    subtitle: "查看助理派给其他智能体的任务和收到的回执。",
    sentSection: "派出",
    unmatchedSection: "收到的回执（未配对）",
    statusLabels: { pending: "待对方接收", consumed: "对方已接收", revoked: "已撤销" } as Record<PersonalAssistantDispatchStatus, string>,
    taskStatusLabels: { awaiting_result: "等待结果", running: "进行中", blocked: "遇到阻塞", awaiting_confirmation: "收到回复，结果待确认", completed: "对方报告完成", failed: "对方报告失败", cancelled: "已取消" } as Record<PersonalAssistantTaskStatus, string>,
    receiptStatusLabels: { pending: "未读", consumed: "已读", revoked: "已撤销" } as Record<PersonalAssistantDispatchStatus, string>,
    receiptCount: (n: number) => `${n} 条回执`,
    showReceipts: "回执",
    hideReceipts: "收起回执",
    openSession: "打开执行会话",
    empty: "还没有派遣记录",
    emptyHint: "对助理说「把任务派给某某」即可开始。",
    loadFailed: "派遣记录读取失败",
    retry: "重试",
    loading: "正在读取派遣记录…",
  },
  en: {
    title: "Dispatches",
    subtitle: "Track the tasks the assistant delegated to other agents and their receipts.",
    sentSection: "Sent",
    unmatchedSection: "Receipts (unmatched)",
    statusLabels: { pending: "Awaiting delivery", consumed: "Received by agent", revoked: "Revoked" } as Record<PersonalAssistantDispatchStatus, string>,
    taskStatusLabels: { awaiting_result: "Awaiting result", running: "In progress", blocked: "Blocked", awaiting_confirmation: "Reply received; result unconfirmed", completed: "Reported complete", failed: "Reported failed", cancelled: "Cancelled" } as Record<PersonalAssistantTaskStatus, string>,
    receiptStatusLabels: { pending: "Unread", consumed: "Read", revoked: "Revoked" } as Record<PersonalAssistantDispatchStatus, string>,
    receiptCount: (n: number) => `${n} ${n === 1 ? "receipt" : "receipts"}`,
    showReceipts: "Receipts",
    hideReceipts: "Hide receipts",
    openSession: "Open execution session",
    empty: "No dispatches yet",
    emptyHint: "Tell the assistant to dispatch a task to an agent to start.",
    loadFailed: "Failed to load dispatches",
    retry: "Retry",
    loading: "Loading dispatches…",
  },
} as const;

function formatTime(iso: string, lang: "zh" | "en"): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(lang === "zh" ? "zh-CN" : "en-US", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function PersonalAssistantDispatches({ agentId, headerAction, onOpenSession }: {
  agentId: string;
  headerAction?: ReactNode;
  onOpenSession?: (sessionId: string) => void;
}) {
  const { lang } = useShellI18n();
  const copy = COPY[lang];
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const dispatches = useQuery({
    queryKey: personalAssistantDispatchesQueryKey(agentId),
    queryFn: ({ signal }) => fetchPersonalAssistantDispatches({ signal }),
    enabled: Boolean(agentId),
    retry: 1,
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  });
  const data = dispatches.data;
  const items = data?.dispatches ?? [];
  const unmatched = data?.unmatchedReceipts ?? [];

  function receiptRow(receipt: PersonalAssistantDispatchReceipt, keyPrefix: string) {
    return <li key={`${keyPrefix}${receipt.messageId}`}>
      <div className={styles.receiptRow}>
        <span className={styles.itemMeta}>
          <strong className={styles.receiptSource}>{receipt.sourceAgentName || receipt.sourceAgentId}</strong>
          <span className={receipt.status === "pending" ? styles.badgePending : styles.badge}>
            {copy.receiptStatusLabels[receipt.status]}
          </span>
          {receipt.taskStatus ? <span className={styles.badge}>{copy.taskStatusLabels[receipt.taskStatus]}</span> : null}
          {receipt.receivedAt ? <span className={styles.itemNote}>{formatTime(receipt.receivedAt, lang)}</span> : null}
        </span>
        {receipt.summary ? <span className={styles.itemNote}>{receipt.summary}</span> : null}
        {receipt.evidenceRefs?.length ? <span className={styles.itemNote}>{receipt.evidenceRefs.join(" · ")}</span> : null}
      </div>
    </li>;
  }

  return <section className={styles.root} aria-label={copy.title}>
    <div className={styles.pinned}>
      <header className={styles.header}>
        <div>
          <h2>{copy.title}</h2>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>
        <div className={styles.headerActions}>{headerAction}</div>
      </header>
    </div>
    <div className={styles.content}>
      {dispatches.isError ? <VStateSurface density="compact" tone="error" title={copy.loadFailed}
        actions={<VButton variant="secondary" onClick={() => void dispatches.refetch()}>{copy.retry}</VButton>}>
        {dispatches.error instanceof Error ? dispatches.error.message : ""}
      </VStateSurface> : null}
      {dispatches.isPending ? <VStateSurface density="compact" tone="loading" busy skeletonLines title={copy.loading} /> : null}
      {data ? <>
        {items.length ? <>
          <div className={styles.sectionTitle}>{copy.sentSection}</div>
          <ul className={styles.list}>
            {items.map(item => <li key={item.messageId}>
              <div className={styles.item}>
                <div className={styles.itemHead}>
                  <span className={styles.itemCopy}>
                    <strong>{item.targetAgentName || item.targetAgentId}</strong>
                    <span className={styles.itemMeta}>
                      <span className={item.deliveryStatus === "pending" ? styles.badgePending : styles.badge}>
                        {copy.statusLabels[item.deliveryStatus]}
                      </span>
                      <span className={styles.badge}>
                        {copy.taskStatusLabels[item.taskStatus ?? (item.deliveryStatus === "revoked" ? "cancelled" : item.receipts.length ? "awaiting_confirmation" : item.deliveryStatus === "consumed" ? "running" : "awaiting_result")]}
                      </span>
                      {item.receipts.length ? <span className={styles.badge}>{copy.receiptCount(item.receipts.length)}</span> : null}
                      {item.sentAt ? <span className={styles.itemNote}>{formatTime(item.sentAt, lang)}</span> : null}
                    </span>
                    {item.summary ? <span className={styles.itemNote}>{item.summary}</span> : null}
                  </span>
                  {item.receipts.length || (item.targetSessionId && onOpenSession) ? <span className={styles.itemActions}>
                    {item.targetSessionId && onOpenSession ? <VButton variant="secondary" density="compact"
                      aria-label={`${copy.openSession}: ${item.targetAgentName || item.targetAgentId}`}
                      onClick={() => onOpenSession(item.targetSessionId)}>{copy.openSession}</VButton> : null}
                    {item.receipts.length ? <VButton variant="ghost" density="compact" aria-expanded={expandedId === item.messageId}
                      aria-label={`${copy.showReceipts}: ${item.targetAgentName || item.targetAgentId}`}
                      onClick={() => setExpandedId(expandedId === item.messageId ? null : item.messageId)}>
                      {expandedId === item.messageId ? copy.hideReceipts : copy.showReceipts}
                    </VButton> : null}
                  </span> : null}
                </div>
                {expandedId === item.messageId && item.receipts.length ? <ul className={styles.receiptList}>
                  {item.receipts.map(receipt => receiptRow(receipt, `${item.messageId}:`))}
                </ul> : null}
              </div>
            </li>)}
          </ul>
        </> : <div className={styles.empty}>
          <Send size={20} />
          <strong>{copy.empty}</strong>
          <span>{copy.emptyHint}</span>
        </div>}
        {unmatched.length ? <>
          <div className={styles.sectionTitle}>{copy.unmatchedSection}</div>
          <ul className={styles.list}>
            {unmatched.map(receipt => receiptRow(receipt, "unmatched:"))}
          </ul>
        </> : null}
      </> : null}
    </div>
  </section>;
}
