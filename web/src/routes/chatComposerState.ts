import { isSteerGuidanceMessage } from "../components/conversation/conversationMessagePredicates";

/** Move a local create shell's composer entry to its real identity once. */
export function rekeySessionComposerEntry<T>(entries: Record<string, T>, fromId: string, toId: string): Record<string, T> {
  if (!fromId || !toId || fromId === toId || !Object.hasOwn(entries, fromId)) return entries;
  const { [fromId]: value, ...remaining } = entries;
  return Object.hasOwn(remaining, toId) ? remaining : { ...remaining, [toId]: value };
}

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
 * The edit target owns the editor. Validity used to be re-derived from the
 * projected message list, so a stop or a re-projection that re-keyed the row
 * dropped the seeded text and left a visible but unusable editor. Presence is
 * now only decided when the user opens or cancels the edit.
 */
export function resolveActiveEditTarget(
  editTarget: ChatEditTarget | null | undefined,
  _messages: MessageIdentity[] | null | undefined,
): ChatEditTarget | null {
  return editTarget ?? null;
}

export function resolveComposerDraftValue(
  draft: string,
  _editTarget: ChatEditTarget | null | undefined,
  _resolvedEditTarget: ChatEditTarget | null,
): string {
  // The draft already carries the seeded original; blanking it here is what
  // turned a visible editor into an empty one with a disabled submit button.
  return draft;
}
