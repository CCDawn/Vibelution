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
