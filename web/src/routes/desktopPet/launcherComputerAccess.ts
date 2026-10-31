import type { SessionDetail } from "../../api/types";
import type { ComputerAuthorizationRequest } from "../../api/types/personalAssistantComputer";
import { resolveSessionActivity } from "../sessionActivityState";

const tools = new Set(["personal_assistant_computer_observe_tool"]);

/** Only native tool metadata is used. Tool prose and old transcript text cannot request access. */
export function latestComputerTurn(detail: SessionDetail | undefined): string {
  if (!detail || detail.provisionalTranscript || detail.selectedLightweight || detail.editResubmitProtection
    || detail.queuedTurns?.length) return "";
  const message = detail.messages.at(-1);
  if (!message || message.role !== "assistant" || !message.turnId) return "";
  if (detail.activeTurnId !== message.turnId && detail.lastTurnTerminalTurnId !== message.turnId) return "";
  const activity = resolveSessionActivity(detail);
  if (detail.activeTurnId === message.turnId ? activity.execution !== "running" : activity.outcome !== "completed") return "";
  return message.turnItems?.some(item => item.type === "tool_call" && item.sessionId === detail.id
    && item.turnId === message.turnId && tools.has(item.toolName || "")) ? message.turnId : "";
}

export function computerAccessMatches(request: ComputerAuthorizationRequest | null | undefined, detail: SessionDetail | undefined, agentId: string): boolean {
  return Boolean(request && detail && request.agentId === agentId && detail.agentId === agentId && request.sessionId === detail.id
    && request.turnId === latestComputerTurn(detail));
}
