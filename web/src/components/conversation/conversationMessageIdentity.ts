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

export function conversationMessageTurnId(message: ConversationMessage) {
  return conversationMessageMetadataText(message.metadata, "turnId").replace(/^live:/, "");
}

export function projectedConversationMessageIds(message: ConversationMessage) {
  const rawIds = message.metadata?.projectedMessageIds;
  if (!Array.isArray(rawIds)) {
    return [];
  }
  return rawIds.map((id) => String(id).trim()).filter(Boolean);
}

export function projectedConversationMessageIdsOrSelf(message: ConversationMessage) {
  const projectedIds = projectedConversationMessageIds(message);
  return projectedIds.length > 0 ? projectedIds : [message.id];
}
