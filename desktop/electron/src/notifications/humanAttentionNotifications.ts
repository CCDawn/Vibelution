export type HumanAttentionKind = "knowledge_review" | "anomaly";
export type HumanAttentionSeverity = "critical" | "high" | "medium";

export type DesktopHumanAttentionNotification = {
  id: string;
  kind: HumanAttentionKind;
  severity: HumanAttentionSeverity;
  title: string;
  body?: string;
  targetUrl?: string;
};

export type HumanAttentionDelivery =
  | "assistant_window"
  | "system_notification"
  | "attention_fallback";

/**
 * Success keeps exactly the contract shape `{ delivered }`; rejected payloads
 * come back as a structured error so an ipcMain.handle caller never throws.
 */
export type DesktopHumanAttentionNotifyResult =
  | { delivered: HumanAttentionDelivery }
  | { delivered: "invalid_payload"; error: string };

type NotificationLike = {
  show(): void;
};

type NotificationFactoryInput = {
  title: string;
  body: string;
  onClick: () => void;
};

/**
 * Narrow window bridge so the service stays free of Electron imports and the
 * shell can rebuild the window provider without recreating the service.
 */
export type HumanAttentionWindowBridge = {
  /** Deliver to the live pet/assistant surface; false when it is closed or not ready. */
  sendToAssistantWindow(channel: string, payload: unknown): boolean;
  sendToWorkbench(channel: string, payload: unknown): boolean;
  focusWorkbench(): Promise<unknown>;
  setWorkbenchAttention(options: {
    unreadCount: number;
    flash?: boolean;
    description?: string;
  }): void;
};

export type HumanAttentionNotificationServiceOptions = {
  windowBridge: HumanAttentionWindowBridge;
  notificationSupported: () => boolean;
  createNotification: (input: NotificationFactoryInput) => NotificationLike;
  /**
   * Single main→renderer channel for the contract: the assistant-window
   * delivery carries the full notify payload (a superset of `{ id, targetUrl }`)
   * and the system-toast click broadcast carries `{ id, targetUrl? }`.
   */
  openedChannel: string;
  recordEvent?: (event: {
    eventCode: string;
    message: string;
    fields: Record<string, unknown>;
  }) => void | Promise<void>;
  dedupWindowMs?: number;
  now?: () => number;
};

export type HumanAttentionNotificationService = {
  notify(payload: unknown): Promise<DesktopHumanAttentionNotifyResult>;
};

const KINDS: ReadonlySet<string> = new Set(["knowledge_review", "anomaly"]);
const SEVERITIES: ReadonlySet<string> = new Set(["critical", "high", "medium"]);
const DEFAULT_DEDUP_WINDOW_MS = 60_000;
const MAX_TRACKED_IDS = 500;
const MAX_ID_LENGTH = 128;
const MAX_TITLE_LENGTH = 160;
const MAX_BODY_LENGTH = 400;
const MAX_TARGET_URL_LENGTH = 500;
const ATTENTION_FALLBACK_DESCRIPTION = "Human attention required";

type DeliveredRecord = {
  deliveredAt: number;
  result: { delivered: HumanAttentionDelivery };
};

function normalizeText(value: unknown, maxLength: number): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const text = value.replace(/\s+/g, " ").trim();
  if (!text) {
    return undefined;
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}…` : text;
}

function validateHumanAttentionPayload(
  payload: unknown
): { ok: true; value: DesktopHumanAttentionNotification } | { ok: false; error: string } {
  if (typeof payload !== "object" || payload === null) {
    return { ok: false, error: "Human attention notification payload must be an object." };
  }
  const raw = payload as Record<string, unknown>;
  const id = typeof raw.id === "string" ? raw.id.trim() : "";
  if (!id) {
    return { ok: false, error: "Human attention notification requires a non-empty string id." };
  }
  if (id.length > MAX_ID_LENGTH) {
    return {
      ok: false,
      error: `Human attention notification id must be ${MAX_ID_LENGTH} characters or fewer.`
    };
  }
  if (typeof raw.kind !== "string" || !KINDS.has(raw.kind)) {
    return {
      ok: false,
      error: "Human attention notification kind must be one of knowledge_review, anomaly."
    };
  }
  if (typeof raw.severity !== "string" || !SEVERITIES.has(raw.severity)) {
    return {
      ok: false,
      error: "Human attention notification severity must be one of critical, high, medium."
    };
  }
  const title = normalizeText(raw.title, MAX_TITLE_LENGTH);
  if (!title) {
    return {
      ok: false,
      error: "Human attention notification requires a non-empty string title."
    };
  }
  const body = normalizeText(raw.body, MAX_BODY_LENGTH);
  const targetUrl = normalizeText(raw.targetUrl, MAX_TARGET_URL_LENGTH);
  return {
    ok: true,
    value: {
      id,
      kind: raw.kind as HumanAttentionKind,
      severity: raw.severity as HumanAttentionSeverity,
      title,
      ...(body ? { body } : {}),
      ...(targetUrl ? { targetUrl } : {})
    }
  };
}

export function createHumanAttentionNotificationService(
  options: HumanAttentionNotificationServiceOptions
): HumanAttentionNotificationService {
  const dedupWindowMs = Math.max(0, options.dedupWindowMs ?? DEFAULT_DEDUP_WINDOW_MS);
  const now = options.now ?? (() => Date.now());
  const deliveredIds = new Map<string, DeliveredRecord>();

  function record(eventCode: string, message: string, fields: Record<string, unknown>): void {
    void options.recordEvent?.({ eventCode, message, fields });
  }

  function recordOutcome(
    notification: DesktopHumanAttentionNotification,
    result: DesktopHumanAttentionNotifyResult,
    duplicate: boolean
  ): void {
    record(
      duplicate
        ? "electron.human_attention_notification.suppressed"
        : result.delivered === "invalid_payload"
          ? "electron.human_attention_notification.invalid"
          : "electron.human_attention_notification.delivered",
      duplicate
        ? "Duplicate human attention notification was suppressed within the dedup window."
        : result.delivered === "invalid_payload"
          ? "Human attention notification payload was rejected."
          : `Human attention notification was delivered via ${result.delivered}.`,
      {
        id: notification.id,
        kind: notification.kind,
        severity: notification.severity,
        delivered: result.delivered,
        duplicate,
        hasTargetUrl: Boolean(notification.targetUrl)
      }
    );
  }

  function pruneExpiredIds(currentMs: number): void {
    for (const [id, entry] of deliveredIds) {
      if (currentMs - entry.deliveredAt >= dedupWindowMs) {
        deliveredIds.delete(id);
      }
    }
  }

  function rememberDelivery(id: string, result: { delivered: HumanAttentionDelivery }): void {
    deliveredIds.set(id, { deliveredAt: now(), result });
    while (deliveredIds.size > MAX_TRACKED_IDS) {
      const oldest = deliveredIds.keys().next();
      if (oldest.done) {
        break;
      }
      deliveredIds.delete(oldest.value);
    }
  }

  function handleNotificationClick(notification: DesktopHumanAttentionNotification): void {
    try {
      void Promise.resolve(options.windowBridge.focusWorkbench()).then(
        () => undefined,
        () => undefined
      );
      const opened = {
        id: notification.id,
        ...(notification.targetUrl ? { targetUrl: notification.targetUrl } : {})
      };
      options.windowBridge.sendToWorkbench(options.openedChannel, opened);
      options.windowBridge.sendToAssistantWindow(options.openedChannel, opened);
    } catch {
      // A toast click must never crash the main process.
    }
  }

  return {
    async notify(payload) {
      const validated = validateHumanAttentionPayload(payload);
      if (!validated.ok) {
        record(
          "electron.human_attention_notification.invalid",
          "Human attention notification payload was rejected.",
          { reason: validated.error }
        );
        return { delivered: "invalid_payload", error: validated.error };
      }
      const notification = validated.value;
      const currentMs = now();
      pruneExpiredIds(currentMs);
      const prior = deliveredIds.get(notification.id);
      if (prior) {
        const suppressed: DesktopHumanAttentionNotifyResult = { delivered: prior.result.delivered };
        recordOutcome(notification, suppressed, true);
        return suppressed;
      }

      // Channel 1: the assistant surface renders the attention card in-window.
      if (options.windowBridge.sendToAssistantWindow(options.openedChannel, { ...notification })) {
        const result: DesktopHumanAttentionNotifyResult = { delivered: "assistant_window" };
        rememberDelivery(notification.id, { delivered: "assistant_window" });
        recordOutcome(notification, result, false);
        return result;
      }

      // Channel 2: a Windows system toast for the assistant-closed case.
      if (options.notificationSupported()) {
        try {
          const toast = options.createNotification({
            title: notification.title,
            body: notification.body ?? "",
            onClick: () => handleNotificationClick(notification)
          });
          toast.show();
          const result: DesktopHumanAttentionNotifyResult = { delivered: "system_notification" };
          rememberDelivery(notification.id, { delivered: "system_notification" });
          recordOutcome(notification, result, false);
          return result;
        } catch {
          // Fall through to the flashFrame attention fallback.
        }
      }

      options.windowBridge.setWorkbenchAttention({
        unreadCount: 1,
        flash: true,
        description: ATTENTION_FALLBACK_DESCRIPTION
      });
      const result: DesktopHumanAttentionNotifyResult = { delivered: "attention_fallback" };
      rememberDelivery(notification.id, { delivered: "attention_fallback" });
      recordOutcome(notification, result, false);
      return result;
    }
  };
}
