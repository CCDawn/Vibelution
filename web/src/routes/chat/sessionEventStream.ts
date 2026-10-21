import { isFetchAbortError, isFetchJsonHttpError } from "../../api/chat";
import { consumeGuardedEventStream } from "./guardedEventStream";
import { isPermanentSessionStreamFailureStatus } from "./chatSessionStreamConnect";

const SESSION_STREAM_RECONNECT_MS = 3_000;

/**
 * A permanent transport failure (404/410/401/403): the stream stops for good
 * instead of looping the reconnect timer. The session-detail consumer folds
 * this into the shouldConnect chain and the existing tombstone rendering.
 */
export type SessionEventStreamTerminalFailure = {
  status: number;
};

export type SessionEventStream = {
  readonly readyState: number;
  /** Non-null once a permanent HTTP failure ended this stream; never resets. */
  readonly terminalFailure: SessionEventStreamTerminalFailure | null;
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: string, callback: EventListener): void;
  removeEventListener(type: string, callback: EventListener): void;
  close(): void;
};

export function sessionEventsUrl(sessionId: string): string {
  return `/api/sessions/${encodeURIComponent(String(sessionId || "").trim())}/events?initial=none`;
}

class FetchSessionEventStream implements SessionEventStream {
  readyState = 0;
  terminalFailure: SessionEventStreamTerminalFailure | null = null;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  private readonly listeners = new Map<string, Set<EventListener>>();
  private controller: AbortController | null = null;
  private reconnectTimer: number | null = null;
  private closed = false;
  /**
   * Last journal sequence seen on an `id:` line. Native EventSource replays it
   * as the Last-Event-ID header on auto-reconnect; this fetch stream mirrors
   * that browser behavior manually so the server can resume the journal
   * window instead of forcing a full resync.
   */
  private lastEventId = "";

  constructor(private readonly url: string) {
    queueMicrotask(() => void this.connect());
  }

  addEventListener(type: string, callback: EventListener): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(callback);
  }

  removeEventListener(type: string, callback: EventListener): void {
    this.listeners.get(type)?.delete(callback);
  }

  close(): void {
    this.closed = true;
    this.readyState = 2;
    this.controller?.abort();
    this.controller = null;
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private async connect(): Promise<void> {
    if (this.closed) return;
    this.readyState = 0;
    const controller = new AbortController();
    this.controller = controller;
    try {
      await consumeGuardedEventStream({
        url: this.url,
        signal: controller.signal,
        headers: this.lastEventId ? { "Last-Event-ID": this.lastEventId } : undefined,
        onOpen: () => {
          if (this.closed || controller.signal.aborted) return;
          this.readyState = 1;
          this.onopen?.(new Event("open"));
        },
        onFrame: (frame) => {
          if (this.closed || controller.signal.aborted) return;
          if (frame.id) this.lastEventId = frame.id;
          const event = new MessageEvent<string>(frame.event, {
            data: frame.data,
            lastEventId: frame.id ?? "",
          });
          for (const listener of this.listeners.get(frame.event) ?? []) listener(event);
        },
      });
      if (!this.closed && !controller.signal.aborted) this.scheduleReconnect();
    } catch (error) {
      if (this.closed || controller.signal.aborted || isFetchAbortError(error)) {
        return;
      }
      // A permanent HTTP failure (session gone / unauthorized) can never be
      // fixed by reconnecting: enter the terminal state instead of looping the
      // 3s retry. 5xx and network errors keep the existing reconnect policy.
      if (isFetchJsonHttpError(error) && isPermanentSessionStreamFailureStatus(error.status)) {
        this.enterTerminalFailure(error.status);
        return;
      }
      this.scheduleReconnect();
    } finally {
      if (this.controller === controller) this.controller = null;
    }
  }

  /**
   * Close the stream for good and report the failure once. readyState settles
   * at CLOSED (2) so the warm registry drops the entry instead of parking a
   * dead stream, and a later remount re-tries exactly once through a fresh
   * stream (never through this instance).
   */
  private enterTerminalFailure(status: number): void {
    if (this.closed) return;
    this.closed = true;
    this.terminalFailure = { status };
    this.readyState = 2;
    this.controller = null;
    this.onerror?.(new Event("error"));
  }

  private scheduleReconnect(): void {
    if (this.closed || this.reconnectTimer !== null) return;
    this.readyState = 0;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, SESSION_STREAM_RECONNECT_MS);
    this.onerror?.(new Event("error"));
  }
}

export function createSessionEventStream(sessionId: string): SessionEventStream {
  return new FetchSessionEventStream(sessionEventsUrl(sessionId));
}
