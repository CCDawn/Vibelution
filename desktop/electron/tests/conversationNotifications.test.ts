import { describe, expect, it, vi } from "vitest";
import {
  createConversationNotificationService,
  type DesktopConversationCompletionNotification
} from "../src/notifications/conversationNotifications.js";

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
    completedAt: "2026-07-05T07:00:00Z",
    terminalStatus: "completed",
    ...overrides
  };
}

function makeService(options: { focused?: boolean; notificationSupported?: boolean } = {}) {
  const notifications: Array<{ title: string; body: string; clicked: () => void; shown: boolean }> = [];
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
    setWorkbenchAttention: vi.fn()
  };
  const service = createConversationNotificationService({
    windowProvider: provider,
    notificationSupported: () => options.notificationSupported ?? true,
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
    recordEvent
  });
  return { service, provider, notifications, recordEvent };
}

describe("conversation notification service", () => {
  it("suppresses native notifications and clears attention when the workbench is focused", async () => {
    const { service, provider, notifications } = makeService({ focused: true });

    const result = await service.notify(completion());

    expect(result.status).toBe("suppressed_focused");
    expect(result.unreadCount).toBe(0);
    expect(notifications).toHaveLength(0);
    expect(provider.setWorkbenchAttention).toHaveBeenCalledWith({ unreadCount: 0 });
  });

  it("shows a native notification and taskbar attention when the workbench is unfocused", async () => {
    const { service, provider, notifications } = makeService({ focused: false });

    const result = await service.notify(completion());

    expect(result.status).toBe("notified");
    expect(result.unreadCount).toBe(1);
    expect(notifications).toHaveLength(1);
    expect(notifications[0]).toMatchObject({
      title: "对话已完成",
      body: "Vibelution 已完成一轮回复。",
      shown: true
    });
    expect(provider.setWorkbenchAttention).toHaveBeenCalledWith({
      unreadCount: 1,
      overlayIcon: { badgeCount: 1 },
      description: "1 completed conversation",
      flash: true
    });
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

  it("focuses the workbench when the notification is clicked", async () => {
    const { service, provider, notifications } = makeService({ focused: false });

    await service.notify(completion());
    notifications[0].clicked();

    expect(provider.focusWorkbench).toHaveBeenCalledTimes(1);
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

  it("uses privacy-safe native notification copy instead of caller-provided content", async () => {
    const { service, notifications } = makeService({ focused: false });

    const result = await service.notify(
      completion({
        title: "SECRET: C:\\Users\\17533\\Desktop\\Vibelution\\logs\\prompt.txt",
        body: "assistant: api_key=sk-live prompt=tool output attachment /tmp/secret.zip"
      })
    );

    expect(result.status).toBe("notified");
    expect(notifications).toHaveLength(1);
    expect(notifications[0]).toMatchObject({
      title: "对话已完成",
      body: "Vibelution 已完成一轮回复。",
      shown: true
    });
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
        body: "tool output with C:\\secret\\path and prompt text"
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
      status: "notified"
    });
    expect(JSON.stringify(event.fields)).not.toContain("assistant output");
    expect(JSON.stringify(event.fields)).not.toContain("tool output");
    expect(JSON.stringify(event.fields)).not.toContain("C:\\secret\\path");
    expect(JSON.stringify(event.fields)).not.toContain("prompt text");
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
      setWorkbenchAttention: vi.fn()
    };
    const service = createConversationNotificationService({
      windowProvider: provider,
      notificationSupported: () => true,
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
});
