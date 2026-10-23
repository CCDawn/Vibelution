// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionSummary } from "../../api/types";
import { createDesktopConversationNotifier } from "../chatDesktopNotifications";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";
import { useDesktopConversationAttention } from "./useDesktopConversationAttention";

vi.mock("./chatSessionDetailHelpers", () => ({ fetchSessionDetailWindow: vi.fn() }));

function settled(turnId: string): SessionDetail {
  return {
    id: "background", title: "后台会话", currentPhase: "ready", status: "ready", terminalReason: "success",
    messages: [{ id: turnId, turnId, role: "assistant", status: "completed", turnItems: [{ type: "agent_message", text: "Done" }] }],
  } as SessionDetail;
}

describe("background conversation completion", () => {
  it.each([false, true])("fetches the real completed turn with old cache=%s and keeps the session identity", async (oldCache) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    if (oldCache) client.setQueryData(queryKeys.session("background"), settled("previous-turn"));
    const fetchDetail = vi.mocked(fetchSessionDetailWindow);
    fetchDetail.mockReset();
    fetchDetail.mockResolvedValue(settled("new-turn"));
    const notify = vi.fn(async () => undefined);
    const notifierRef = { current: createDesktopConversationNotifier({ bridge: { notifyConversationCompleted: notify }, postTelemetry: vi.fn() }) };
    const element = document.createElement("div");
    const root = createRoot(element);
    function Harness({ status }: { status: string }) {
      useDesktopConversationAttention({
        sessions: [{ id: "background", title: "后台会话", status, currentPhase: status }] as SessionSummary[],
        queryClient: client, viewedSessionId: "viewed-other", notifierRef, onOpenSession: vi.fn(),
      });
      return null;
    }
    try {
      await act(async () => { root.render(<Harness status="running" />); });
      expect(fetchDetail).not.toHaveBeenCalled();
      await act(async () => { root.render(<Harness status="ready" />); });
      expect(fetchDetail).toHaveBeenCalledTimes(1);
      expect(notify).toHaveBeenCalledWith(expect.objectContaining({
        sessionId: "background", turnId: "new-turn", sessionLabel: "后台会话", suppressWhenFocused: false,
      }));
      await act(async () => { root.render(<Harness status="ready" />); });
      expect(fetchDetail).toHaveBeenCalledTimes(1);
      expect(notify).toHaveBeenCalledTimes(1);

      fetchDetail.mockResolvedValue(settled("next-turn"));
      await act(async () => { root.render(<Harness status="running" />); });
      await act(async () => { root.render(<Harness status="ready" />); });
      expect(notify).toHaveBeenCalledTimes(2);
      expect(notify).toHaveBeenLastCalledWith(expect.objectContaining({ turnId: "next-turn" }));
    } finally {
      await act(async () => { root.unmount(); });
      client.clear();
    }
  });
});

describe("viewed conversation query completion", () => {
  function harness() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.mocked(fetchSessionDetailWindow).mockReset();
    const notify = vi.fn(async () => undefined);
    const notifierRef = { current: createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify }, postTelemetry: vi.fn(),
    }) };
    const root = createRoot(document.createElement("div"));
    function Harness({ detail, enabled }: { detail: SessionDetail; enabled: boolean }) {
      useDesktopConversationAttention({
        sessions: [], queryClient: client, viewedSessionId: "viewed", viewedSessionDetail: detail,
        viewedSessionDetailEnabled: enabled,
        notifierRef, onOpenSession: vi.fn(),
      });
      return null;
    }
    return {
      notify, notifier: notifierRef.current,
      render: async (detail: SessionDetail, enabled = true) => { await act(async () => { root.render(<Harness detail={detail} enabled={enabled} />); }); },
      close: async () => { await act(async () => { root.unmount(); }); client.clear(); },
    };
  }

  function viewed(turnId: string, patch: Partial<SessionDetail> = {}): SessionDetail {
    return { ...settled(turnId), id: "viewed", lastTurnTerminalTurnId: turnId, ...patch };
  }

  it("notifies query-only continuation and success, then deduplicates late stream events", async () => {
    const h = harness();
    try {
      await h.render(viewed("first", { status: "running", currentPhase: "running", terminalReason: "running", activeTurnId: "first" }));
      await h.render(viewed("first", { status: "needs_continue", currentPhase: "needs_continue", terminalReason: "needs_continue", activeTurnId: "" }));
      expect(h.notify).toHaveBeenCalledTimes(1);
      expect(h.notify).toHaveBeenLastCalledWith(expect.objectContaining({ turnId: "first", terminalStatus: "needs_continue" }));

      await h.render(viewed("first", { status: "running", currentPhase: "running", terminalReason: "needs_continue", activeTurnId: "second" }));
      const completed = viewed("second", { activeTurnId: "" });
      await h.render(completed);
      expect(h.notify).toHaveBeenCalledTimes(2);
      expect(h.notify).toHaveBeenLastCalledWith(expect.objectContaining({ turnId: "second", terminalStatus: "completed" }));

      h.notifier.handleAssistantDelta({
        type: "assistant_delta", sessionId: "viewed", turnId: "second", done: true,
        stage: "responding", turnItems: [], updatedAt: "2026-10-23T14:00:00Z",
      });
      h.notifier.handleSessionDetail(completed);
      await h.render({ ...completed });
      expect(h.notify).toHaveBeenCalledTimes(2);
      expect(fetchSessionDetailWindow).not.toHaveBeenCalled();
    } finally { await h.close(); }
  });

  it("ignores initial history, provisional data and another session", async () => {
    const h = harness();
    try {
      await h.render(viewed("old-turn"));
      await h.render(viewed("future", { provisionalTranscript: true, status: "running", currentPhase: "running", activeTurnId: "future" }));
      await h.render(viewed("future"));
      await h.render(viewed("other", { id: "other", status: "running", currentPhase: "running", activeTurnId: "other" }));
      await h.render(viewed("another-old-turn"));
      expect(h.notify).not.toHaveBeenCalled();
    } finally { await h.close(); }
  });

  it("leaves Companion, unresolved or refetching identity on its existing attention path", async () => {
    const h = harness();
    try {
      await h.render(viewed("companion", { status: "running", currentPhase: "running", activeTurnId: "companion" }), false);
      await h.render(viewed("companion"), false);
      expect(h.notify).not.toHaveBeenCalled();
    } finally { await h.close(); }
  });

  it("delivers a pending ordinary completion when binding lookup becomes ready", async () => {
    const h = harness();
    try {
      await h.render(viewed("pending"), false);
      h.notifier.handleAssistantDelta({
        type: "assistant_delta", sessionId: "viewed", turnId: "pending", done: true,
        stage: "responding", turnItems: [], updatedAt: "2026-10-23T14:00:00Z",
      });
      await h.render(viewed("pending"));
      expect(h.notify).toHaveBeenCalledTimes(1);
      expect(h.notify).toHaveBeenLastCalledWith(expect.objectContaining({ turnId: "pending", terminalStatus: "completed" }));
    } finally { await h.close(); }
  });
});
