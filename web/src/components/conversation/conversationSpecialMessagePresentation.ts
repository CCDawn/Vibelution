import type { ConversationMessage } from "../../api/types";

export function conversationMessageMetadataText(
  metadata: Record<string, unknown> | undefined,
  key: string,
) {
  const value = metadata?.[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value).trim();
  }
  return "";
}

export function cliAgentLifecycleLabel(message: ConversationMessage, lang: "zh" | "en") {
  const label = conversationMessageMetadataText(message.metadata, "label")
    || conversationMessageMetadataText(message.metadata, "adapterId")
    || "CLI Agent";
  const event = conversationMessageMetadataText(message.metadata, "event")
    || conversationMessageMetadataText(message.metadata, "status");
  if (event === "closed") {
    return lang === "zh" ? `终端已关闭 · ${label}` : `Terminal closed · ${label}`;
  }
  return lang === "zh" ? `终端状态 · ${label}` : `Terminal status · ${label}`;
}

export function cliAgentLifecycleDetail(message: ConversationMessage) {
  return conversationMessageMetadataText(message.metadata, "cliRunId")
    || conversationMessageMetadataText(message.metadata, "terminalSessionId")
    || message.content;
}

export function agentInboxSourceLabel(message: ConversationMessage) {
  const metadata = message.metadata;
  const sourceLabel = [
    conversationMessageMetadataText(metadata, "sourceAgentCode"),
    conversationMessageMetadataText(metadata, "sourceAgentName"),
  ].filter(Boolean).join(" · ");
  if (sourceLabel) {
    return `Agent 私信 · ${sourceLabel}`;
  }
  const fallback = String(message.content ?? "").match(/^来源 Agent:\s*(.+)$/m)?.[1]?.trim();
  return fallback ? `Agent 私信 · ${fallback}` : "Agent 私信";
}

export function agentInboxSummary(message: ConversationMessage) {
  const metadataSummary = conversationMessageMetadataText(message.metadata, "summary");
  if (metadataSummary) {
    return metadataSummary;
  }
  const content = String(message.content ?? "");
  const summaryMatch = content.match(/^摘要:\s*([\s\S]*?)(?:\n\s*消息内容:|$)/m);
  const summary = summaryMatch?.[1]?.trim();
  if (summary) {
    return summary;
  }
  const bodyMatch = content.match(/^消息内容:\s*([\s\S]*)$/m);
  const body = bodyMatch?.[1]?.trim();
  if (body) {
    return body.replace(/\s+/g, " ").trim();
  }
  return content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith("[Agent 私信") && !line.startsWith("来源 Agent") && !line.startsWith("消息ID"))
    ?? "";
}

export function groupRoomTranscriptLabel(message: ConversationMessage) {
  const roomTitle = conversationMessageMetadataText(message.metadata, "sourceRoomTitle");
  return roomTitle ? `群聊同步记录 · ${roomTitle}` : "群聊同步记录";
}
