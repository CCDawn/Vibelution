import { isSteerGuidanceMessage } from "../components/conversation/conversationMessagePredicates";

export type ChatEditTarget = {
  messageId: string;
  /** Journal node id the edit should branch from; empty for legacy rows. */
  nodeId?: string;
  original: string;
};

export type MessageIdentity = {
  id?: string;
  role?: string;
  metadata?: { kind?: unknown } | null;
};

export function latestUserMessageId(messages: MessageIdentity[] | null | undefined): string {
  const items = messages ?? [];
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const message = items[index];
    if (String(message?.role ?? "").trim().toLowerCase() !== "user") {
      continue;
    }
    if (isSteerGuidanceMessage({ role: "user", metadata: message.metadata ?? undefined })) {
      continue;
    }
    return String(message?.id ?? "").trim();
  }
  return "";
}

/**
 * An edit target stays valid while its message is still on the active path.
 * Branch mode edits any visible message, not just the latest one, so presence
 * (not recency) is what decides whether the composer keeps editing mode.
 */
export function resolveActiveEditTarget(
  editTarget: ChatEditTarget | null | undefined,
  messages: MessageIdentity[] | null | undefined,
): ChatEditTarget | null {
  if (!editTarget) {
    return null;
  }
  const present = (messages ?? []).some(
    (message) => String(message?.id ?? "").trim() === editTarget.messageId,
  );
  return present ? editTarget : null;
}

export function resolveComposerDraftValue(
  draft: string,
  editTarget: ChatEditTarget | null | undefined,
  resolvedEditTarget: ChatEditTarget | null,
): string {
  if (editTarget && !resolvedEditTarget) {
    return "";
  }
  return draft;
}
