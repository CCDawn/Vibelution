import type { ConversationMessage } from "../../api/types";

const STREAMING_STATUS_CONTENT_MARKERS = [
  "正在准备对话上下文",
  "正在读取当前会话",
  "正在唤起对话 agent",
  "正在绑定 agent 实例",
  "私有工作区",
  "工具工作区",
  "正在请求模型",
  "等待首个响应片段",
  "上下文已组装完成",
  "正在进入 llm 调用",
  "preparing the conversation context",
  "reading the current session",
  "preparing the conversation agent",
  "binding the agent instance",
  "private workspace",
  "tool workspace",
  "requesting the model",
  "waiting for the first response chunk",
  "context is assembled",
  "llm call is starting",
];

const INTERNAL_STREAMING_STATUS_STAGES = new Set([
  "context_prepare",
  "queued",
  "agent_prepare",
  "history_restore",
  "model_request",
  "model_thinking",
  "followup_prepare",
]);

function normalizeInternalStreamingStatusText(content: string) {
  return String(content ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

export function isInternalStreamingStatusContent(content: string) {
  const normalized = normalizeInternalStreamingStatusText(content);
  if (!normalized || normalized.length > 360) {
    return false;
  }
  return STREAMING_STATUS_CONTENT_MARKERS.some((marker) => normalized.includes(marker));
}

export function isInternalStreamingStatusStage(stage: unknown) {
  return INTERNAL_STREAMING_STATUS_STAGES.has(String(stage ?? "").trim().toLowerCase());
}

export function messageHasInternalStreamingStatusContent(message: ConversationMessage) {
  if (!message.content) {
    return false;
  }
  const metadataKind = String(message.metadata?.kind ?? "").trim();
  return (
    (metadataKind === "session_live_overlay" || metadataKind === "session_active_turn_layer" || Boolean(message.streaming))
    && isInternalStreamingStatusStage(message.streamStage)
    && isInternalStreamingStatusContent(message.content)
  );
}

export function answerProjectionContent(message: ConversationMessage) {
  return messageHasInternalStreamingStatusContent(message) ? "" : message.content;
}
