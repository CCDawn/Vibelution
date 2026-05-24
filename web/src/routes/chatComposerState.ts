export type ChatEditTarget = {
  messageId: string;
  original: string;
};

export type MessageIdentity = {
  id?: string;
  role?: string;
};

export function latestUserMessageId(messages: MessageIdentity[] | null | undefined): string {
  const items = messages ?? [];
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const message = items[index];
    if (String(message?.role ?? "").trim().toLowerCase() === "user") {
      return String(message?.id ?? "").trim();
    }
  }
  return "";
}

export function resolveLatestEditTarget(
  editTarget: ChatEditTarget | null | undefined,
  latestMessageId: string,
): ChatEditTarget | null {
  if (!editTarget || !latestMessageId) {
    return null;
  }
  return editTarget.messageId === latestMessageId ? editTarget : null;
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
