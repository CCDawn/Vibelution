import type { ChatNextStateSignalSummary, ConversationMessage, ToolCallTurnItem } from "../../api/types";
import { assistantToolCallTurnItems } from "../../routes/chatTurnProtocol";

function isBusyConversationPhase(phase: string) {
  return ["queued", "running", "stopping"].includes(String(phase || "").trim().toLowerCase());
}

function failedToolName(signal: ChatNextStateSignalSummary) {
  const match = String(signal.summary || "").trim().match(/^tool failed:\s*(.+)$/i);
  return match?.[1]?.trim() || "";
}

function isFailedToolCall(toolCall: ToolCallTurnItem) {
  return toolCall.status === "failed";
}

function isSuccessfulToolCall(toolCall: ToolCallTurnItem) {
  return toolCall.status === "completed";
}

function toolCallIdentity(toolCall: ToolCallTurnItem) {
  return toolCall.toolName.trim();
}

function latestTurnRecoveredToolFailure(
  signal: ChatNextStateSignalSummary,
  messages: ConversationMessage[],
) {
  const toolName = failedToolName(signal);
  if (!toolName) {
    return false;
  }
  let latestUserIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "user") {
      latestUserIndex = index;
      break;
    }
  }
  const latestTurnToolCalls = messages
    .slice(Math.max(0, latestUserIndex + 1))
    .flatMap(assistantToolCallTurnItems)
    .filter((toolCall) => toolCallIdentity(toolCall) === toolName);
  const terminalToolCalls = latestTurnToolCalls.filter(
    (toolCall) => isFailedToolCall(toolCall) || isSuccessfulToolCall(toolCall),
  );
  const latestTerminalToolCall = terminalToolCalls.at(-1);
  return terminalToolCalls.some(isFailedToolCall)
    && Boolean(latestTerminalToolCall && isSuccessfulToolCall(latestTerminalToolCall));
}

export function shouldShowNextStateSignalInConversation(
  signal: ChatNextStateSignalSummary,
  phase: string,
  messages: ConversationMessage[] = [],
) {
  if (signal.kind === "user_continues") {
    return isBusyConversationPhase(phase);
  }
  if (
    signal.kind === "tool_error"
    && !isBusyConversationPhase(phase)
    && latestTurnRecoveredToolFailure(signal, messages)
  ) {
    return false;
  }
  return true;
}
