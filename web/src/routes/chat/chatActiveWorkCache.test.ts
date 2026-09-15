import { describe, expect, it } from "vitest";

import type { RuntimeSummary } from "../../api/types/runtime";
import { removeChatTurnFromRuntimeSummary } from "./chatActiveWorkCache";

function runtimeSummaryWithChatTurns(turns: Array<Record<string, unknown>>) {
  return {
    workRuns: {
      active: {
        chat_turn: turns[0] ?? null,
        chat_room_round: null,
        self_evolution_run: null,
        supervised_evolution_run: null,
        supervised_worktree_evolution_run: null,
      },
      activeItems: { chat_turn: turns },
      latest: {
        chat_turn: null,
        chat_room_round: null,
        self_evolution_run: null,
        supervised_evolution_run: null,
        supervised_worktree_evolution_run: null,
      },
    },
  } as unknown as RuntimeSummary;
}

describe("removeChatTurnFromRuntimeSummary", () => {
  it("drops the stopped chat turn immediately and keeps other active work", () => {
    const summary = runtimeSummaryWithChatTurns([
      { sessionId: "session-stopped", turnId: "turn-1" },
      { sessionId: "session-other", turnId: "turn-2" },
    ]);

    const next = removeChatTurnFromRuntimeSummary(summary, {
      sessionId: "session-stopped",
      turnId: "turn-1",
    });

    const workRuns = next?.workRuns;
    expect(workRuns?.active.chat_turn).toBeNull();
    expect(workRuns?.activeItems?.chat_turn).toEqual([
      { sessionId: "session-other", turnId: "turn-2" },
    ]);
    expect(summary.workRuns.active.chat_turn).toEqual({ sessionId: "session-stopped", turnId: "turn-1" });
  });

  it("returns the same snapshot when nothing matches", () => {
    const summary = runtimeSummaryWithChatTurns([{ sessionId: "session-other", turnId: "turn-2" }]);

    const next = removeChatTurnFromRuntimeSummary(summary, {
      sessionId: "session-stopped",
      turnId: "turn-1",
    });

    expect(next).toBe(summary);
  });

  it("matches alternate session keys used by supervised runs", () => {
    const summary = runtimeSummaryWithChatTurns([{ sourceSessionId: "session-supervised" }]);

    const next = removeChatTurnFromRuntimeSummary(summary, { sessionId: "session-supervised" });

    expect(next?.workRuns.activeItems?.chat_turn).toEqual([]);
    expect(next?.workRuns.active.chat_turn).toBeNull();
  });
});
