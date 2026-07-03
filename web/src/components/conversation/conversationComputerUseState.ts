import type { ConversationMessage } from "../../api/types";

export const COMPUTER_USE_TOOL_NAME = "computer_use_task_tool";

export type ComputerUseResult = {
  status: string;
  sessionId: string;
  summary: string;
  steps: Array<{ index?: number; action?: string; summary?: string; status?: string }>;
  screenshotUrl: string;
  needsConfirmation: boolean;
  error: string;
};

export function computerUseSessionIdFromPreview(preview: unknown) {
  const value = String(preview ?? "").trim();
  if (!value || !value.startsWith("{")) {
    return "";
  }
  try {
    const payload = JSON.parse(value) as { sessionId?: unknown };
    return String(payload.sessionId ?? "").trim();
  } catch {
    return "";
  }
}

export function computerUseSessionIdsForMessage(message: ConversationMessage) {
  if (message.role !== "assistant") {
    return [];
  }
  const sessionIds = new Set<string>();
  for (const toolCall of message.toolCalls ?? []) {
    if (toolCall.name !== COMPUTER_USE_TOOL_NAME) {
      continue;
    }
    const sessionId = computerUseSessionIdFromPreview(toolCall.resultPreview);
    if (sessionId) {
      sessionIds.add(sessionId);
    }
  }
  for (const event of message.feedbackEvents ?? []) {
    if (event.kind !== "tool" || event.name !== COMPUTER_USE_TOOL_NAME) {
      continue;
    }
    const sessionId = computerUseSessionIdFromPreview(event.resultPreview);
    if (sessionId) {
      sessionIds.add(sessionId);
    }
  }
  return Array.from(sessionIds).sort();
}

export function buildComputerUseStateForMessage(
  message: ConversationMessage,
  results: Record<string, ComputerUseResult>,
  pending: Record<string, "confirm" | "cancel" | undefined>,
) {
  const sessionIds = computerUseSessionIdsForMessage(message);
  if (sessionIds.length === 0) {
    return "";
  }
  return sessionIds
    .map((sessionId) => {
      const result = results[sessionId];
      return [
        sessionId,
        pending[sessionId] ?? "",
        result?.status ?? "",
        result?.summary ?? "",
        result?.error ?? "",
        result?.screenshotUrl ?? "",
        result?.needsConfirmation ? "1" : "0",
      ].join("\u001f");
    })
    .join("\u001e");
}
