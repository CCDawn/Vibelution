import { describe, expect, it, vi } from "vitest";

import type { SessionDetail, SessionStreamEvent } from "../api/types";
import { browserDesktopNotificationBridge, createDesktopConversationNotifier } from "./chatDesktopNotifications";

function assistantDelta(
  patch: Partial<Extract<SessionStreamEvent, { type: "assistant_delta" }>> = {},
): Extract<SessionStreamEvent, { type: "assistant_delta" }> {
  return {
    type: "assistant_delta",
    sessionId: "session-1",
    turnId: "turn-1",
    ledgerSeq: 3,
    stage: "responding",
    content: "final answer with local path C:\\secret.txt",
    thought: "internal chain of thought",
    updatedAt: "2026-07-05T07:00:00Z",
    done: true,
    ...patch,
  };
}

function detail(patch: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: "session-1",
    title: "测试会话",
    status: "ready",
    currentPhase: "ready",
    messages: [
      {
        id: "assistant-final",
        role: "assistant",
        content: "final answer with local path C:\\secret.txt",
        thought: "internal chain of thought",
        timestamp: "2026-07-05T07:00:00Z",
        metadata: { turnId: "turn-1" },
      },
    ],
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
    ...patch,
  } as SessionDetail;
}

describe("desktop conversation notifier", () => {
  it("emits once for a completed assistant delta", () => {
    const notify = vi.fn(async () => ({
      schemaVersion: 1,
      status: "notified",
      notificationKey: "session-1:turn-1:completed",
      unreadCount: 1,
      focused: false,
    }));
    const telemetry = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: telemetry,
    });

    notifier.handleAssistantDelta(assistantDelta(), { sessionTitle: "测试会话" });
    notifier.handleAssistantDelta(assistantDelta(), { sessionTitle: "测试会话" });

    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        schemaVersion: 1,
        notificationKey: "session-1:turn-1:completed",
        sessionId: "session-1",
        turnId: "turn-1",
        title: "对话已完成",
        body: "Vibelution 已完成一轮回复。",
        terminalStatus: "completed",
      }),
    );
    expect(telemetry).toHaveBeenCalledWith(
      expect.objectContaining({
        eventCode: "browser.desktop_notification.conversation_completed_emitted",
      }),
    );
  });

  it("does not emit for a non-final assistant delta", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleAssistantDelta(assistantDelta({ done: false }), { sessionTitle: "测试会话" });

    expect(notify).not.toHaveBeenCalled();
  });

  it("emits once for a detail transition from busy to ready", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleSessionDetail(detail({ currentPhase: "running", status: "running" }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(detail({ currentPhase: "ready", status: "ready" }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(detail({ currentPhase: "ready", status: "ready" }), { sessionTitle: "测试会话" });

    expect(notify).toHaveBeenCalledTimes(1);
  });

  it("emits once for a detail transition from busy to failed", () => {
    const notify = vi.fn();
    const telemetry = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: telemetry,
    });

    notifier.handleSessionDetail(detail({ currentPhase: "running", status: "running" }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(detail({ currentPhase: "failed", status: "failed" }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(detail({ currentPhase: "failed", status: "failed" }), { sessionTitle: "测试会话" });

    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        notificationKey: "session-1:turn-1:failed",
        terminalStatus: "failed",
      }),
    );
    expect(telemetry).toHaveBeenCalledWith(
      expect.objectContaining({
        eventCode: "browser.desktop_notification.conversation_completed_emitted",
      }),
    );
  });

  it("emits once for a detail transition from busy to interrupted", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleSessionDetail(detail({ currentPhase: "running", status: "running" }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(
      detail({
        currentPhase: "needs_continue",
        status: "needs_continue",
      }),
      { sessionTitle: "测试会话" },
    );
    notifier.handleSessionDetail(
      detail({
        currentPhase: "needs_continue",
        status: "needs_continue",
      }),
      { sessionTitle: "测试会话" },
    );

    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        notificationKey: "session-1:turn-1:needs_continue",
        terminalStatus: "needs_continue",
      }),
    );
  });

  it("uses the last turn error id when a failed detail has no assistant message", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleSessionDetail(detail({ currentPhase: "running", status: "running", messages: [] }), {
      sessionTitle: "测试会话",
    });
    notifier.handleSessionDetail(
      detail({
        currentPhase: "failed",
        status: "failed",
        messages: [],
        lastTurnError: {
          message: "provider failed with secret path C:\\hidden.txt",
          errorType: "ProviderError",
          recoverable: true,
          timestamp: "2026-07-05T07:00:00Z",
          turnId: "turn-error-1",
        },
      }),
      { sessionTitle: "测试会话" },
    );

    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        notificationKey: "session-1:turn-error-1:failed",
        turnId: "turn-error-1",
        terminalStatus: "failed",
        title: "对话已完成",
        body: "Vibelution 已完成一轮回复。",
      }),
    );
    expect(JSON.stringify(notify.mock.calls[0]?.[0])).not.toContain("provider failed");
    expect(JSON.stringify(notify.mock.calls[0]?.[0])).not.toContain("C:\\hidden.txt");
  });

  it("supports the route pattern of assistant delta final followed by final detail without duplicate notification", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleAssistantDelta(assistantDelta({ done: true }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(detail({ currentPhase: "running", status: "running" }), { sessionTitle: "测试会话" });
    notifier.handleSessionDetail(detail({ currentPhase: "ready", status: "ready" }), { sessionTitle: "测试会话" });

    expect(notify).toHaveBeenCalledTimes(1);
  });

  it("degrades to telemetry-only when the Electron bridge is missing", () => {
    const telemetry = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: undefined,
      postTelemetry: telemetry,
    });

    notifier.handleAssistantDelta(assistantDelta(), { sessionTitle: "测试会话" });

    expect(telemetry).toHaveBeenCalledWith(
      expect.objectContaining({
        eventCode: "browser.desktop_notification.conversation_completed_skipped",
      }),
    );
  });

  it("does not forward assistant content, thought, or paths into notification payload or telemetry", () => {
    const notify = vi.fn();
    const telemetry = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: telemetry,
    });

    notifier.handleAssistantDelta(
      assistantDelta({
        content: "answer body should stay private C:\\Users\\17533\\secret.txt",
        thought: "sensitive thought text",
      }),
      { sessionTitle: "测试会话" },
    );

    const notifyPayload = notify.mock.calls[0]?.[0];
    const telemetryPayload = telemetry.mock.calls[0]?.[0];

    expect(JSON.stringify(notifyPayload)).not.toContain("answer body should stay private");
    expect(JSON.stringify(notifyPayload)).not.toContain("sensitive thought text");
    expect(JSON.stringify(notifyPayload)).not.toContain("C:\\Users\\17533\\secret.txt");
    expect(JSON.stringify(telemetryPayload)).not.toContain("answer body should stay private");
    expect(JSON.stringify(telemetryPayload)).not.toContain("sensitive thought text");
    expect(JSON.stringify(telemetryPayload)).not.toContain("C:\\Users\\17533\\secret.txt");
  });

  it("uses generic safe notification copy even when sessionTitle contains secrets or paths", () => {
    const notify = vi.fn();
    const telemetry = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: telemetry,
    });
    const maliciousTitle = "sk-live-secret from C:\\Users\\17533\\Desktop\\prompt.txt";

    notifier.handleAssistantDelta(assistantDelta(), { sessionTitle: maliciousTitle });

    const notifyPayload = notify.mock.calls[0]?.[0];
    const telemetryPayload = telemetry.mock.calls[0]?.[0];

    expect(notifyPayload).toMatchObject({
      title: "对话已完成",
      body: "Vibelution 已完成一轮回复。",
    });
    expect(JSON.stringify(notifyPayload)).not.toContain("sk-live-secret");
    expect(JSON.stringify(notifyPayload)).not.toContain("C:\\Users\\17533\\Desktop\\prompt.txt");
    expect(JSON.stringify(telemetryPayload)).not.toContain("sk-live-secret");
    expect(JSON.stringify(telemetryPayload)).not.toContain("C:\\Users\\17533\\Desktop\\prompt.txt");
  });

  it("returns no bridge when the launcher API is unavailable", () => {
    expect(browserDesktopNotificationBridge({})).toBeUndefined();
    expect(browserDesktopNotificationBridge({ vibelutionLauncher: {} })).toBeUndefined();
  });

  it("returns the bridge when the launcher API exposes completion notifications", () => {
    const notifyConversationCompleted = vi.fn();

    expect(
      browserDesktopNotificationBridge({
        vibelutionLauncher: { notifyConversationCompleted },
      }),
    ).toEqual({
      notifyConversationCompleted,
    });
  });
});
