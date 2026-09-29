/**
 * Turn extraction for the local share/export dialog (pattern:
 * conversationTurnNavigation.ts — pure logic, no DOM). Mirrors the server-side
 * grouping in core/web/services/session/export_html.py: a turn opens at every
 * user message and owns the first assistant message that follows before the
 * next user message; leading assistant messages form their own turns. A turn's
 * id is the assistant turnId when present, otherwise the anchoring message id,
 * so dialog selections resolve server-side byte-identically.
 */

import type { ConversationMessage } from "../../api/types";
import { assistantFinalAnswerText } from "../../routes/chatTurnProtocol";

export const SHARE_EXPORT_USER_PREVIEW_MAX_CHARS = 160;
export const SHARE_EXPORT_ASSISTANT_PREVIEW_MAX_CHARS = 200;

export type ConversationShareExportTurn = {
  /** Stable export turn id (assistant turnId, else anchoring message id). */
  turnId: string;
  /** 1-based display order in the dialog. */
  turnNumber: number;
  userPreviewText: string;
  assistantPreviewText: string;
  hasAttachments: boolean;
  timestamp: string;
};

function metadataTurnId(message: ConversationMessage): string {
  const value = message.metadata?.["turnId"];
  return typeof value === "string" ? value.trim() : "";
}

function clampPreview(text: string, maxChars: number): string {
  return String(text ?? "").replace(/\s+/g, " ").trim().slice(0, maxChars);
}

type ShareExportTurnDraft = {
  turnId: string;
  user: ConversationMessage | null;
  assistant: ConversationMessage | null;
  timestamp: string;
};

export function buildConversationShareExportTurns(
  messages: readonly ConversationMessage[],
): ConversationShareExportTurn[] {
  const turns: ShareExportTurnDraft[] = [];
  let current: ShareExportTurnDraft | null = null;

  for (const message of messages) {
    if (message.role === "user") {
      current = {
        turnId: metadataTurnId(message) || message.id,
        user: message,
        assistant: null,
        timestamp: message.timestamp ?? "",
      };
      turns.push(current);
      continue;
    }
    if (message.role === "assistant") {
      const assistantTurnId = message.turnId?.trim() || metadataTurnId(message);
      if (current && current.user && !current.assistant) {
        current.assistant = message;
        if (assistantTurnId) {
          current.turnId = assistantTurnId;
        }
        continue;
      }
      current = {
        turnId: assistantTurnId || message.id,
        user: null,
        assistant: message,
        timestamp: message.timestamp ?? "",
      };
      turns.push(current);
    }
  }

  return turns.map((turn, index) => {
    const userContent = turn.user && turn.user.role === "user"
      ? String((turn.user as { content?: unknown }).content ?? "")
      : "";
    const assistantText = turn.assistant ? assistantFinalAnswerText(turn.assistant) : "";
    const attachments = turn.user && turn.user.role === "user"
      ? (turn.user as { attachments?: unknown[] }).attachments
      : undefined;
    return {
      turnId: turn.turnId,
      turnNumber: index + 1,
      userPreviewText: clampPreview(userContent, SHARE_EXPORT_USER_PREVIEW_MAX_CHARS),
      assistantPreviewText: clampPreview(assistantText, SHARE_EXPORT_ASSISTANT_PREVIEW_MAX_CHARS),
      hasAttachments: Array.isArray(attachments) && attachments.length > 0,
      timestamp: turn.timestamp,
    };
  });
}
