import React from "react";
import { renderToString } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { SessionDetail } from "../../api/types";
import { useChatComposerBridgeState, type ChatComposerBridgeStateResult } from "./useChatComposerBridgeState";

function composer(patch: Partial<SessionDetail>, draft = "") {
  let result!: ChatComposerBridgeStateResult;
  function Probe() {
    result = useChatComposerBridgeState({
      activeSessionId: "s", sessionDrafts: { s: draft }, sessionFollowupQueues: {}, sessionComposerErrors: {},
      sessionEditTargets: {}, sessionImageAttachments: {}, sessionReferenceAttachments: {}, sessionImageUploadPending: {},
      detail: { id: "s", status: "ready", currentPhase: "ready", messages: [], ...patch } as SessionDetail,
      agents: [], modelImageInputSupportById: new Map(), lang: "zh", t: (key) => key,
      submitTurnMutation: { isPending: false }, editResubmitMutation: { isPending: false },
      regenerateMutation: { isPending: false }, stopTurnMutation: { isPending: false },
      sessionGuidanceMutation: { isPending: false }, continueEnabled: true,
    });
    return null;
  }
  renderToString(<Probe />);
  return result;
}

describe("composer consumes the Session ownership contract", () => {
  it("keeps paused execution owned while allowing draft editing", () => {
    const state = composer({ status: "paused", currentPhase: "thinking", terminalReason: "success" }, "draft");
    expect(state.sessionBusy).toBe(true);
    expect(state.sessionRunning).toBe(false);
    expect(state.conversationComposer.disabled).toBe(false);
    expect(state.conversationComposer.actionMode).toBe("stop");
  });
  it("uses live status even when currentPhase is still ready", () => {
    expect(composer({ status: "running", currentPhase: "ready", terminalReason: "success" }).sessionBusy).toBe(true);
  });
  it("offers continuation only after the current turn is settled", () => {
    const snapshot = { agentId: "a", activeLeafId: "h", ledgerSeq: 10, lastTurnTerminalTurnId: "t", terminalReason: "needs_continue" };
    expect(composer(snapshot).conversationComposer.actionMode).toBe("continue");
    expect(composer({ ...snapshot, status: "paused" }).conversationComposer.actionMode).toBe("stop");
  });
  it("releases the exact committed owner and preserves a new owner", () => {
    const terminal = { activeTurnId: "t", lastTurnTerminalTurnId: "t", terminalReason: "stopped_by_user" };
    expect(composer(terminal, "next").conversationComposer.actionMode).toBe("send");
    expect(composer({ ...terminal, activeTurnId: "next" }).sessionBusy).toBe(true);
  });
});

describe("guidance delivery notice is a one-shot receipt", () => {
  function noticeComposer(
    patch: Partial<SessionDetail>,
    guidance: {
      isSuccess?: boolean;
      data?: SessionDetail;
      variables?: { sessionId?: string; mode?: "safe" | "interrupt" };
      dataUpdatedAt?: number;
    },
  ) {
    let result!: ChatComposerBridgeStateResult;
    function Probe() {
      result = useChatComposerBridgeState({
        activeSessionId: "s",
        sessionDrafts: { s: "" },
        sessionFollowupQueues: {},
        sessionComposerErrors: {},
        sessionEditTargets: {},
        sessionImageAttachments: {},
        sessionReferenceAttachments: {},
        sessionImageUploadPending: {},
        detail: { id: "s", status: "ready", currentPhase: "ready", messages: [], ...patch } as SessionDetail,
        agents: [],
        modelImageInputSupportById: new Map(),
        lang: "zh",
        t: (key) => key,
        submitTurnMutation: { isPending: false },
        editResubmitMutation: { isPending: false },
        regenerateMutation: { isPending: false },
        stopTurnMutation: { isPending: false },
        sessionGuidanceMutation: { isPending: false, ...guidance },
        continueEnabled: true,
      });
      return null;
    }
    renderToString(<Probe />);
    return result;
  }

  const receipt = {
    isSuccess: true,
    data: { guidanceDelivery: "guide" } as SessionDetail,
    variables: { sessionId: "s", mode: "safe" as const },
    dataUpdatedAt: Date.now(),
  };

  it("shows the receipt while the submitting turn still runs", () => {
    const state = noticeComposer({ status: "running", activeTurnId: "t", currentPhase: "ready" }, receipt);
    expect(state.conversationComposer.guidance).toContain("已插入当前 turn");
  });

  it("drops the receipt once the turn settled", () => {
    const state = noticeComposer({ status: "ready", currentPhase: "ready" }, receipt);
    expect(state.conversationComposer.guidance).not.toContain("已插入当前 turn");
  });

  it("does not carry the receipt into another session", () => {
    const state = noticeComposer(
      { status: "running", activeTurnId: "t", currentPhase: "ready" },
      { ...receipt, variables: { sessionId: "other", mode: "safe" } },
    );
    expect(state.conversationComposer.guidance).not.toContain("已插入当前 turn");
  });

  it("expires the receipt after the one-shot window", () => {
    const state = noticeComposer(
      { status: "running", activeTurnId: "t", currentPhase: "ready" },
      { ...receipt, dataUpdatedAt: Date.now() - 20_000 },
    );
    expect(state.conversationComposer.guidance).not.toContain("已插入当前 turn");
  });
});
