import type { RuntimeSummary, WorkRunSnapshot } from "../../api/types/runtime";

const CHAT_TURN_SESSION_KEYS = [
  "sessionId",
  "sourceSessionId",
  "conversationId",
  "directSessionId",
] as const;

function textField(record: Record<string, unknown>, keys: readonly string[]) {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value) {
      return value;
    }
  }
  return "";
}

function snapshotMatchesChatTurn(
  run: WorkRunSnapshot | null | undefined,
  match: { sessionId: string; turnId?: string },
) {
  if (!run) {
    return false;
  }
  const record = run as unknown as Record<string, unknown>;
  const sessionId = textField(record, CHAT_TURN_SESSION_KEYS);
  if (!sessionId || sessionId !== match.sessionId) {
    return false;
  }
  if (!match.turnId) {
    return true;
  }
  const turnId = textField(record, ["turnId", "activeTurnId"]);
  return !turnId || turnId === match.turnId;
}

/**
 * Drop a stopped chat turn from the runtime active-work snapshot so the shell
 * indicator clears at stop time instead of waiting for the next summary poll.
 */
export function removeChatTurnFromRuntimeSummary(
  summary: RuntimeSummary | undefined,
  match: { sessionId: string; turnId?: string },
): RuntimeSummary | undefined {
  const workRuns = summary?.workRuns;
  if (!summary || !workRuns) {
    return summary;
  }
  const active = workRuns.active;
  const items = workRuns.activeItems;
  const currentActiveChatTurn = active?.chat_turn ?? null;
  const nextActiveChatTurn = snapshotMatchesChatTurn(currentActiveChatTurn, match)
    ? null
    : currentActiveChatTurn;
  const currentChatItems = items?.chat_turn;
  const nextChatItems = currentChatItems?.some((run) => snapshotMatchesChatTurn(run, match))
    ? currentChatItems.filter((run) => !snapshotMatchesChatTurn(run, match))
    : currentChatItems;
  if (nextActiveChatTurn === currentActiveChatTurn && nextChatItems === currentChatItems) {
    return summary;
  }
  return {
    ...summary,
    workRuns: {
      ...workRuns,
      active: active ? { ...active, chat_turn: nextActiveChatTurn } : active,
      ...(items && nextChatItems ? { activeItems: { ...items, chat_turn: nextChatItems } } : {}),
    },
  };
}
