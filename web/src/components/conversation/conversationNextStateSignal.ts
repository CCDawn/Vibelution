import type { ChatNextStateSignalSummary, ConversationMessage, ToolCall } from "../../api/types";

function isBusyConversationPhase(phase: string) {
  return ["queued", "running", "stopping"].includes(String(phase || "").trim().toLowerCase());
}

function failedToolName(signal: ChatNextStateSignalSummary) {
  const match = String(signal.summary || "").trim().match(/^tool failed:\s*(.+)$/i);
  return match?.[1]?.trim() || "";
}

function isFailedToolCall(toolCall: ToolCall) {
  const status = String(toolCall.status || "").trim().toLowerCase();
  const semanticStatus = String(toolCall.semanticStatus || "").trim().toLowerCase();
  return ["failed", "error"].includes(status) || semanticStatus === "failed";
}

function isSuccessfulToolCall(toolCall: ToolCall) {
  const status = String(toolCall.status || "").trim().toLowerCase();
  const semanticStatus = String(toolCall.semanticStatus || "").trim().toLowerCase();
  return ["done", "completed", "succeeded", "success"].includes(status)
    && semanticStatus !== "failed";
}

function toolCallIdentity(toolCall: ToolCall) {
  return String(toolCall.rawToolName || toolCall.name || toolCall.title || "").trim();
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
    .flatMap((message) => message.toolCalls ?? [])
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
