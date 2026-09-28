import type { ConversationMessage } from "../../api/types";
import {
  assistantFinalAnswerText,
  assistantStatusTurnItems,
  assistantTurnIsStreaming,
} from "../../routes/chatTurnProtocol";

function metadataString(message: ConversationMessage, key: string) {
  const value = message.metadata?.[key];
  return typeof value === "string" ? value.trim() : "";
}

export function isProviderFailureSummaryText(text: unknown) {
  const value = String(text ?? "").trim().toLowerCase();
  if (!value) {
    return false;
  }
  return [
    "模型服务上游暂时失败，本轮没有完成",
    "the model provider failed upstream, so this turn did not complete",
  ].some((marker) => value.includes(marker));
}

export function isTurnErrorMessage(message: ConversationMessage) {
  if (message.role !== "assistant") {
    return false;
  }
  if (metadataString(message, "kind") === "turn_error") {
    return true;
  }
  if (assistantStatusTurnItems(message).some((item) => (
    item.type === "error" && isProviderFailureSummaryText(item.text)
  ))) {
    return true;
  }
  return metadataString(message, "kind") === "image2_generation"
    && metadataString(message, "status") === "failed";
}

export function isRuntimeNoticeText(text: unknown) {
  const content = String(text ?? "").trim().toLowerCase();
  return [
    "上一轮运行已被中断，当前会话已恢复为可继续状态",
    "the previous turn was interrupted. this session is ready to continue",
  ].some((notice) => content.includes(notice));
}

export function isRuntimeNoticeMessage(message: ConversationMessage) {
  return message.role === "assistant" && assistantStatusTurnItems(message)
    .some((item) => isRuntimeNoticeText(item.type === "retry" ? item.reason : item.text));
}

function normalizeRuntimeStatusText(text: unknown) {
  return String(text ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

export function isLiveOverlayMessage(message: Pick<ConversationMessage, "metadata">) {
  const kind = String(message.metadata?.kind ?? "").trim();
  return kind === "session_live_overlay" || kind === "session_active_turn_layer";
}

function isStreamingRuntimeStatusCarrier(message: ConversationMessage) {
  const stage = assistantStatusTurnItems(message)
    .map((item) => item.type === "status" ? item.code : item.type)
    .at(-1)
    ?.trim()
    .toLowerCase();
  return isLiveOverlayMessage(message)
    || assistantTurnIsStreaming(message)
    || stage === "model_thinking"
    || stage === "model_request"
    || stage === "thinking";
}

export function isTransientReasoningStatusText(text: unknown) {
  const content = normalizeRuntimeStatusText(text);
  if (!content || content.length > 360) {
    return false;
  }
  const hasReasoningStatusMarker = [
    "已收到思考片段",
    "模型已经开始返回 reasoning",
    "正文可能稍后出现",
    "received reasoning",
    "reasoning has started",
    "answer may appear later",
  ].some((marker) => content.includes(marker));
  const hasThinkingMarker = content.includes("正在思考")
    || content.includes("reasoning")
    || content.includes("thinking");
  return hasReasoningStatusMarker && hasThinkingMarker;
}

export function isRuntimeStatusContent(message: ConversationMessage) {
  if (message.role !== "assistant") {
    return false;
  }
  const content = assistantFinalAnswerText(message);
  if (!content) {
    return false;
  }
  if (
    /^(状态|status)\s+.+/i.test(content)
    && /(正在|running|thinking|reasoning|tooling|模型|model|上下文|context)/i.test(content)
  ) {
    return true;
  }
  return isStreamingRuntimeStatusCarrier(message) && isTransientReasoningStatusText(content);
}

export function isAgentInboxMessage(message: ConversationMessage) {
  const kind = String(message.metadata?.kind ?? "").trim();
  if (kind === "agent_inbox_message") {
    return true;
  }
  return assistantFinalAnswerText(message).startsWith("[Agent 私信");
}

const STEER_GUIDANCE_KINDS = new Set(["user_guidance", "user_interrupt_guidance"]);

export function isSteerGuidanceMessage(message: Pick<ConversationMessage, "role" | "metadata">) {
  if (message.role !== "user") {
    return false;
  }
  const kind = String(message.metadata?.kind ?? "").trim();
  return STEER_GUIDANCE_KINDS.has(kind);
}

export function isGroupRoomTranscriptMessage(message: ConversationMessage) {
  const kind = String(message.metadata?.kind ?? "").trim();
  if (kind === "group_room_transcript") {
    return true;
  }
  return assistantFinalAnswerText(message).startsWith("[群聊同步]");
}

export function isCliAgentLifecycleMessage(message: ConversationMessage) {
  return metadataString(message, "kind") === "cli_agent_lifecycle";
}

// Context compression projects a settled checkpoint into the timeline as an
// assistant-role message with empty content, metadata.kind
// "context_compression_marker" and a status such as "applied" /
// "skipped_low_savings" / "failed_preserved" (core/chat/
// context_compression_ledger.py). The marker is lifecycle chrome, not a model
// answer: it carries no llmUsage and must not count as a turn's model.
export function isContextCompressionMarkerMessage(message: ConversationMessage) {
  return metadataString(message, "kind") === "context_compression_marker";
}

// Fork provenance: the backend records the parent at the SESSION level only
// (conversation["forkedFrom"] = {sessionId, nodeId, scope, forkedAt}, see
// core/web/services/session/fork_session.py + conversation_index.py); the
// copied journal events carry no per-message fork marker. This predicate reads
// the message-metadata spelling a fork marker would use if the backend ever
// projects one (mirroring the session record shape). Until Wave3 lands that
// projection, it can only match messages that carry the field explicitly.
export function isForkedSessionMarkerMessage(message: ConversationMessage) {
  if (metadataString(message, "forkedFromSessionId")) {
    return true;
  }
  const forkedFrom = message.metadata?.forkedFrom;
  if (forkedFrom && typeof forkedFrom === "object") {
    return Boolean(String((forkedFrom as Record<string, unknown>).sessionId ?? "").trim());
  }
  return false;
}

export function isSessionRecoveryResumedMessage(message: ConversationMessage) {
  return message.role === "assistant"
    && metadataString(message, "kind") === "session_recovery_resumed";
}

// Startup-recovery resume resubmits re-journal the original user text as a
// system-authored row (backend ``submit_session_message`` with
// ``turn_mode="hot_restart_resume"`` / ``write_intent=False``; metadata kind
// ``hot_restart_resume``). The journal keeps that row — the recovery retry
// chain re-reads the open turn's user message across restarts, and the LLM
// history already omits it server-side. Only the display layer drops it so
// the timeline does not duplicate the user message next to the original row
// (same contract as isRecoverySupersededPartial and the agent-inbox /
// steer-guidance kinds).
export function isHotRestartResumeMessage(message: ConversationMessage) {
  return message.role === "user"
    && metadataString(message, "kind") === "hot_restart_resume";
}

// Half-streamed partials from an interrupted turn already carry
// metadata.interrupted; recovery supersedes them by appending
// metadata.recoverySuperseded. Only the display layer drops them — the journal
// keeps both messages untouched.
export function isRecoverySupersededPartial(
  message: Pick<ConversationMessage, "role" | "metadata">,
) {
  return message.role === "assistant"
    && message.metadata?.interrupted === true
    && message.metadata?.recoverySuperseded === true;
}

export type ImageArtifactMessage = {
  imageUrl: string;
  downloadUrl: string;
  prompt: string;
  artifactId: string;
  size: string;
  quality: string;
  model: string;
};

function metadataValue(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  return typeof value === "string" ? value.trim() : "";
}

export type ResearchOrgMessageChip = {
  key: string;
  label: string;
  tone: "intent" | "wake" | "meta";
};

function compactLabel(value: string) {
  return value
    .trim()
    .replace(/^research_org_/, "")
    .replace(/_/g, " ");
}

export function researchOrgMessageChips(message: ConversationMessage): ResearchOrgMessageChip[] {
  const metadata = message.metadata;
  if (!metadata) {
    return [];
  }
  const intent = metadataValue(metadata, "researchOrgIntent");
  const messageType = metadataValue(metadata, "researchOrgMessageType");
  const deliveryMode = metadataValue(metadata, "researchOrgDeliveryMode");
  const wakeStatus = metadataValue(metadata, "wakeStatus");
  const inboxKind = metadataValue(metadata, "inboxKind");
  const isResearchOrgMessage = Boolean(intent || messageType || deliveryMode)
    || inboxKind.startsWith("research_org_");
  if (!isResearchOrgMessage) {
    return [];
  }
  return [
    intent ? { key: "intent", label: `intent: ${compactLabel(intent)}`, tone: "intent" as const } : null,
    messageType ? { key: "type", label: `type: ${compactLabel(messageType)}`, tone: "meta" as const } : null,
    deliveryMode ? { key: "delivery", label: `delivery: ${compactLabel(deliveryMode)}`, tone: "meta" as const } : null,
    wakeStatus ? { key: "wake", label: `wake: ${compactLabel(wakeStatus)}`, tone: "wake" as const } : null,
  ].filter(Boolean) as ResearchOrgMessageChip[];
}

export function imageArtifactForMessage(message: ConversationMessage): ImageArtifactMessage | null {
  const metadata = message.metadata;
  if (!metadata || metadataValue(metadata, "kind") !== "image2_generation") {
    return null;
  }
  if (metadataValue(metadata, "status") !== "succeeded") {
    return null;
  }
  const imageUrl = metadataValue(metadata, "imageUrl") || metadataValue(metadata, "url");
  if (!imageUrl) {
    return null;
  }
  return {
    imageUrl,
    downloadUrl: metadataValue(metadata, "downloadUrl") || imageUrl,
    prompt: metadataValue(metadata, "prompt"),
    artifactId: metadataValue(metadata, "artifactId"),
    size: metadataValue(metadata, "size"),
    quality: metadataValue(metadata, "quality"),
    model: metadataValue(metadata, "model"),
  };
}
