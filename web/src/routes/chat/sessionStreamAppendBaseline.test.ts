// @vitest-environment happy-dom
import { describe, expect, it, vi } from "vitest";
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient } from "@tanstack/react-query";
import { queryKeys } from "../../api/queryKeys";
import { useSessionDetailStream, type UseSessionDetailStreamOptions } from "./useSessionDetailStream";
import { disposeSessionStreams } from "./sessionStreamWarmRegistry";

vi.mock("../../app/browserTelemetry", () => ({
  collectBrowserPageSnapshot: () => ({}), postBrowserTelemetry: vi.fn(),
}));
import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import { reconcileActiveTurnLayerItemsWithMessages, type ActiveTurnLayerState } from "../chatActiveTurnLayer";
import { createSessionStreamAppendReassembler } from "../chatSessionStreamProtocol";
import { sessionStreamAppendBaseline } from "./sessionStreamAppendBaseline";

const reasoning: SessionTurnItem = {
  version: 3, id: "r:1", itemId: "r", sessionId: "s1", turnId: "t1",
  type: "reasoning", status: "running", revision: 1, sequence: 1, text: "abc",
};
const answer: SessionTurnItem = {
  version: 3, id: "a:1", itemId: "a", sessionId: "s1", turnId: "t1",
  type: "agent_message", phase: "final_answer", status: "running", revision: 1, sequence: 2, text: "answer",
};
const message: ConversationMessage = {
  id: "live", role: "assistant", turnId: "t1", status: "running", timestamp: "2026-01-01T00:00:00Z",
  turnItems: [reasoning],
};
const layer: ActiveTurnLayerState = {
  id: "active", sessionId: "s1", turnId: "t1", updatedAt: "2026-01-01T00:00:00Z",
  status: "running", ledgerSeq: 2, turnItems: [reasoning, answer],
};

describe("sessionStreamAppendBaseline", () => {
  it("retains reconciled detail items for legal appends and still reports a real gap", () => {
    const residual = reconcileActiveTurnLayerItemsWithMessages(layer, [message]);
    expect(residual?.turnItems.map((item) => item.itemId)).toEqual(["a"]);
    const decoder = createSessionStreamAppendReassembler();
    decoder.rebase("s1", "t1", sessionStreamAppendBaseline("s1", "t1", [reasoning], residual?.turnItems));
    const event = {
      type: "assistant_delta" as const, sessionId: "s1", turnId: "t1", ledgerSeq: 3,
      stage: "responding", turnItems: [], updatedAt: "2026-01-01T00:00:01Z", done: false,
      turnItemAppends: [{ kind: "append" as const, itemId: "r", itemType: "reasoning" as const,
        baseLength: 3, appendedLength: 1, appendedText: "d" }],
    };
    const expanded = decoder.expand(event);
    expect(expanded.gaps).toEqual([]);
    expect(expanded.payload.turnItems[0]).toMatchObject({ itemId: "r", text: "abcd" });
    expect(decoder.expand(event).gaps).toEqual([{ itemId: "r", baseLength: 3, reason: "length_mismatch" }]);
    decoder.rebase("s1", "t1", sessionStreamAppendBaseline("s1", "t1", [{ ...reasoning, revision: 2, text: "abcd" }]));
    const recovered = decoder.expand({
      ...event, turnItemAppends: [{ ...event.turnItemAppends[0], baseLength: 4, appendedText: "e" }],
    });
    expect(recovered.gaps).toEqual([]);
    expect(recovered.payload.turnItems[0]).toMatchObject({ itemId: "r", text: "abcde" });
  });

  it("selects the newest item revision and rejects other sessions or turns", () => {
    const newer = { ...reasoning, revision: 2, text: "abcd" };
    const wrongSession = { ...reasoning, sessionId: "s2", itemId: "foreign" };
    const wrongTurn = { ...reasoning, turnId: "t2", itemId: "other-turn" };
    expect(sessionStreamAppendBaseline("s1", "t1", [reasoning, wrongSession, wrongTurn], [newer, answer]))
      .toEqual([newer, answer]);
    expect(sessionStreamAppendBaseline("s1", "t1", [newer], [reasoning]))
      .toEqual([newer]);
  });
});


it.each([true, false])("keeps committed append progress across two details while the React ref is stale (existing layer: %s)", (hasRenderedLayer) => {
  vi.useFakeTimers();
  const queryClient = new QueryClient();
  const detail = {
    id: "s1", ledgerSeq: 2, activeTurnId: "t1", currentPhase: "running",
    messages: [message],
  };
  queryClient.setQueryData(queryKeys.session("s1"), detail);
  const listeners = new Map<string, Set<(event: { data: string }) => void>>();
  const stream = {
    readyState: 1,
    onopen: null,
    onerror: null,
    close: vi.fn(),
    addEventListener: (type: string, cb: (event: { data: string }) => void) => {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type)!.add(cb);
    },
    removeEventListener: (type: string, cb: (event: { data: string }) => void) => listeners.get(type)?.delete(cb),
  };
  const emit = (type: string, payload: unknown) => {
    for (const cb of listeners.get(type) ?? []) cb({ data: JSON.stringify(payload) });
  };
  const notify = vi.fn();
  const options = {
    activeSessionId: "s1", sessionStreamShouldConnect: true, queryClient,
    syncSessionDetail: (value: unknown) => queryClient.setQueryData(queryKeys.session("s1"), value),
    setActiveTurnLayersBySession: vi.fn(),
    activeTurnLayersBySessionRef: { current: hasRenderedLayer ? { s1: { ...layer, turnItems: [reasoning] } } : {} },
    lastAssistantDeltaAppliedAtRef: { current: {} }, lastStreamActivityAppliedAtRef: { current: {} },
    sessionStreamDecisionSnapshotRef: { current: { sessionId: "s1", shouldConnect: true } },
    desktopConversationNotifierRef: { current: { handleSessionDetail: vi.fn(), handleAssistantDelta: notify } },
    createSessionEventStream: () => stream,
    sessionTitleForNotifications: "test",
  } as unknown as UseSessionDetailStreamOptions;
  const host = document.createElement("div");
  const root = createRoot(host);
  function Host() { useSessionDetailStream(options); return null; }
  const delta = (baseLength: number, appendedText: string) => ({
    type: "assistant_delta", sessionId: "s1", turnId: "t1", ledgerSeq: 2, stage: "responding",
    turnItems: [], turnItemAppends: [{ kind: "append", itemId: "r", itemType: "reasoning",
      baseLength, appendedLength: appendedText.length, appendedText }],
    updatedAt: "2026-01-01T00:00:01Z", done: false,
  });
  try {
    act(() => root.render(React.createElement(Host)));
    act(() => { emit("assistant_delta", delta(3, "d")); vi.advanceTimersByTime(64); });
    expect(stream.close).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledTimes(1);
    for (let index = 0; index < 2; index += 1) {
      act(() => {
        emit("session_detail", { type: "session_detail", sessionId: "s1", ledgerSeq: 2, detail });
        vi.advanceTimersByTime(400);
      });
    }
    expect(options.desktopConversationNotifierRef.current.handleSessionDetail).toHaveBeenCalledTimes(2);
    act(() => { emit("assistant_delta", delta(4, "e")); vi.advanceTimersByTime(64); });
    expect(stream.close).not.toHaveBeenCalled();
    expect(notify).toHaveBeenCalledTimes(2);
    expect(notify.mock.calls[1][0].turnItems[0]).toMatchObject({ text: "abcde" });
  } finally {
    act(() => root.unmount());
    disposeSessionStreams();
    vi.useRealTimers();
  }
});
