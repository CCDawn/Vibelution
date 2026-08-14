import type { ConversationMessage, SessionDetail, SessionStreamEvent } from "../api/types";
import type { BrowserTelemetryEventInput } from "../app/browserTelemetry";

export type DesktopConversationCompletionNotification = {
  schemaVersion: 1;
  notificationKey: string;
  sessionId: string;
  turnId?: string;
  title: string;
  body: string;
  completedAt?: string;
  terminalStatus?: string;
  sessionLabel?: string;
  suppressWhenFocused?: boolean;
};

export type ConversationNotificationOpenPayload = {
  schemaVersion: 1;
  sessionId: string;
};

type DesktopBridge = {
  notifyConversationCompleted?: (payload: DesktopConversationCompletionNotification) => Promise<unknown>;
  onConversationNotificationOpened?: (listener: (payload: unknown) => void) => () => void;
};

type DesktopConversationNotifierOptions = {
  bridge?: DesktopBridge;
  postTelemetry: (event: BrowserTelemetryEventInput) => void;
  maxSeenKeys?: number;
};

export type NotificationContext = {
  sessionTitle?: string;
  viewedSessionId?: string;
};

export type SessionCompletionSummary = {
  id?: string;
  title?: string;
  agentDisplayName?: string;
  status?: string;
  currentPhase?: string;
  lastTurnStatus?: string;
  updatedAt?: string;
  lastActive?: string;
};

const SUCCESS_TERMINAL_STATUSES = new Set(["ready", "completed", "done", "success"]);

export type DesktopConversationNotifier = {
  handleAssistantDelta(
    payload: Extract<SessionStreamEvent, { type: "assistant_delta" }>,
    context?: NotificationContext,
  ): void;
  handleSessionDetail(detail: SessionDetail, context?: NotificationContext): void;
  handleSessionSummaries(sessions: SessionCompletionSummary[], context?: NotificationContext): void;
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

export function normalizeNotificationText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function isBusyPhase(value: unknown): boolean {
  return BUSY_PHASES.has(normalizeNotificationText(value).toLowerCase());
}

function terminalPhaseForValue(...values: unknown[]): string {
  for (const value of values) {
    const phase = normalizeNotificationText(value).toLowerCase();
    if (TERMINAL_PHASES.has(phase)) {
      return phase;
    }
  }
  return "";
}

function notificationStatusForTerminalPhase(phase: string): string {
  return SUCCESS_TERMINAL_STATUSES.has(phase) ? "completed" : phase;
}

export function sanitizeSessionLabel(raw: unknown, sessionId: string): string {
  let text = normalizeNotificationText(raw);
  text = text
    .replace(/[A-Za-z]:\\[^\s]+/g, " ")
    .replace(/\\\\[^\s]+/g, " ")
    .replace(/(?:^|[\s(])\/(?:Users|home|tmp|var|etc|opt)[^\s]*/gi, " ")
    .replace(/\bsk-[A-Za-z0-9_-]{8,}\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (text.length > 40) {
    text = `${text.slice(0, 39)}…`;
  }
  if (text) {
    return text;
  }
  const shortId = normalizeNotificationText(sessionId).replace(/^session-/, "").slice(0, 8);
  return shortId ? `会话 ${shortId}` : "当前会话";
}

export function buildConversationNotificationCopy(options: {
  sessionLabel: string;
  terminalStatus: string;
}): { title: string; body: string } {
  const label = options.sessionLabel || "当前会话";
  if (SUCCESS_TERMINAL_STATUSES.has(options.terminalStatus)) {
    return {
      title: "对话已完成",
      body: `「${label}」已完成一轮回复。`,
    };
  }
  return {
    title: "对话已结束",
    body: `「${label}」对话已结束。`,
  };
}

function sessionLabelFromContext(
  sessionId: string,
  context: NotificationContext | undefined,
  ...candidates: unknown[]
): string {
  return sanitizeSessionLabel(
    candidates.find((value) => normalizeNotificationText(value)) || context?.sessionTitle || sessionId,
    sessionId,
  );
}

function shouldSuppressWhenFocused(sessionId: string, context?: NotificationContext): boolean {
  const viewedSessionId = normalizeNotificationText(context?.viewedSessionId);
  if (!viewedSessionId) {
    return true;
  }
  return viewedSessionId === sessionId;
}

function latestAssistantTurnMessage(detail: SessionDetail): ConversationMessage | undefined {
  return [...(detail.messages ?? [])].reverse().find((message) => {
    if (message.role !== "assistant") {
      return false;
    }
    const kind = normalizeNotificationText(message.metadata?.kind);
    if (kind === "session_active_turn_layer" || kind === "session_live_overlay") {
      return false;
    }
    return message.turnItems?.some((item) => (
      (item.type === "agent_message" || item.type === "reasoning")
      && Boolean(normalizeNotificationText(item.text))
    ));
  });
}

function messageTurnId(message: ConversationMessage | undefined): string {
  if (message?.role === "assistant") {
    return normalizeNotificationText(message.turnId);
  }
  const raw = normalizeNotificationText(message?.metadata?.turnId);
  return raw.startsWith("live:") ? raw.slice("live:".length) : raw;
}

function detailTurnId(detail: SessionDetail, latest: ConversationMessage | undefined): string {
  return messageTurnId(latest) || normalizeNotificationText(latest?.id) || normalizeNotificationText(detail.lastTurnError?.turnId);
}

export function parseConversationNotificationOpenPayload(raw: unknown): ConversationNotificationOpenPayload | null {
  if (typeof raw !== "object" || raw === null) {
    return null;
  }
  const payload = raw as { schemaVersion?: unknown; sessionId?: unknown };
  if (payload.schemaVersion !== 1) {
    return null;
  }
  const sessionId = normalizeNotificationText(payload.sessionId);
  if (!sessionId || !/^[A-Za-z0-9._:-]{1,128}$/.test(sessionId)) {
    return null;
  }
  return { schemaVersion: 1, sessionId };
}

export function browserDesktopNotificationBridge(globalLike: unknown = globalThis): DesktopBridge | undefined {
  const bridge = (globalLike as { vibelutionLauncher?: unknown })?.vibelutionLauncher;
  if (typeof bridge !== "object" || bridge === null) {
    return undefined;
  }
  const candidate = bridge as DesktopBridge;
  const hasNotify = typeof candidate.notifyConversationCompleted === "function";
  const hasOpen = typeof candidate.onConversationNotificationOpened === "function";
  if (!hasNotify && !hasOpen) {
    return undefined;
  }
  return {
    notifyConversationCompleted: hasNotify ? candidate.notifyConversationCompleted : undefined,
    onConversationNotificationOpened: hasOpen ? candidate.onConversationNotificationOpened : undefined,
  };
}

export function subscribeConversationNotificationOpened(
  bridge: DesktopBridge | undefined,
  onOpen: (sessionId: string) => void,
): () => void {
  if (typeof bridge?.onConversationNotificationOpened !== "function") {
    return () => undefined;
  }
  return bridge.onConversationNotificationOpened((raw) => {
    const parsed = parseConversationNotificationOpenPayload(raw);
    if (parsed) {
      onOpen(parsed.sessionId);
    }
  });
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

  function emitSessionCompletion(input: {
    sessionId: string;
    turnId: string;
    terminalStatus: string;
    completedAt?: string;
    sessionLabel: string;
    suppressWhenFocused: boolean;
  }): void {
    const copy = buildConversationNotificationCopy({
      sessionLabel: input.sessionLabel,
      terminalStatus: input.terminalStatus,
    });
    emit({
      schemaVersion: 1,
      notificationKey: `${input.sessionId}:${input.turnId}:${input.terminalStatus}`,
      sessionId: input.sessionId,
      turnId: input.turnId,
      title: copy.title,
      body: copy.body,
      completedAt: input.completedAt,
      terminalStatus: input.terminalStatus,
      sessionLabel: input.sessionLabel,
      suppressWhenFocused: input.suppressWhenFocused,
    });
  }

  function observeSessionPhase(
    sessionId: string,
    busy: boolean,
    terminalPhase: string,
    onTerminal: () => void,
  ): void {
    const seen = lastBusyBySession.has(sessionId);
    const wasBusy = lastBusyBySession.get(sessionId) ?? false;
    lastBusyBySession.set(sessionId, busy);
    if (!seen || busy || !wasBusy || !terminalPhase) {
      return;
    }
    onTerminal();
  }

  return {
    handleAssistantDelta(payload, context) {
      if (!payload.done) {
        return;
      }

      const sessionId = normalizeNotificationText(payload.sessionId);
      const turnId = normalizeNotificationText(payload.turnId);
      if (!sessionId || !turnId) {
        return;
      }
      const sessionLabel = sessionLabelFromContext(sessionId, context);
      emitSessionCompletion({
        sessionId,
        turnId,
        terminalStatus: "completed",
        completedAt: normalizeNotificationText(payload.updatedAt) || undefined,
        sessionLabel,
        suppressWhenFocused: shouldSuppressWhenFocused(sessionId, context),
      });
      // Stream owns the viewed session. Mark idle so the index poll cannot
      // emit a second native notification with a recency-based key.
      lastBusyBySession.set(sessionId, false);
    },

    handleSessionDetail(detail, context) {
      const sessionId = normalizeNotificationText(detail.id);
      if (!sessionId) {
        return;
      }

      const phase = normalizeNotificationText(detail.currentPhase || detail.status);
      const busy = isBusyPhase(phase);
      const terminalPhase = terminalPhaseForValue(detail.currentPhase, detail.status);
      observeSessionPhase(sessionId, busy, terminalPhase, () => {
        const latest = latestAssistantTurnMessage(detail);
        const turnId = detailTurnId(detail, latest);
        if (!turnId) {
          return;
        }
        emitSessionCompletion({
          sessionId,
          turnId,
          terminalStatus: notificationStatusForTerminalPhase(terminalPhase),
          completedAt: normalizeNotificationText(latest?.timestamp) || undefined,
          sessionLabel: sessionLabelFromContext(sessionId, context, detail.title, detail.agentDisplayName),
          suppressWhenFocused: shouldSuppressWhenFocused(sessionId, context),
        });
      });
    },

    handleSessionSummaries(sessions, context) {
      for (const session of sessions) {
        const sessionId = normalizeNotificationText(session.id);
        if (!sessionId) {
          continue;
        }
        if (sessionId === normalizeNotificationText(context?.viewedSessionId)) {
          continue;
        }
        const busy = isBusyPhase(session.currentPhase || session.status);
        const terminalPhase = terminalPhaseForValue(session.currentPhase, session.status, session.lastTurnStatus);
        observeSessionPhase(sessionId, busy, terminalPhase, () => {
          const turnId = (
            normalizeNotificationText(session.updatedAt)
            || normalizeNotificationText(session.lastActive)
            || "index"
          );
          emitSessionCompletion({
            sessionId,
            turnId,
            terminalStatus: notificationStatusForTerminalPhase(terminalPhase),
            completedAt: normalizeNotificationText(session.updatedAt || session.lastActive) || undefined,
            sessionLabel: sessionLabelFromContext(sessionId, context, session.title, session.agentDisplayName),
            suppressWhenFocused: shouldSuppressWhenFocused(sessionId, context),
          });
        });
      }
    },
  };
}
