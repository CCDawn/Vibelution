import type { RuntimeSummary } from "../../api/types";

/**
 * Live chat turns from runtime summary. `workRuns.active.chat_turn` is a
 * single slot and must not decide which session looks selected or running.
 */
export function chatTurnSessionIdsFromRuntime(
  runtime: Pick<RuntimeSummary, "workRuns"> | null | undefined,
): string[] {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const run of runtime?.workRuns?.activeItems?.chat_turn ?? []) {
    const sessionId = String(run?.sessionId ?? "").trim();
    if (!sessionId || seen.has(sessionId)) {
      continue;
    }
    seen.add(sessionId);
    ids.push(sessionId);
  }
  ids.sort((left, right) => left.localeCompare(right));
  return ids;
}

export function runtimeHasChatTurnForSession(
  runtime: Pick<RuntimeSummary, "workRuns"> | null | undefined,
  sessionId: string | null | undefined,
): boolean {
  const normalizedSessionId = String(sessionId ?? "").trim();
  if (!normalizedSessionId) {
    return false;
  }
  return chatTurnSessionIdsFromRuntime(runtime).includes(normalizedSessionId);
}
