export type DesktopConversationCompletionNotification = {
  schemaVersion: 1;
  notificationKey: string;
  sessionId: string;
  turnId?: string;
  title: string;
  body: string;
  completedAt?: string;
  terminalStatus?: string;
};

export type DesktopConversationNotificationStatus =
  | "notified"
  | "suppressed_focused"
  | "duplicate"
  | "invalid_payload"
  | "notification_unavailable_attention_applied"
  | "failed";

export type DesktopConversationNotificationResult = {
  schemaVersion: 1;
  status: DesktopConversationNotificationStatus;
  notificationKey: string;
  unreadCount: number;
  focused: boolean;
};

type NotificationLike = {
  show(): void;
};

type NotificationFactoryInput = {
  title: string;
  body: string;
  onClick: () => void;
};

type WindowProviderLike = {
  isWorkbenchFocused(): boolean;
  focusWorkbench(): Promise<unknown>;
  setWorkbenchAttention(options: {
    unreadCount: number;
    overlayIcon?: unknown;
    description?: string;
    flash?: boolean;
  }): void;
};

export type ConversationNotificationServiceOptions = {
  windowProvider: WindowProviderLike;
  notificationSupported: () => boolean;
  createNotification: (input: NotificationFactoryInput) => NotificationLike;
  createBadgeIcon: (count: number) => unknown;
  recordEvent?: (event: {
    eventCode: string;
    message: string;
    fields: Record<string, unknown>;
  }) => void | Promise<void>;
  maxSeenKeys?: number;
};

export type ConversationNotificationService = {
  notify(payload: DesktopConversationCompletionNotification): Promise<DesktopConversationNotificationResult>;
  clearAttention(): void;
};

const SAFE_NOTIFICATION_TITLE = "对话已完成";
const SAFE_NOTIFICATION_BODY = "Vibelution 已完成一轮回复。";

export function createConversationNotificationService(
  options: ConversationNotificationServiceOptions
): ConversationNotificationService {
  const seenKeys: string[] = [];
  const seenKeySet = new Set<string>();
  const maxSeenKeys = Math.max(1, Math.round(options.maxSeenKeys ?? 200));
  let unreadCount = 0;

  function rememberKey(key: string): boolean {
    if (seenKeySet.has(key)) {
      return false;
    }
    seenKeySet.add(key);
    seenKeys.push(key);
    while (seenKeys.length > maxSeenKeys) {
      const removed = seenKeys.shift();
      if (removed) {
        seenKeySet.delete(removed);
      }
    }
    return true;
  }

  function createResult(
    status: DesktopConversationNotificationStatus,
    payload: DesktopConversationCompletionNotification,
    focused: boolean
  ): DesktopConversationNotificationResult {
    return {
      schemaVersion: 1,
      status,
      notificationKey: String(payload.notificationKey || ""),
      unreadCount,
      focused
    };
  }

  function record(
    eventCode: string,
    message: string,
    payload: DesktopConversationCompletionNotification,
    focused: boolean,
    status: DesktopConversationNotificationStatus
  ): void {
    void options.recordEvent?.({
      eventCode,
      message,
      fields: {
        sessionId: payload.sessionId,
        turnId: payload.turnId ?? "",
        notificationKey: payload.notificationKey,
        terminalStatus: payload.terminalStatus ?? "",
        focused,
        unreadCount,
        status
      }
    });
  }

  function applyAttention(): void {
    const boundedCount = Math.min(unreadCount, 9);
    options.windowProvider.setWorkbenchAttention({
      unreadCount,
      overlayIcon: options.createBadgeIcon(boundedCount),
      description: `${unreadCount} completed conversation${unreadCount === 1 ? "" : "s"}`,
      flash: true
    });
  }

  return {
    async notify(payload) {
      const notificationKey = String(payload?.notificationKey || "").trim();
      const sessionId = String(payload?.sessionId || "").trim();
      if (payload?.schemaVersion !== 1 || !notificationKey || !sessionId) {
        const focused = options.windowProvider.isWorkbenchFocused();
        unreadCount = Math.max(0, unreadCount);
        const invalidPayload: DesktopConversationCompletionNotification = {
          schemaVersion: 1,
          notificationKey,
          sessionId,
          turnId: typeof payload?.turnId === "string" ? payload.turnId : undefined,
          title: typeof payload?.title === "string" ? payload.title : "",
          body: typeof payload?.body === "string" ? payload.body : "",
          completedAt: typeof payload?.completedAt === "string" ? payload.completedAt : undefined,
          terminalStatus: typeof payload?.terminalStatus === "string" ? payload.terminalStatus : undefined
        };
        record(
          "electron.conversation_notification.failed",
          "Conversation completion notification payload was invalid.",
          invalidPayload,
          focused,
          "invalid_payload"
        );
        return createResult("invalid_payload", invalidPayload, focused);
      }

      const normalizedPayload: DesktopConversationCompletionNotification = {
        schemaVersion: 1,
        notificationKey,
        sessionId,
        turnId: String(payload.turnId || "").trim() || undefined,
        title: SAFE_NOTIFICATION_TITLE,
        body: SAFE_NOTIFICATION_BODY,
        completedAt: String(payload.completedAt || "").trim() || undefined,
        terminalStatus: String(payload.terminalStatus || "").trim() || undefined
      };
      const focused = options.windowProvider.isWorkbenchFocused();

      if (!rememberKey(notificationKey)) {
        record(
          "electron.conversation_notification.suppressed",
          "Duplicate conversation completion notification was suppressed.",
          normalizedPayload,
          focused,
          "duplicate"
        );
        return createResult("duplicate", normalizedPayload, focused);
      }

      if (focused) {
        unreadCount = 0;
        options.windowProvider.setWorkbenchAttention({ unreadCount: 0 });
        record(
          "electron.conversation_notification.suppressed",
          "Conversation completion notification was suppressed because workbench is focused.",
          normalizedPayload,
          focused,
          "suppressed_focused"
        );
        return createResult("suppressed_focused", normalizedPayload, focused);
      }

      unreadCount += 1;
      applyAttention();

      if (!options.notificationSupported()) {
        record(
          "electron.conversation_notification.failed",
          "Native notification was unavailable; taskbar attention was applied.",
          normalizedPayload,
          focused,
          "notification_unavailable_attention_applied"
        );
        return createResult("notification_unavailable_attention_applied", normalizedPayload, focused);
      }

      try {
        const notification = options.createNotification({
          title: normalizedPayload.title,
          body: normalizedPayload.body,
          onClick: () => {
            void options.windowProvider.focusWorkbench();
          }
        });
        notification.show();
        record(
          "electron.conversation_notification.notified",
          "Conversation completion notification was shown.",
          normalizedPayload,
          focused,
          "notified"
        );
        return createResult("notified", normalizedPayload, focused);
      } catch {
        record(
          "electron.conversation_notification.failed",
          "Native notification failed; taskbar attention was applied.",
          normalizedPayload,
          focused,
          "failed"
        );
        return createResult("failed", normalizedPayload, focused);
      }
    },

    clearAttention() {
      unreadCount = 0;
      options.windowProvider.setWorkbenchAttention({ unreadCount: 0 });
    }
  };
}
