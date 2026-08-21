import { VButton } from "../../components/vui";
import type { ChatRoomMessage } from "../../api/types";
import {
  tokenizeChatMentions,
  type ChatMentionTarget,
} from "../chatMentionTokens";
import styles from "./ChatGroupMessagePresentation.styles";
import {
  shouldCollapseGroupMessage,
  stripGroupSpeakerPrefix,
} from "./chatRoutePresentation";

export type ChatMentionedTextProps = {
  content: string;
  fallback?: string;
  lang: "zh" | "en";
  mentionTargets: ChatMentionTarget[];
  onOpenMentionTarget: (target: ChatMentionTarget) => void;
};

export function ChatMentionedText({
  content,
  fallback = "",
  lang,
  mentionTargets,
  onOpenMentionTarget,
}: ChatMentionedTextProps) {
  const text = content || fallback;
  return (
    <>
      {tokenizeChatMentions(text, mentionTargets).map((segment, index) => {
        if (segment.type === "text") {
          return <span key={`text-${index}`}>{segment.text}</span>;
        }
        const mentionLabel = segment.target.kind === "all"
          ? (lang === "zh" ? "全体成员" : "All agents")
          : [segment.target.displayName, segment.target.agentCode].filter(Boolean).join(" · ");
        return (
          <VButton
            key={`mention-${index}-${segment.text}`}
            type="button"
            className={styles.agentMention}
            onClick={() => onOpenMentionTarget(segment.target)}
            aria-label={lang === "zh" ? `打开 ${mentionLabel} 的索引` : `Open ${mentionLabel} index`}
            title={lang === "zh" ? "打开对应 Agent 索引" : "Open the matching agent index"}
          >
            {segment.text}
          </VButton>
        );
      })}
    </>
  );
}

export type ChatGroupMessageBodyProps = {
  message: ChatRoomMessage;
  identityName: string;
  lang: "zh" | "en";
  expandedMessageIds: string[];
  mentionTargets: ChatMentionTarget[];
  onOpenMentionTarget: (target: ChatMentionTarget) => void;
  onToggleExpanded: (messageId: string) => void;
};

export function ChatGroupMessageBody({
  message,
  identityName,
  lang,
  expandedMessageIds,
  mentionTargets,
  onOpenMentionTarget,
  onToggleExpanded,
}: ChatGroupMessageBodyProps) {
  const content = stripGroupSpeakerPrefix(message, identityName);
  const expanded = expandedMessageIds.includes(message.messageId);
  const collapsible = shouldCollapseGroupMessage(content);
  const collapsed = collapsible && !expanded;
  const collapseLabel = lang === "zh" ? "展开全文" : "Show full";

  const messageStatus = String(message.status ?? "").toLowerCase();
  const failureReason = messageStatus !== "completed" && !content.trim()
    ? String(message.summary || message.errorType || "").trim()
    : "";
  return (
    <>
      <p className={collapsed ? `${styles.groupBubbleBody} ${styles.groupBubbleBodyCollapsed}` : styles.groupBubbleBody}>
        <ChatMentionedText
          content={content}
          fallback={failureReason
            ? (lang === "zh" ? `发言未完成：${failureReason}` : `Message incomplete: ${failureReason}`)
            : (lang === "zh" ? "暂无内容" : "No content yet")}
          lang={lang}
          mentionTargets={mentionTargets}
          onOpenMentionTarget={onOpenMentionTarget}
        />
      </p>
      {collapsible ? (
        <VButton
          type="button"
          className={styles.groupBubbleToggle}
          onClick={() => onToggleExpanded(message.messageId)}
        >
          {expanded ? (lang === "zh" ? "收起" : "Collapse") : collapseLabel}
        </VButton>
      ) : null}
    </>
  );
}
