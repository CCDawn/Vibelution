import { forwardRef, useCallback, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ArrowRight, RefreshCw, Send } from "lucide-react";

import { VButton, VInput } from "../vui";
import { MessageActor, MessageAvatar } from "./AgentMessageParts";
import { messageHasException, messageKind, messageMatches, messageSummary, messageText, messageTime, type AgentMessageFilter } from "./agentMessagePresentation";
import type { AgentMessageLang, AgentMessageRecord, AgentMessageScope } from "./types";
import styles from "./AgentMessages.styles";

export interface AgentMessageSidebarProps {
  records: readonly AgentMessageRecord[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  lang: AgentMessageLang;
  scope: AgentMessageScope;
  onScopeChange: (scope: AgentMessageScope) => void;
  currentScopeAvailable?: boolean;
  loading?: boolean;
  error?: string | null;
  onRefresh?: () => void;
  footer?: ReactNode;
  className?: string;
}

export interface AgentMessageSidebarHandle {
  /** Explicit navigation also reveals a record hidden by the local filters. */
  locate: (id: string) => void;
}

export const AgentMessageSidebar = forwardRef<AgentMessageSidebarHandle, AgentMessageSidebarProps>(function AgentMessageSidebar({
  records, selectedId, onSelect, lang, scope, onScopeChange, currentScopeAvailable = true,
  loading = false, error, onRefresh, footer, className,
}, ref) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<AgentMessageFilter>("all");
  const [pendingLocate, setPendingLocate] = useState<string | null>(null);
  const listRef = useRef<HTMLElement>(null);
  const previousSelection = useRef<string | null | undefined>(undefined);
  const anchorRef = useRef<{ id: string; offset: number } | null>(null);
  const visible = useMemo(() => records.filter((record) => messageMatches(record, query, filter)), [records, query, filter]);

  const captureAnchor = useCallback(() => {
    const list = listRef.current;
    if (!list) return;
    const top = list.getBoundingClientRect().top;
    const row = [...list.querySelectorAll<HTMLButtonElement>("[data-message-id]")]
      .find((item) => item.getBoundingClientRect().bottom > top);
    anchorRef.current = row ? { id: row.dataset.messageId!, offset: row.getBoundingClientRect().top - top } : null;
  }, []);

  const locate = useCallback((id: string) => {
    if (!records.some((record) => record.id === id)) return;
    if (!visible.some((record) => record.id === id)) {
      setQuery("");
      setFilter("all");
    }
    setPendingLocate(id);
  }, [records, visible]);
  useImperativeHandle(ref, () => ({ locate }), [locate]);

  // Selection belongs to the caller. Refreshing records never selects the newest row.
  useLayoutEffect(() => {
    if (previousSelection.current === selectedId) return;
    previousSelection.current = selectedId;
    if (selectedId) locate(selectedId);
  }, [selectedId, locate]);

  // Keep the first visible row at the same reading position when records prepend.
  useLayoutEffect(() => {
    const list = listRef.current;
    const anchor = anchorRef.current;
    if (!list || !anchor) return;
    const row = [...list.querySelectorAll<HTMLButtonElement>("[data-message-id]")]
      .find((item) => item.dataset.messageId === anchor.id);
    if (row) list.scrollTop += row.getBoundingClientRect().top - list.getBoundingClientRect().top - anchor.offset;
  }, [records]);

  useLayoutEffect(() => {
    if (pendingLocate) {
      const row = [...(listRef.current?.querySelectorAll<HTMLButtonElement>("[data-message-id]") ?? [])]
        .find((item) => item.dataset.messageId === pendingLocate);
      if (row) {
        row.scrollIntoView?.({ block: "nearest", inline: "nearest" });
        setPendingLocate(null);
      }
    }
    captureAnchor();
  }, [pendingLocate, visible, captureAnchor]);

  const filters: Array<{ id: AgentMessageFilter; label: string }> = [
    { id: "all", label: messageText(lang, "全部", "All") },
    { id: "pending", label: messageText(lang, "待处理", "Pending") },
    { id: "replied", label: messageText(lang, "已回复", "Replied") },
    { id: "exception", label: messageText(lang, "异常", "Exceptions") },
  ];
  return <aside className={[styles.sidebar, className].filter(Boolean).join(" ")} aria-label={messageText(lang, "跨 Agent 消息左栏", "Agent messages sidebar")} data-testid="agent-message-sidebar">
    <header className={styles.listHeader}>
      <div><h2 className={styles.heading}>{messageText(lang, "跨 Agent 消息", "Agent messages")}</h2><p className={styles.subheading}>{messageText(lang, "发送记录与关联回复", "Sent messages and linked replies")}</p></div>
      <Send size={18} aria-hidden="true" />
    </header>
    <div className={styles.switch} aria-label={messageText(lang, "消息展示范围", "Message scope")}>
      <VButton className={styles.control} aria-pressed={scope === "current"} isDisabled={!currentScopeAvailable} title={!currentScopeAvailable ? messageText(lang, "请先打开一个对话", "Open a conversation first") : undefined} onPress={() => onScopeChange("current")}>{messageText(lang, "当前对话", "Conversation")}</VButton>
      <VButton className={styles.control} aria-pressed={scope === "all"} onPress={() => onScopeChange("all")}>{messageText(lang, "消息中心", "Message center")}</VButton>
    </div>
    <div className={styles.search}><VInput type="search" aria-label={messageText(lang, "搜索消息或 Agent", "Search messages or agents")} placeholder={messageText(lang, "搜索消息或 Agent", "Search messages or agents")} value={query} onChange={(event) => setQuery(event.target.value)} /></div>
    <div className={styles.filters} aria-label={messageText(lang, "消息状态筛选", "Message status filters")}>
      {filters.map((item) => <VButton key={item.id} className={styles.control} aria-pressed={filter === item.id} onPress={() => setFilter(item.id)}>{item.label}</VButton>)}
    </div>
    {error ? <div className={styles.loadError} role="alert"><p>{messageText(lang, "消息加载失败：", "Could not load messages: ")}{error}</p>{onRefresh ? <VButton className={styles.control} onPress={onRefresh}>{messageText(lang, "重新加载", "Reload")}</VButton> : null}</div> : null}
    <div className={styles.sectionLabel}>{messageText(lang, "消息记录", "Messages")} <span className="tabular-nums">{records.length}</span>{loading ? <span role="status">{messageText(lang, "加载中…", "Loading…")}</span> : null}</div>
    <nav ref={listRef} className={styles.messageList} aria-label={messageText(lang, "跨 Agent 消息记录", "Agent message records")} aria-busy={loading} onScroll={captureAnchor} data-testid="agent-message-list">
      {visible.map((record) => <VButton key={record.id} contentLayout="plain" className={styles.messageRow} aria-pressed={selectedId === record.id} data-message-id={record.id} onPress={() => { onSelect(record.id); locate(record.id); }}>
        <span className={styles.identity}><MessageActor actor={record.sender} compact /><ArrowRight size={12} className={styles.arrow} aria-hidden="true" />
          {record.recipients.length === 1 ? <MessageActor actor={record.recipients[0]} compact /> : record.recipients.length > 1 ? <span className={styles.recipientGroup} title={record.recipients.map((r) => r.name || r.agentId).join("、")}>
            <span className={styles.avatarStack} aria-hidden="true">{record.recipients.slice(0, 2).map((recipient) => <MessageAvatar key={recipient.agentId} actor={recipient} compact />)}</span>
            <span className="truncate">{messageText(lang, `${record.recipients[0].name || record.recipients[0].agentId}等 ${record.recipients.length} 位`, `${record.recipients.length} recipients`)}</span>
          </span> : <span className={styles.compactName}>{messageText(lang, "接收方待确认", "Recipient unconfirmed")}</span>}
        </span>
        <span className={styles.title}>{record.title || messageText(lang, "无标题消息", "Untitled message")}</span>
        <span className={styles.meta}><span>{messageKind(record, lang)}</span><time dateTime={record.createdAt}>{messageTime(record.createdAt, lang)}</time></span>
        <span className={styles.rowState} data-tone={messageHasException(record) ? "danger" : record.recipients.some((r) => (r.delivery === "delivered" && r.handling === "processing") || r.delivery === "sending") ? "active" : "neutral"}>{messageSummary(record, lang)}</span>
      </VButton>)}
      {!loading && visible.length === 0 ? <div className={styles.empty}>{records.length === 0 ? error ? messageText(lang, "消息记录暂不可用", "Messages are currently unavailable") : messageText(lang, "暂无跨 Agent 消息", "No agent messages yet") : messageText(lang, "没有匹配的消息", "No matching messages")}{records.length > 0 ? <VButton onPress={() => { setQuery(""); setFilter("all"); }}>{messageText(lang, "查看全部消息", "Show all messages")}</VButton> : null}</div> : null}
    </nav>
    <footer className={styles.footer}><div className={styles.footerSummary}><span>{messageText(lang, `显示 ${visible.length} / ${records.length} 条`, `${visible.length} / ${records.length} messages`)}</span>{onRefresh ? <VButton className={styles.control} isDisabled={loading} onPress={onRefresh} icon={<RefreshCw size={13} aria-hidden="true" />}>{messageText(lang, "刷新", "Refresh")}</VButton> : null}</div>{footer ? <div className="mt-2 min-w-0 space-y-2">{footer}</div> : null}</footer>
  </aside>;
});
