export type HumanAttentionKind =
  | "knowledge_review"
  | "anomaly"
  | "affair_reminder"
  | "human_gate"
  | "dispatch_receipt"
  | "run_completed"
  | "session_completed"
  | "assistant_digest";
/** info 只用于完成类事件（好消息），不占用停靠/异常的 critical/high 语义。 */
export type HumanAttentionSeverity = "critical" | "high" | "medium" | "info";

/** Server-labeled approve affordance forwarded to the assistant window card. */
export type DesktopHumanAttentionAction = {
  label: string;
  decision: string;
};

/** Research human-gate routing facts forwarded to the assistant window card. */
export type DesktopHumanAttentionMeta = {
  teamId?: string;
  runId?: string;
  nodeId?: string;
  taskId?: string;
  decisions?: string[];
};

export type DesktopHumanAttentionNotification = {
  id: string;
  kind: HumanAttentionKind;
  severity: HumanAttentionSeverity;
  title: string;
  body?: string;
  targetUrl?: string;
  actions?: DesktopHumanAttentionAction[];
  meta?: DesktopHumanAttentionMeta;
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
  | { delivered: "invalid_payload"; error: string }
  | { delivered: "source_retired" }
  | { delivered: "attempt_pending" };

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
  /**
   * Whether the assistant surface is actually on screen. An in-window card on a
   * hidden or minimized surface is never seen, so delivery has to fall through
   * to the system toast instead of stopping at channel 1. Optional for
   * backwards compatibility: absent means "assume visible".
   */
  isAssistantWindowVisible?(): boolean;
  sendToWorkbench(channel: string, payload: unknown): boolean;
  focusWorkbench(): Promise<unknown>;
  setWorkbenchAttention(options: {
    unreadCount: number;
    flash?: boolean;
    description?: string;
  }): void;
};

/** Main-only source, captured from the registered WebContents. */
export type HumanAttentionSource = {
  instanceId: string;
  origin: string;
  documentToken: object;
  target: Pick<HumanAttentionWindowBridge, "sendToWorkbench" | "focusWorkbench" | "setWorkbenchAttention">;
  allowAssistantWindow: () => boolean;
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
  notify(payload: unknown, source?: HumanAttentionSource): Promise<DesktopHumanAttentionNotifyResult>;
};

/**
 * Must mirror the web whitelist (`HUMAN_ATTENTION_KINDS` in
 * `web/src/routes/personalAssistant/humanAttentionNotifications.ts`); the
 * desktop test suite asserts both sets stay identical.
 */
const KINDS: ReadonlySet<string> = new Set([
  "knowledge_review",
  "anomaly",
  "affair_reminder",
  "human_gate",
  "dispatch_receipt",
  "run_completed",
  "session_completed",
  "assistant_digest"
]);
const SEVERITIES: ReadonlySet<string> = new Set(["critical", "high", "medium", "info"]);
const DEFAULT_DEDUP_WINDOW_MS = 60_000;
const MAX_TRACKED_IDS = 500;
const MAX_ID_LENGTH = 128;
const MAX_TITLE_LENGTH = 160;
const MAX_BODY_LENGTH = 400;
const MAX_TARGET_URL_LENGTH = 500;
const MAX_ACTIONS = 4;
const MAX_ACTION_LABEL_LENGTH = 40;
const MAX_ACTION_DECISION_LENGTH = 24;
const MAX_META_VALUE_LENGTH = 128;
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

/**
 * Bounded pass-through of the server-built approve actions. The assistant
 * window re-normalizes on parse, so the shell only guarantees shape safety:
 * well-formed entries survive, anything else is dropped silently.
 */
function normalizeActions(raw: unknown): DesktopHumanAttentionAction[] | undefined {
  if (!Array.isArray(raw)) {
    return undefined;
  }
  const actions: DesktopHumanAttentionAction[] = [];
  const seenDecisions = new Set<string>();
  for (const entry of raw.slice(0, MAX_ACTIONS)) {
    if (typeof entry !== "object" || entry === null) {
      continue;
    }
    const source = entry as { label?: unknown; decision?: unknown };
    if (typeof source.label !== "string" || typeof source.decision !== "string") {
      continue;
    }
    const label = source.label.replace(/\s+/g, " ").trim().slice(0, MAX_ACTION_LABEL_LENGTH);
    const decision = source.decision.replace(/\s+/g, " ").trim().slice(0, MAX_ACTION_DECISION_LENGTH);
    if (!label || !decision || seenDecisions.has(decision)) {
      continue;
    }
    seenDecisions.add(decision);
    actions.push({ label, decision });
  }
  return actions.length > 0 ? actions : undefined;
}

/** Bounded pass-through of the known human-gate routing keys. */
function normalizeMeta(raw: unknown): DesktopHumanAttentionMeta | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return undefined;
  }
  const source = raw as Record<string, unknown>;
  const value = (key: string): string | undefined => {
    if (typeof source[key] !== "string") {
      return undefined;
    }
    const text = (source[key] as string).replace(/\s+/g, " ").trim().slice(0, MAX_META_VALUE_LENGTH);
    return text || undefined;
  };
  const decisions = Array.isArray(source.decisions)
    ? source.decisions
      .filter((decision): decision is string => typeof decision === "string")
      .map(decision => decision.replace(/\s+/g, " ").trim().slice(0, MAX_ACTION_DECISION_LENGTH))
      .filter(Boolean)
    : undefined;
  const meta: DesktopHumanAttentionMeta = {
    ...(value("teamId") ? { teamId: value("teamId") } : {}),
    ...(value("runId") ? { runId: value("runId") } : {}),
    ...(value("nodeId") ? { nodeId: value("nodeId") } : {}),
    ...(value("taskId") ? { taskId: value("taskId") } : {}),
    ...(decisions && decisions.length > 0 ? { decisions } : {})
  };
  return Object.keys(meta).length > 0 ? meta : undefined;
}

export function validateHumanAttentionPayload(
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
      error: `Human attention notification kind must be one of ${[...KINDS].join(", ")}.`
    };
  }
  if (typeof raw.severity !== "string" || !SEVERITIES.has(raw.severity)) {
    return {
      ok: false,
      error: "Human attention notification severity must be one of critical, high, medium, info."
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
  const actions = normalizeActions(raw.actions);
  const meta = normalizeMeta(raw.meta);
  return {
    ok: true,
    value: {
      id,
      kind: raw.kind as HumanAttentionKind,
      severity: raw.severity as HumanAttentionSeverity,
      title,
      ...(body ? { body } : {}),
      ...(targetUrl ? { targetUrl } : {}),
      ...(actions ? { actions } : {}),
      ...(meta ? { meta } : {})
    }
  };
}

export function createHumanAttentionNotificationService(
  options: HumanAttentionNotificationServiceOptions
): HumanAttentionNotificationService {
  const dedupWindowMs = Math.max(0, options.dedupWindowMs ?? DEFAULT_DEDUP_WINDOW_MS);
  const now = options.now ?? (() => Date.now());
  const deliveredIds = new Map<string, DeliveredRecord>();
  const documentKeys = new WeakMap<object, number>();
  let nextDocumentKey = 0;

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

  function handleNotificationClick(notification: DesktopHumanAttentionNotification, source?: HumanAttentionSource): void {
    try {
      const target = source?.target ?? options.windowBridge;
      void Promise.resolve(target.focusWorkbench()).then(
        () => undefined,
        () => undefined
      );
      const opened = {
        id: notification.id,
        ...(notification.targetUrl ? { targetUrl: notification.targetUrl } : {})
      };
      target.sendToWorkbench(options.openedChannel, opened);
      if (!source || source.allowAssistantWindow()) options.windowBridge.sendToAssistantWindow(options.openedChannel, opened);
    } catch {
      // A toast click must never crash the main process.
    }
  }

  return {
    async notify(payload, source) {
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
      let documentKey = 0;
      if (source) {
        documentKey = documentKeys.get(source.documentToken) ?? ++nextDocumentKey;
        documentKeys.set(source.documentToken, documentKey);
      }
      const dedupKey = JSON.stringify([source?.instanceId ?? "", source?.origin ?? "", documentKey, notification.id]);
      const currentMs = now();
      pruneExpiredIds(currentMs);
      const prior = deliveredIds.get(dedupKey);
      if (prior) {
        const suppressed: DesktopHumanAttentionNotifyResult = { delivered: prior.result.delivered };
        recordOutcome(notification, suppressed, true);
        return suppressed;
      }

      // Channel 1: the assistant surface renders the attention card in-window.
      // Only a surface the user can actually see counts as delivery: a hidden or
      // minimized assistant window would swallow the card, and the notification
      // would never reach the user while still consuming its dedup slot.
      const assistantVisible = options.windowBridge.isAssistantWindowVisible?.() ?? true;
      if ((!source || source.allowAssistantWindow()) && assistantVisible
        && options.windowBridge.sendToAssistantWindow(options.openedChannel, { ...notification })) {
        const result: DesktopHumanAttentionNotifyResult = { delivered: "assistant_window" };
        rememberDelivery(dedupKey, { delivered: "assistant_window" });
        recordOutcome(notification, result, false);
        return result;
      }

      // Channel 2: a Windows system toast for the assistant-closed case.
      if (options.notificationSupported()) {
        try {
          const toast = options.createNotification({
            title: notification.title,
            body: notification.body ?? "",
            onClick: () => handleNotificationClick(notification, source)
          });
          toast.show();
          const result: DesktopHumanAttentionNotifyResult = { delivered: "system_notification" };
          rememberDelivery(dedupKey, { delivered: "system_notification" });
          recordOutcome(notification, result, false);
          return result;
        } catch {
          // Fall through to the flashFrame attention fallback.
        }
      }

      (source?.target ?? options.windowBridge).setWorkbenchAttention({
        unreadCount: 1,
        flash: true,
        description: ATTENTION_FALLBACK_DESCRIPTION
      });
      const result: DesktopHumanAttentionNotifyResult = { delivered: "attention_fallback" };
      rememberDelivery(dedupKey, { delivered: "attention_fallback" });
      recordOutcome(notification, result, false);
      return result;
    }
  };
}
