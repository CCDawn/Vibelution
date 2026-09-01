import { describe, expect, it, vi } from "vitest";

import type { SessionDetail, SessionStreamEvent } from "../api/types";
import {
  browserDesktopNotificationBridge,
  buildConversationNotificationCopy,
  createDesktopConversationNotifier,
  parseConversationNotificationOpenPayload,
  sanitizeSessionLabel,
  subscribeCompanionNotificationOpened,
  subscribeConversationNotificationOpened,
} from "./chatDesktopNotifications";

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
        turnId: "turn-1",
        status: "completed",
        timestamp: "2026-07-05T07:00:00Z",
        metadata: { turnId: "turn-1" },
        turnItems: [{ type: "agent_message", text: "final answer" }],
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
  it("emits once for a completed assistant delta and names the session", () => {
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

    notifier.handleAssistantDelta(assistantDelta(), {
      sessionTitle: "测试会话",
      viewedSessionId: "session-1",
    });
    notifier.handleAssistantDelta(assistantDelta(), {
      sessionTitle: "测试会话",
      viewedSessionId: "session-1",
    });

    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        schemaVersion: 1,
        notificationKey: "session-1:turn-1:completed",
        sessionId: "session-1",
        turnId: "turn-1",
        title: "对话已完成",
        body: "「测试会话」已完成一轮回复。",
        sessionLabel: "测试会话",
        suppressWhenFocused: true,
        terminalStatus: "completed",
      }),
    );
    expect(notify.mock.calls[0]?.[0]).not.toHaveProperty("companionAgentId");
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

  it("uses the last turn error id when a failed detail has no assistant message", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleSessionDetail(detail({ currentPhase: "running", status: "running", messages: [] }), {
      sessionTitle: "测试会话",
      viewedSessionId: "session-other",
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
      { sessionTitle: "测试会话", viewedSessionId: "session-other" },
    );

    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        notificationKey: "session-1:turn-error-1:failed",
        turnId: "turn-error-1",
        terminalStatus: "failed",
        title: "对话已结束",
        body: "「测试会话」对话已结束。",
        sessionLabel: "测试会话",
        suppressWhenFocused: false,
      }),
    );
    expect(JSON.stringify(notify.mock.calls[0]?.[0])).not.toContain("provider failed");
    expect(JSON.stringify(notify.mock.calls[0]?.[0])).not.toContain("C:\\hidden.txt");
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

  it("sanitizes sessionTitle so secrets and paths never appear in notification copy or telemetry", () => {
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
      body: "「from」已完成一轮回复。",
      sessionLabel: "from",
    });
    expect(JSON.stringify(notifyPayload)).not.toContain("sk-live-secret");
    expect(JSON.stringify(notifyPayload)).not.toContain("C:\\Users\\17533\\Desktop\\prompt.txt");
    expect(JSON.stringify(telemetryPayload)).not.toContain("sk-live-secret");
    expect(JSON.stringify(telemetryPayload)).not.toContain("C:\\Users\\17533\\Desktop\\prompt.txt");
  });

  it("notifies background session index busy-to-idle without duplicating the live stream", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleSessionSummaries(
      [
        { id: "session-bg", title: "后台会话", status: "running", currentPhase: "running", updatedAt: "t1" },
        { id: "session-1", title: "当前会话", status: "ready", currentPhase: "ready", updatedAt: "t0" },
      ],
      { viewedSessionId: "session-1" },
    );
    notifier.handleSessionSummaries(
      [
        { id: "session-bg", title: "后台会话", status: "ready", currentPhase: "ready", updatedAt: "t2" },
        { id: "session-1", title: "当前会话", status: "ready", currentPhase: "ready", updatedAt: "t0" },
      ],
      { viewedSessionId: "session-1" },
    );
    notifier.handleSessionDetail(detail({ id: "session-1", currentPhase: "running", status: "running" }), {
      viewedSessionId: "session-1",
    });
    notifier.handleSessionDetail(detail({ id: "session-1", currentPhase: "ready", status: "ready" }), {
      viewedSessionId: "session-1",
    });
    notifier.handleSessionSummaries(
      [
        { id: "session-bg", title: "后台会话", status: "ready", currentPhase: "ready", updatedAt: "t2" },
        { id: "session-1", title: "当前会话", status: "ready", currentPhase: "ready", updatedAt: "t3" },
      ],
      { viewedSessionId: "session-1" },
    );

    expect(notify).toHaveBeenCalledTimes(2);
    expect(notify).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        sessionId: "session-bg",
        body: "「后台会话」已完成一轮回复。",
        suppressWhenFocused: false,
      }),
    );
    expect(notify).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        sessionId: "session-1",
        notificationKey: "session-1:turn-1:completed",
        suppressWhenFocused: true,
      }),
    );
  });

  it("emits only once when live stream and session index both observe the viewed session finish", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleSessionSummaries(
      [{ id: "session-1", title: "当前会话", status: "running", currentPhase: "running", updatedAt: "t1" }],
      { viewedSessionId: "session-1", sessionTitle: "当前会话" },
    );
    notifier.handleAssistantDelta(assistantDelta(), {
      viewedSessionId: "session-1",
      sessionTitle: "当前会话",
    });
    notifier.handleSessionSummaries(
      [{ id: "session-1", title: "当前会话", status: "ready", currentPhase: "ready", updatedAt: "t2" }],
      { viewedSessionId: "session-1", sessionTitle: "当前会话" },
    );

    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "session-1",
        notificationKey: "session-1:turn-1:completed",
      }),
    );
  });

  it("does not notify idle sessions observed for the first time", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleSessionSummaries(
      [{ id: "session-idle", title: "旧会话", status: "ready", currentPhase: "ready", updatedAt: "t0" }],
      { viewedSessionId: "session-1" },
    );

    expect(notify).not.toHaveBeenCalled();
  });

  it("notifies a Companion when its native completion identity changes without a sampled busy phase", () => {
    const notify = vi.fn();
    const notifier = createDesktopConversationNotifier({
      bridge: { notifyConversationCompleted: notify },
      postTelemetry: vi.fn(),
    });

    notifier.handleSessionSummaries([
      {
        id: "session-nora",
        title: "Nora",
        status: "ready",
        currentPhase: "ready",
        companionAgentId: "agent-nora",
        completionIdentity: "completion-1",
      },
    ]);
    notifier.handleSessionSummaries([
      {
        id: "session-nora",
        title: "Nora",
        status: "ready",
        currentPhase: "ready",
        companionAgentId: "agent-nora",
        completionIdentity: "completion-2",
      },
    ]);

    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({
      notificationKey: "session-nora:completion-2:completed",
      sessionId: "session-nora",
      companionAgentId: "agent-nora",
      suppressWhenFocused: false,
    }));
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
      onConversationNotificationOpened: undefined,
    });
  });

  it("subscribes to notification click payloads and ignores unsafe session ids", () => {
    const opened: string[] = [];
    const listeners: Array<(payload: unknown) => void> = [];
    const unsubscribe = subscribeConversationNotificationOpened(
      {
        onConversationNotificationOpened: (listener) => {
          listeners.push(listener);
          return () => undefined;
        },
      },
      (sessionId) => opened.push(sessionId),
    );

    listeners[0]?.({ schemaVersion: 1, sessionId: "session-safe" });
    listeners[0]?.({ schemaVersion: 1, sessionId: "../etc/passwd" });
    listeners[0]?.({ schemaVersion: 1, sessionId: "https://evil.example" });
    unsubscribe();

    expect(opened).toEqual(["session-safe"]);
    expect(parseConversationNotificationOpenPayload({ schemaVersion: 1, sessionId: "session-safe" })).toEqual({
      schemaVersion: 1,
      sessionId: "session-safe",
    });
  });

  it("routes Companion notification clicks separately while preserving ordinary payloads", () => {
    const ordinaryOpened: string[] = [];
    const companionOpened: Array<{ sessionId: string; companionAgentId: string }> = [];
    const listeners: Array<(payload: unknown) => void> = [];
    const bridge = {
      onConversationNotificationOpened: (listener: (payload: unknown) => void) => {
        listeners.push(listener);
        return () => undefined;
      },
    };
    subscribeConversationNotificationOpened(bridge, (sessionId) => ordinaryOpened.push(sessionId));
    subscribeCompanionNotificationOpened(bridge, (payload) => companionOpened.push(payload));

    listeners.forEach((listener) => listener({ schemaVersion: 1, sessionId: "session-normal" }));
    listeners.forEach((listener) => listener({
      schemaVersion: 1,
      sessionId: "session-nora",
      companionAgentId: "agent-nora",
    }));
    listeners.forEach((listener) => listener({
      schemaVersion: 1,
      sessionId: "session-nora",
      companionAgentId: "../unsafe",
    }));

    expect(ordinaryOpened).toEqual(["session-normal"]);
    expect(companionOpened).toEqual([{
      sessionId: "session-nora",
      companionAgentId: "agent-nora",
    }]);
    expect(parseConversationNotificationOpenPayload({
      schemaVersion: 1,
      sessionId: "session-nora",
      companionAgentId: "agent-nora",
    })).toEqual({
      schemaVersion: 1,
      sessionId: "session-nora",
      companionAgentId: "agent-nora",
    });
  });
});

describe("session notification copy", () => {
  it("falls back to a short session id when the title sanitizes away", () => {
    expect(sanitizeSessionLabel("C:\\Users\\17533\\secret.txt", "session-abcd1234")).toBe("会话 abcd1234");
    expect(buildConversationNotificationCopy({ sessionLabel: "科研助手", terminalStatus: "completed" })).toEqual({
      title: "对话已完成",
      body: "「科研助手」已完成一轮回复。",
    });
  });
});
