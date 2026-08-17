import { describe, expect, it } from "vitest";

import type { RuntimeSummary } from "../../api/types";
import {
  chatTurnSessionIdsFromRuntime,
  runtimeHasChatTurnForSession,
} from "./chatRuntimeWorkRuns";

function runtimeWithTurns(sessionIds: string[], activeSessionId?: string): Pick<RuntimeSummary, "workRuns"> {
  return {
    workRuns: {
      active: {
        chat_turn: activeSessionId
          ? { sessionId: activeSessionId, runId: "slot", runKind: "chat_turn", status: "running", leases: [] }
          : null,
        chat_room_round: null,
        self_evolution_run: null,
        supervised_evolution_run: null,
        supervised_worktree_evolution_run: null,
      },
      activeItems: {
        chat_turn: sessionIds.map((sessionId) => ({
          sessionId,
          runId: `run-${sessionId}`,
          runKind: "chat_turn",
          status: "running",
          leases: [],
        })),
      },
      latest: {
        chat_turn: null,
        chat_room_round: null,
        self_evolution_run: null,
        supervised_evolution_run: null,
        supervised_worktree_evolution_run: null,
      },
    },
  };
}

describe("chatRuntimeWorkRuns", () => {
  it("uses activeItems in stable id order and ignores the single active slot", () => {
    const runtime = runtimeWithTurns(["session-b", "session-a"], "session-b");
    expect(chatTurnSessionIdsFromRuntime(runtime)).toEqual(["session-a", "session-b"]);
    expect(runtimeHasChatTurnForSession(runtime, "session-a")).toBe(true);
    expect(runtimeHasChatTurnForSession(runtime, "session-missing")).toBe(false);
  });

  it("does not treat the single active slot as the only running session", () => {
    const runtime = runtimeWithTurns(["session-a", "session-b"], "session-b");
    expect(runtimeHasChatTurnForSession(runtime, "session-a")).toBe(true);
    expect(chatTurnSessionIdsFromRuntime(runtime)[0]).toBe("session-a");
  });
});
