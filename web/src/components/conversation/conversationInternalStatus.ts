import type { ConversationMessage } from "../../api/types";
import { assistantFinalAnswerText, assistantStatusTurnItems } from "../../routes/chatTurnProtocol";

const STREAMING_STATUS_CONTENT_MARKERS = [
  "正在准备对话上下文",
  "正在读取当前会话",
  "正在唤起对话 agent",
  "正在绑定 agent 实例",
  "私有工作区",
  "工具工作区",
  "正在请求模型",
  "等待首个响应片段",
  "模型连接正在重试",
  "本轮仍在继续",
  "上下文已组装完成",
  "正在进入 llm 调用",
  "正在思考，已收到思考片段",
  "模型已经开始返回 reasoning",
  "正文可能稍后出现",
  "preparing the conversation context",
  "reading the current session",
  "preparing the conversation agent",
  "binding the agent instance",
  "private workspace",
  "tool workspace",
  "requesting the model",
  "waiting for the first response chunk",
  "model connection is retrying",
  "retrying the model connection",
  "model request is retrying",
  "context is assembled",
  "llm call is starting",
  "thinking, received reasoning",
  "reasoning may appear later",
];

const INTERNAL_STREAMING_STATUS_STAGES = new Set([
  "context_prepare",
  "queued",
  "agent_prepare",
  "history_restore",
  "model_request",
  "model_thinking",
  "model_retry",
  "retrying",
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

export function isStreamingStatusPlaceholderContent(content: string) {
  return isInternalStreamingStatusContent(content);
}

export function isNoFinalAnswerStatusContent(content: string) {
  const normalized = String(content ?? "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return false;
  }
  const mentionsNoFinalAnswer =
    normalized.startsWith("本轮还没有形成最终回答")
    || normalized.startsWith("本轮尚未形成最终回答")
    || normalized.startsWith("尚未形成最终回答");
  return mentionsNoFinalAnswer && /继续|恢复|衔接|保留当前执行进度|工具循环/.test(normalized);
}

export function compactStreamingStatusPlaceholder(
  content: string,
  compactPreview: (value: string, maxLength?: number) => string,
) {
  if (isInternalStreamingStatusContent(content)) {
    return "";
  }
  return compactPreview(String(content ?? "").replace(/\s+/g, " ").trim(), 92);
}

export function isInternalStreamingStatusStage(stage: unknown) {
  return INTERNAL_STREAMING_STATUS_STAGES.has(String(stage ?? "").trim().toLowerCase());
}

export function messageHasInternalStreamingStatusContent(message: ConversationMessage) {
  return assistantStatusTurnItems(message)
    .some((item) => isInternalStreamingStatusContent(item.type === "retry" ? item.reason : item.text));
}

export function answerProjectionContent(message: ConversationMessage) {
  if (message.role === "user") {
    return message.content;
  }
  return messageHasInternalStreamingStatusContent(message) ? "" : assistantFinalAnswerText(message);
}

function compactProjectionKey(value: unknown) {
  return String(value ?? "").replace(/\s+/g, "").trim();
}

/**
 * True when timeline assistant_text already owns the committed final answer.
 * Intermediate commentary / orphan capture fragments must not suppress the response body.
 *
 * Interleaved turns may split the final body across multiple assistant_text rows
 * (answer → tools → answer). Ownership uses the combined assistant_text keys.
 */
export function timelineAssistantTextCoversFinalAnswer(
  items: ReadonlyArray<{ kind?: string; text?: string }>,
  projectedAnswer: string,
) {
  const contentKey = compactProjectionKey(projectedAnswer);
  if (!contentKey) {
    return true;
  }
  const assistantKeys = items
    .filter((item) => String(item.kind ?? "").trim() === "assistant_text")
    .map((item) => compactProjectionKey(item.text))
    .filter(Boolean);
  if (assistantKeys.length === 0) {
    return false;
  }
  const combinedKey = assistantKeys.join("");
  if (
    contentKey === combinedKey
    || combinedKey.includes(contentKey)
    || (
      contentKey.includes(combinedKey)
      && combinedKey.length >= Math.max(24, Math.floor(contentKey.length * 0.8))
    )
  ) {
    return true;
  }
  // Content is exactly the concatenation of interleaved assistant_text segments
  // (order-preserving removal leaves nothing).
  let remainder = contentKey;
  for (const textKey of assistantKeys) {
    if (!textKey || !remainder.includes(textKey)) {
      continue;
    }
    remainder = remainder.split(textKey).join("");
  }
  if (!remainder) {
    return true;
  }
  for (const textKey of assistantKeys) {
    if (contentKey === textKey || textKey.includes(contentKey)) {
      return true;
    }
    if (
      contentKey.includes(textKey)
      && textKey.length >= Math.max(24, Math.floor(contentKey.length * 0.8))
    ) {
      return true;
    }
  }
  return false;
}
