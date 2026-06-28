import { ConversationMessage, MentalStateSnapshot } from "../../api/types";

export function hasMentalSnapshot(snapshot: MentalStateSnapshot | undefined) {
  if (!snapshot) {
    return false;
  }
  return [
    snapshot.mood,
    snapshot.feeling,
    snapshot.whisper,
    snapshot.cognitiveState,
  ].some((value) => String(value ?? "").trim().length > 0);
}

export function hasThoughtBlock(message: ConversationMessage) {
  return message.role === "assistant"
    && Boolean(message.thought?.trim());
}

export function hasMentalBlock(message: ConversationMessage) {
  return message.role === "assistant" && hasMentalSnapshot(message.mentalSnapshot);
}

export function hasToolBlock(message: ConversationMessage) {
  return message.role === "assistant" && (message.toolCalls?.length ?? 0) > 0;
}

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
  if (isProviderFailureSummaryText(message.content)) {
    return true;
  }
  return metadataString(message, "kind") === "image2_generation"
    && metadataString(message, "status") === "failed";
}

export function isRuntimeNoticeMessage(message: ConversationMessage) {
  if (message.role !== "assistant") {
    return false;
  }
  const content = String(message.content ?? "").trim().toLowerCase();
  return [
    "上一轮运行已被中断，当前会话已恢复为可继续状态",
    "the previous turn was interrupted. this session is ready to continue",
  ].some((notice) => content.includes(notice));
}

function normalizeRuntimeStatusText(text: unknown) {
  return String(text ?? "").replace(/\s+/g, " ").trim().toLowerCase();
}

function isStreamingRuntimeStatusCarrier(message: ConversationMessage) {
  const kind = String(message.metadata?.kind ?? "").trim();
  const stage = String(message.streamStage ?? "").trim().toLowerCase();
  return Boolean(message.streaming)
    || kind === "session_live_overlay"
    || kind === "session_active_turn_layer"
    || stage === "model_thinking"
    || stage === "model_request";
}

function isTransientReasoningStatusText(text: unknown) {
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
  const content = String(message.content ?? "").trim();
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
  return String(message.content ?? "").trim().startsWith("[Agent 私信");
}

export function isGroupRoomTranscriptMessage(message: ConversationMessage) {
  const kind = String(message.metadata?.kind ?? "").trim();
  if (kind === "group_room_transcript") {
    return true;
  }
  return String(message.content ?? "").trim().startsWith("[群聊同步]");
}

export function hasUserContent(message: ConversationMessage) {
  return message.role !== "assistant" && Boolean(message.content.trim());
}

export function hasResponseBlock(message: ConversationMessage) {
  return message.role === "assistant"
    && !isRuntimeNoticeMessage(message)
    && !isRuntimeStatusContent(message)
    && !isTurnErrorMessage(message)
    && !isGroupRoomTranscriptMessage(message)
    && Boolean(message.content.trim());
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
