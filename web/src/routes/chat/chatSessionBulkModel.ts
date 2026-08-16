import type { ConversationSummary, SessionSummary } from "../../api/types";
import { conversationToSessionSummary } from "../DirectSessionIndexList";

export type SessionBulkActionItem = {
  sessionId: string;
  reason?: string;
  message?: string;
};

export function collectDirectSessionIdsFromConversations(
  conversations: readonly ConversationSummary[],
  sessionsById: Map<string, SessionSummary>,
): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const conversation of conversations) {
    if (conversation.type === "group_room") {
      continue;
    }
    const session = conversationToSessionSummary(conversation, sessionsById);
    const sessionId = String(session.id || "").trim();
    if (!sessionId || seen.has(sessionId)) {
      continue;
    }
    seen.add(sessionId);
    ids.push(sessionId);
  }
  return ids;
}

export function sessionBulkDeletable(
  session: SessionSummary,
  isBusyPhase: (value: string | null | undefined) => boolean,
) {
  return !isBusyPhase(session.currentPhase || session.status);
}

export function sessionBulkActionSummary(
  resultLabel: string,
  success: number,
  skipped: number,
  failed: number,
  notes: string[],
  lang: "zh" | "en",
) {
  const parts = [
    resultLabel,
    lang === "zh"
      ? `成功 ${success}，跳过 ${skipped}，失败 ${failed}`
      : `${success} succeeded, ${skipped} skipped, ${failed} failed`,
  ];
  if (notes.length) {
    parts.push(notes.slice(0, 6).join(" · "));
  }
  return parts.join(" · ");
}

export function sessionBulkActionItemNote(
  item: SessionBulkActionItem,
  sessionsById: Map<string, SessionSummary>,
  fallback: string,
) {
  const session = sessionsById.get(item.sessionId);
  const title = String(session?.title || session?.agentDisplayName || item.sessionId || "").trim();
  const detail = String(item.message || fallback || item.reason || "").trim();
  return detail ? `${title}: ${detail}` : title;
}
