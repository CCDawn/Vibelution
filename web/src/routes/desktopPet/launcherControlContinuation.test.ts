import { describe, expect, it } from "vitest";
import type { SessionDetail } from "../../api/types";
import { CONTROL_CONTINUATION_MESSAGE, launcherControlOrigin, launcherControlSubmission, type LauncherControlContext } from "./launcherControlContinuation";

const detail = (): SessionDetail => ({ id: "s", agentId: "a", status: "ready", terminalReason: "success",
  lastTurnTerminalTurnId: "t", ledgerSeq: 10, activeLeafId: "h", activeBranchId: "b",
  messages: [{ id: "u", role: "user", metadata: { turnId: "t" } }, { id: "answer", role: "assistant", turnId: "t", turnItems: [] }],
} as SessionDetail);
const context = (patch: Partial<SessionDetail> = {}): LauncherControlContext => ({ detail: { ...detail(), ...patch }, agentId: "a", blocked: false });
const intent = () => ({ origin: launcherControlOrigin(context())!, requestId: "request", toolIds: [], pendingToolIds: [] });

describe("explicit operator continuation", () => {
  it("creates one fixed native send preserving the unrelated composer", () => {
    expect(launcherControlSubmission(intent(), context())).toEqual({ state: "ready", submission: {
      message: CONTROL_CONTINUATION_MESSAGE, requestId: "request", preserveDraft: true,
      controlContinuation: { agentId: "a", sessionId: "s", turnId: "t", headId: "h", ledgerSeq: 10 },
    } });
  });
  it("waits only for the captured turn's natural completion, then uses its settled cursor", () => {
    const running = context({ status: "running", activeTurnId: "t", terminalReason: "", lastTurnTerminalTurnId: "old" });
    const captured = { origin: launcherControlOrigin(running)!, requestId: "request", toolIds: [], pendingToolIds: [] };
    expect(launcherControlSubmission(captured, running)).toEqual({ state: "waiting" });
    expect(launcherControlSubmission(captured, context({ ledgerSeq: 20, activeLeafId: "settled" }))).toMatchObject({ state: "ready", submission: { controlContinuation: { headId: "settled", ledgerSeq: 20 } } });
  });
  it.each(["stopped", "cancelled", "failed", "unknown", "superseded"])("never resumes a %s task", terminalReason => {
    expect(launcherControlSubmission(intent(), context({ terminalReason }))).toEqual({ state: "stale" });
  });
  it("cancels on a changed identity, branch, user instruction, pending question or queue hold", () => {
    for (const patch of [{ id: "other" }, { agentId: "other" }, { activeBranchId: "other" },
      { messages: [...detail().messages, { id: "new", role: "user", turnId: "next" }] },
      { pendingQuestion: {} }, { queueHold: {} }, { queuedTurns: [{}] }, { provisionalTranscript: true },
      { selectedLightweight: true }, { editResubmitProtection: {} }]) {
      expect(launcherControlSubmission(intent(), context(patch as Partial<SessionDetail>))).toEqual({ state: "stale" });
    }
    expect(launcherControlSubmission(intent(), { ...context(), blocked: true })).toEqual({ state: "stale" });
  });
  it("requires the actual journal cursor and user turn metadata", () => {
    for (const patch of [{ activeLeafId: "" }, { ledgerSeq: 0 }, { ledgerSeq: NaN },
      { messages: [{ ...detail().messages[0], metadata: {} }, detail().messages[1]] }]) {
      expect(launcherControlSubmission(intent(), context(patch))).toEqual({ state: "stale" });
    }
  });
  it("uses logical tool identity so a denied observe's final revision can still continue", () => {
    const source = context({ messages: [detail().messages[0], { ...detail().messages[1], turnItems: [
      { id: "revision-2", itemId: "observe", type: "tool_call", sessionId: "s", turnId: "t", status: "failed" } as never,
    ] }] });
    expect(launcherControlSubmission({ ...intent(), toolIds: ["observe"] }, source).state).toBe("ready");
  });
  it("consumes an in-flight tool's successful result while retaining an exact authorization denial", () => {
    const tool = { id: "observe.rev2", itemId: "observe", type: "tool_call", toolName: "personal_assistant_computer_observe_tool",
      sessionId: "s", turnId: "t", status: "completed", output: JSON.stringify({ ok: true }) };
    const source = context({ messages: [detail().messages[0], { ...detail().messages[1], turnItems: [tool as never] }] });
    const captured = { ...intent(), toolIds: ["observe"], pendingToolIds: ["observe"] };
    expect(launcherControlSubmission(captured, source).state).toBe("stale");
    tool.output = JSON.stringify({ ok: false, status: "blocked", reason: "authorization_required" });
    expect(launcherControlSubmission(captured, source).state).toBe("ready");
  });
});
