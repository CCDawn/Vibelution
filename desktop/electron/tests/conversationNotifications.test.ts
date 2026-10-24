import { describe, expect, it, vi } from "vitest";
import { createDesktopConversationNotifier } from "../../../web/src/routes/chatDesktopNotifications";
import {
  createConversationNotificationService,
  type DesktopConversationCompletionNotification
} from "../src/notifications/conversationNotifications.js";

const OPENED_CHANNEL = "launcher:conversation-notification-opened";

function completion(
  overrides: Partial<DesktopConversationCompletionNotification> = {}
): DesktopConversationCompletionNotification {
  return {
    schemaVersion: 1,
    notificationKey: "session-1:turn-1:completed",
    sessionId: "session-1",
    turnId: "turn-1",
    title: "对话已完成",
    body: "测试 Agent 已完成一轮回复。",
    sessionLabel: "测试会话",
    completedAt: "2026-07-05T07:00:00Z",
    terminalStatus: "completed",
    ...overrides
  };
}

function makeService(options: { focused?: boolean; notificationSupported?: boolean } = {}) {
  const notifications: Array<{ title: string; body: string; clicked: () => void; shown: boolean; nativeShown: () => void; nativeFailed: () => void }> = [];
  const workbenchMessages: Array<{ channel: string; payload: unknown }> = [];
  const recordEvent = vi.fn(async () => undefined);
  const provider = {
    isWorkbenchFocused: vi.fn(() => Boolean(options.focused)),
    focusWorkbench: vi.fn(async () => ({
      role: "workbench",
      provider: "electron",
      open: true,
      focused: true,
      windowId: 1,
      rendererProcessId: 2,
      url: "http://127.0.0.1:8000/"
    })),
    sendToWorkbench: vi.fn((channel: string, payload: unknown) => {
      workbenchMessages.push({ channel, payload });
      return true;
    }),
    setWorkbenchAttention: vi.fn()
  };
  const service = createConversationNotificationService({
    windowProvider: provider,
    notificationSupported: () => options.notificationSupported ?? true,
    notificationOpenedChannel: OPENED_CHANNEL,
    createNotification: ({ title, body, onClick, onShow, onFailed }) => {
      const record = { title, body, clicked: onClick, shown: false, nativeShown: onShow, nativeFailed: onFailed };
      notifications.push(record);
      return {
        show: () => {
          record.shown = true;
        }
      };
    },
    createBadgeIcon: (count) => ({ badgeCount: count }),
    recordEvent
  });
  return { service, provider, notifications, recordEvent, workbenchMessages };
}

describe("conversation notification service", () => {
  it("records OS display and failure callbacks separately from submission", async () => {
    const { service, notifications, recordEvent } = makeService();
    await service.notify(completion());
    expect(recordEvent.mock.calls.map(([event]) => event.eventCode)).toEqual(["electron.conversation_notification.notified"]);
    notifications[0].nativeShown();
    notifications[0].nativeFailed();
    expect(recordEvent.mock.calls.map(([event]) => event.eventCode)).toEqual([
      "electron.conversation_notification.notified", "electron.conversation_notification.native_shown",
      "electron.conversation_notification.native_failed"
    ]);
  });
  it.each(["failed_runtime", "failed_provider", "paused_limit", "aborted", "superseded"])(
    "accepts the real renderer payload for %s without calling it success", async terminalReason => {
      const payloads: DesktopConversationCompletionNotification[] = [];
      const notifier = createDesktopConversationNotifier({
        bridge: { notifyConversationCompleted: payload => { payloads.push(payload); } }, postTelemetry: vi.fn()
      });
      notifier.handleSessionDetail({ id: "session-1", status: "running", currentPhase: "running", activeTurnId: "turn-1" } as never);
      notifier.handleSessionDetail({ id: "session-1", status: "ready", currentPhase: "ready", terminalReason,
        activeTurnId: "", lastTurnTerminalTurnId: "turn-1", messages: [] } as never);
      expect(payloads).toHaveLength(1);
      const { service, notifications } = makeService({ focused: false });
      expect((await service.notify(payloads[0])).status).toBe("notified");
      expect(notifications[0].title).toBe(terminalReason === "paused_limit" ? "对话待继续" : "对话已结束");
    }
  );
  it.each(["ready", "idle", "running", "paused", "stopped", "stopped_by_user", "force_stopped", "unknown", ""])(
    "does not turn %s into a native completion or taskbar alert", async terminalStatus => {
      const { service, provider, notifications } = makeService({ focused: false });
      const result = await service.notify(completion({ terminalStatus }));
      expect(result.status).toBe("invalid_payload");
      expect(result.unreadCount).toBe(0);
      expect(notifications).toHaveLength(0);
      expect(provider.setWorkbenchAttention).not.toHaveBeenCalled();
    }
  );
  it("suppresses native notifications for the viewed session without clearing background unread", async () => {
    const { service, provider, notifications } = makeService({ focused: true });

    const background = await service.notify(completion({
      notificationKey: "session-bg:turn-1:completed",
      sessionId: "session-bg",
      suppressWhenFocused: false
    }));
    expect(background.unreadCount).toBe(1);
    provider.setWorkbenchAttention.mockClear();

    const result = await service.notify(completion({ suppressWhenFocused: true }));

    expect(result.status).toBe("suppressed_focused");
    expect(result.unreadCount).toBe(1);
    expect(notifications).toHaveLength(1);
    expect(provider.setWorkbenchAttention).not.toHaveBeenCalled();
  });

  it("shows a native notification for a background session even when the workbench is focused", async () => {
    const { service, notifications } = makeService({ focused: true });

    const result = await service.notify(completion({ suppressWhenFocused: false }));

    expect(result.status).toBe("notified");
    expect(notifications).toHaveLength(1);
    expect(notifications[0]).toMatchObject({
      title: "对话已完成",
      body: "「测试会话」已完成一轮回复。",
      shown: true
    });
  });

  it("shows a native notification and taskbar attention when the workbench is unfocused", async () => {
    const { service, provider, notifications } = makeService({ focused: false });

    const result = await service.notify(completion());

    expect(result.status).toBe("notified");
    expect(result.unreadCount).toBe(1);
    expect(notifications).toHaveLength(1);
    expect(notifications[0]).toMatchObject({
      title: "对话已完成",
      body: "「测试会话」已完成一轮回复。",
      shown: true
    });
    expect(provider.setWorkbenchAttention).toHaveBeenCalledWith({
      unreadCount: 1,
      overlayIcon: { badgeCount: 1 },
      description: "1 completed conversation",
      flash: true
    });
  });

  it("shows a native notification for a failed terminal conversation status", async () => {
    const { service, notifications, recordEvent } = makeService({ focused: false });

    const result = await service.notify(
      completion({
        notificationKey: "session-1:turn-1:failed",
        terminalStatus: "failed"
      })
    );

    expect(result.status).toBe("notified");
    expect(result.unreadCount).toBe(1);
    expect(notifications).toHaveLength(1);
    expect(notifications[0]).toMatchObject({
      title: "对话已结束",
      body: "「测试会话」对话已结束。",
      shown: true
    });
    expect(recordEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        eventCode: "electron.conversation_notification.notified",
        fields: expect.objectContaining({
          notificationKey: "session-1:turn-1:failed",
          terminalStatus: "failed",
          status: "notified"
        })
      })
    );
  });

  it("dedupes repeated completion keys", async () => {
    const { service, provider, notifications } = makeService({ focused: false });

    const first = await service.notify(completion());
    const second = await service.notify(completion());

    expect(first.status).toBe("notified");
    expect(second.status).toBe("duplicate");
    expect(second.unreadCount).toBe(1);
    expect(notifications).toHaveLength(1);
    expect(provider.setWorkbenchAttention).toHaveBeenCalledTimes(1);
  });

  it("focuses the workbench and opens the completed session when the notification is clicked", async () => {
    const { service, provider, notifications, workbenchMessages } = makeService({ focused: false });

    await service.notify(completion());
    notifications[0].clicked();

    expect(provider.focusWorkbench).toHaveBeenCalledTimes(1);
    expect(workbenchMessages).toEqual([
      {
        channel: OPENED_CHANNEL,
        payload: { schemaVersion: 1, sessionId: "session-1" }
      }
    ]);
  });

  it("preserves Companion identity only for an explicit Companion notification click", async () => {
    const { service, notifications, workbenchMessages } = makeService({ focused: false });

    await service.notify(completion({
      notificationKey: "session-nora:turn-1:completed",
      sessionId: "session-nora",
      companionAgentId: "agent-nora",
    }));
    notifications[0].clicked();

    expect(workbenchMessages).toEqual([{
      channel: OPENED_CHANNEL,
      payload: {
        schemaVersion: 1,
        sessionId: "session-nora",
        companionAgentId: "agent-nora",
      },
    }]);
  });

  it("rejects an unsafe Companion identity without notifying or changing attention", async () => {
    const { service, provider, notifications } = makeService({ focused: false });

    const result = await service.notify(completion({ companionAgentId: "../unsafe" }));

    expect(result.status).toBe("invalid_payload");
    expect(notifications).toHaveLength(0);
    expect(provider.setWorkbenchAttention).not.toHaveBeenCalled();
  });

  it("applies taskbar attention even when native notifications are unavailable", async () => {
    const { service, provider, notifications } = makeService({
      focused: false,
      notificationSupported: false
    });

    const result = await service.notify(completion());

    expect(result.status).toBe("notification_unavailable_attention_applied");
    expect(result.unreadCount).toBe(1);
    expect(notifications).toHaveLength(0);
    expect(provider.setWorkbenchAttention).toHaveBeenCalledWith({
      unreadCount: 1,
      overlayIcon: { badgeCount: 1 },
      description: "1 completed conversation",
      flash: true
    });
  });

  it("rebuilds privacy-safe native notification copy from the session label", async () => {
    const { service, notifications } = makeService({ focused: false });

    const result = await service.notify(
      completion({
        title: "SECRET: C:\\Users\\17533\\Desktop\\Vibelution\\logs\\prompt.txt",
        body: "assistant: api_key=sk-live prompt=tool output attachment /tmp/secret.zip",
        sessionLabel: "sk-live-secret from C:\\Users\\17533\\Desktop\\prompt.txt"
      })
    );

    expect(result.status).toBe("notified");
    expect(notifications).toHaveLength(1);
    expect(notifications[0]).toMatchObject({
      title: "对话已完成",
      body: "「from」已完成一轮回复。",
      shown: true
    });
    expect(JSON.stringify(notifications[0])).not.toContain("sk-live-secret");
    expect(JSON.stringify(notifications[0])).not.toContain("C:\\Users\\17533");
  });

  it("rejects invalid payloads without notifying, unread increments, or attention changes", async () => {
    const { service, provider, notifications } = makeService({ focused: false });

    const result = await service.notify({
      ...completion(),
      notificationKey: "   "
    });

    expect(result.status).toBe("invalid_payload");
    expect(result.unreadCount).toBe(0);
    expect(notifications).toHaveLength(0);
    expect(provider.setWorkbenchAttention).not.toHaveBeenCalled();
  });

  it("records only approved telemetry metadata", async () => {
    const { service, recordEvent } = makeService({ focused: false });

    await service.notify(
      completion({
        title: "assistant output",
        body: "tool output with C:\\secret\\path and prompt text",
        sessionLabel: "测试会话"
      })
    );

    expect(recordEvent).toHaveBeenCalledTimes(1);
    const event = recordEvent.mock.calls[0]?.[0];
    expect(event.eventCode).toBe("electron.conversation_notification.notified");
    expect(event.fields).toEqual({
      sessionId: "session-1",
      turnId: "turn-1",
      notificationKey: "session-1:turn-1:completed",
      terminalStatus: "completed",
      focused: false,
      unreadCount: 1,
      status: "notified",
      suppressWhenFocused: true
    });
    expect(JSON.stringify(event.fields)).not.toContain("assistant output");
    expect(JSON.stringify(event.fields)).not.toContain("tool output");
    expect(JSON.stringify(event.fields)).not.toContain("C:\\secret\\path");
    expect(JSON.stringify(event.fields)).not.toContain("prompt text");
    expect(JSON.stringify(event.fields)).not.toContain("测试会话");
  });

  it("clearAttention resets unread state and clears workbench attention", async () => {
    const { service, provider } = makeService({ focused: false });

    await service.notify(completion());
    provider.setWorkbenchAttention.mockClear();

    service.clearAttention();

    expect(provider.setWorkbenchAttention).toHaveBeenCalledWith({ unreadCount: 0 });

    const afterClear = await service.notify(
      completion({
        notificationKey: "session-1:turn-2:completed",
        turnId: "turn-2"
      })
    );
    expect(afterClear.unreadCount).toBe(1);
  });

  it("resets unread count to 1 for the next background completion after focus-driven clear", async () => {
    let focused = false;
    const notifications: Array<{ title: string; body: string; clicked: () => void; shown: boolean }> = [];
    const provider = {
      isWorkbenchFocused: vi.fn(() => focused),
      focusWorkbench: vi.fn(async () => ({
        role: "workbench",
        provider: "electron",
        open: true,
        focused: true,
        windowId: 1,
        rendererProcessId: 2,
        url: "http://127.0.0.1:8000/"
      })),
      sendToWorkbench: vi.fn(() => true),
      setWorkbenchAttention: vi.fn()
    };
    const service = createConversationNotificationService({
      windowProvider: provider,
      notificationSupported: () => true,
      notificationOpenedChannel: OPENED_CHANNEL,
      createNotification: ({ title, body, onClick }) => {
        const record = { title, body, clicked: onClick, shown: false };
        notifications.push(record);
        return {
          show: () => {
            record.shown = true;
          }
        };
      },
      createBadgeIcon: (count) => ({ badgeCount: count }),
      recordEvent: vi.fn(async () => undefined)
    });

    const first = await service.notify(completion());
    expect(first.unreadCount).toBe(1);

    focused = true;
    service.clearAttention();

    focused = false;
    const second = await service.notify(
      completion({
        notificationKey: "session-1:turn-2:completed",
        turnId: "turn-2"
      })
    );

    expect(second.status).toBe("notified");
    expect(second.unreadCount).toBe(1);
  });

  it("reports needs_continue turns as awaiting the user instead of ended", async () => {
    const { service, notifications } = makeService({});

    const result = await service.notify(
      completion({
        notificationKey: "session-1:turn-3:needs_continue",
        turnId: "turn-3",
        terminalStatus: "needs_continue"
      })
    );

    expect(result.status).toBe("notified");
    expect(notifications).toHaveLength(1);
    expect(notifications[0].title).toBe("对话待继续");
    expect(notifications[0].body).toBe("「测试会话」还有后续步骤，回复“继续”即可推进。");
  });
});
