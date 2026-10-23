import { describe, expect, it } from "vitest";
import type { SessionDetail } from "../../api/types";
import { resolveConversationContinuation } from "./conversationContinuationModel";

const stopped = {
  id: "session-a", agentId: "agent-a", activeLeafId: "head-a", ledgerSeq: 12,
  lastTurnTerminalTurnId: "turn-a", lastTurnStatus: "stopped_by_user",
  terminalReason: "stopped_by_user", currentPhase: "ready", activeTurnId: "",
} as SessionDetail;

describe("conversation continuation eligibility", () => {
  it.each(["stopped_by_user", "needs_continue", "paused_limit"])("offers the exact snapshot for %s", (terminalReason) => {
    expect(resolveConversationContinuation({ ...stopped, terminalReason }, "session-a"))
      .toEqual({ turnId: "turn-a", headId: "head-a", ledgerSeq: 12, agentId: "agent-a" });
  });
  it("offers an iteration-limit stop only for the same latest terminal turn", () => {
    const detail = { ...stopped, terminalReason: "failed_runtime", lastTurnError: { reasonCode: "iteration_limit_reached", turnId: "turn-a" } } as SessionDetail;
    expect(resolveConversationContinuation(detail, "session-a")).not.toBeNull();
    expect(resolveConversationContinuation({ ...detail, lastTurnError: { ...detail.lastTurnError!, turnId: "old-turn" } }, "session-a")).toBeNull();
    expect(resolveConversationContinuation({ ...detail, terminalReason: "success" }, "session-a")).toBeNull();
  });
  it.each([
    { readOnly: true }, { agentDirectSessionMismatch: true }, { selectedLightweight: true }, { provisionalTranscript: true },
    { activeTurnId: "new-turn" }, { stopRequested: true }, { currentPhase: "thinking" },
    { terminalReason: "success" }, { terminalReason: "failed_provider" }, { terminalReason: "failed_runtime" },
    { ledgerSeq: 0 }, { activeLeafId: "" }, { agentId: "" },
    { queuedTurns: [{ id: "queued" }] },
  ])("does not offer Play for an unsafe or unavailable snapshot %j", (patch) => {
    expect(resolveConversationContinuation({ ...stopped, ...patch } as SessionDetail, "session-a")).toBeNull();
  });
  it("never borrows eligibility from another selected session", () => {
    expect(resolveConversationContinuation(stopped, "session-b")).toBeNull();
    expect(resolveConversationContinuation(undefined, "session-a")).toBeNull();
  });
});
