import type { ConversationMessage, SessionDetail, SessionStreamEvent } from "../api/types";
import type { BrowserTelemetryEventInput } from "../app/browserTelemetry";

type DesktopConversationCompletionNotification = {
  schemaVersion: 1;
  notificationKey: string;
  sessionId: string;
  turnId?: string;
  title: string;
  body: string;
  completedAt?: string;
  terminalStatus?: string;
};

type DesktopBridge = {
  notifyConversationCompleted?: (payload: DesktopConversationCompletionNotification) => Promise<unknown>;
};

type DesktopConversationNotifierOptions = {
  bridge?: DesktopBridge;
  postTelemetry: (event: BrowserTelemetryEventInput) => void;
  maxSeenKeys?: number;
};

type NotificationContext = {
  sessionTitle?: string;
};

const SAFE_NOTIFICATION_TITLE = "对话已完成";
const SAFE_NOTIFICATION_BODY = "Vibelution 已完成一轮回复。";

export type DesktopConversationNotifier = {
  handleAssistantDelta(
    payload: Extract<SessionStreamEvent, { type: "assistant_delta" }>,
    context?: NotificationContext,
  ): void;
  handleSessionDetail(detail: SessionDetail, context?: NotificationContext): void;
};

const BUSY_PHASES = new Set([
  "queued",
  "running",
  "thinking",
  "tooling",
  "answering",
  "planning",
  "reading",
  "editing",
  "verifying",
  "stopping",
  "paused",
]);

const TERMINAL_PHASES = new Set([
  "ready",
  "completed",
  "done",
  "success",
  "failed",
  "failed_provider",
  "failed_runtime",
  "error",
  "timeout",
  "timed_out",
  "blocked",
  "cancelled",
  "canceled",
  "stopped",
  "stopped_by_user",
  "needs_continue",
]);

function normalizeText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function isBusyPhase(value: unknown): boolean {
  return BUSY_PHASES.has(normalizeText(value).toLowerCase());
}

function terminalPhaseForDetail(detail: SessionDetail): string {
  const phase = normalizeText(detail.currentPhase || detail.status).toLowerCase();
  return TERMINAL_PHASES.has(phase) ? phase : "";
}

function notificationStatusForTerminalPhase(phase: string): string {
  return ["ready", "completed", "done", "success"].includes(phase) ? "completed" : phase;
}

function latestAssistantTurnMessage(detail: SessionDetail): ConversationMessage | undefined {
  return [...(detail.messages ?? [])].reverse().find((message) => {
    if (message.role !== "assistant") {
      return false;
    }
    const kind = normalizeText(message.metadata?.kind);
    if (kind === "session_active_turn_layer" || kind === "session_live_overlay") {
      return false;
    }
    return Boolean(normalizeText(message.content ?? message.thought ?? ""));
  });
}

function messageTurnId(message: ConversationMessage | undefined): string {
  const raw = normalizeText(message?.metadata?.turnId);
  return raw.startsWith("live:") ? raw.slice("live:".length) : raw;
}

function detailTurnId(detail: SessionDetail, latest: ConversationMessage | undefined): string {
  return messageTurnId(latest) || normalizeText(latest?.id) || normalizeText(detail.lastTurnError?.turnId);
}

export function browserDesktopNotificationBridge(globalLike: unknown = globalThis): DesktopBridge | undefined {
  const bridge = (globalLike as { vibelutionLauncher?: unknown })?.vibelutionLauncher;
  if (typeof bridge !== "object" || bridge === null) {
    return undefined;
  }
  const candidate = bridge as DesktopBridge;
  return typeof candidate.notifyConversationCompleted === "function" ? candidate : undefined;
}

export function createDesktopConversationNotifier(
  options: DesktopConversationNotifierOptions,
): DesktopConversationNotifier {
  const seenKeys: string[] = [];
  const seenKeySet = new Set<string>();
  const maxSeenKeys = Math.max(1, Math.round(options.maxSeenKeys ?? 200));
  const lastBusyBySession = new Map<string, boolean>();

  function remember(key: string): boolean {
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

  function emit(payload: DesktopConversationCompletionNotification): void {
    if (!remember(payload.notificationKey)) {
      return;
    }

    const bridge = options.bridge;
    if (!bridge?.notifyConversationCompleted) {
      options.postTelemetry({
        phase: "desktop_notification",
        eventCode: "browser.desktop_notification.conversation_completed_skipped",
        message: "Conversation completion desktop notification bridge was unavailable.",
        level: "info",
        fields: {
          sessionId: payload.sessionId,
          turnId: payload.turnId ?? "",
          notificationKey: payload.notificationKey,
          terminalStatus: payload.terminalStatus ?? "",
          reason: "bridge_unavailable",
        },
      });
      return;
    }

    void bridge.notifyConversationCompleted(payload);
    options.postTelemetry({
      phase: "desktop_notification",
      eventCode: "browser.desktop_notification.conversation_completed_emitted",
      message: "Conversation completion desktop notification was emitted to Electron.",
      level: "info",
      fields: {
        sessionId: payload.sessionId,
        turnId: payload.turnId ?? "",
        notificationKey: payload.notificationKey,
        terminalStatus: payload.terminalStatus ?? "",
      },
    });
  }

  return {
    handleAssistantDelta(payload, context) {
      if (!payload.done) {
        return;
      }

      const sessionId = normalizeText(payload.sessionId);
      const turnId = normalizeText(payload.turnId);
      if (!sessionId || !turnId) {
        return;
      }

      emit({
        schemaVersion: 1,
        notificationKey: `${sessionId}:${turnId}:completed`,
        sessionId,
        turnId,
        title: SAFE_NOTIFICATION_TITLE,
        body: SAFE_NOTIFICATION_BODY,
        completedAt: normalizeText(payload.updatedAt) || undefined,
        terminalStatus: "completed",
      });
    },

    handleSessionDetail(detail, context) {
      const sessionId = normalizeText(detail.id);
      if (!sessionId) {
        return;
      }

      const phase = normalizeText(detail.currentPhase || detail.status);
      const busy = isBusyPhase(phase);
      const terminalPhase = terminalPhaseForDetail(detail);
      const wasBusy = lastBusyBySession.get(sessionId) ?? false;
      lastBusyBySession.set(sessionId, busy);
      if (busy || !wasBusy || !terminalPhase) {
        return;
      }
      const terminalStatus = notificationStatusForTerminalPhase(terminalPhase);

      const latest = latestAssistantTurnMessage(detail);
      const turnId = detailTurnId(detail, latest);
      if (!turnId) {
        return;
      }

      emit({
        schemaVersion: 1,
        notificationKey: `${sessionId}:${turnId}:${terminalStatus}`,
        sessionId,
        turnId,
        title: SAFE_NOTIFICATION_TITLE,
        body: SAFE_NOTIFICATION_BODY,
        completedAt: normalizeText(latest?.timestamp) || undefined,
        terminalStatus,
      });
    },
  };
}
