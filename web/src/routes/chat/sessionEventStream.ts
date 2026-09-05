import { isFetchAbortError } from "../../api/chat";
import { consumeGuardedEventStream } from "./guardedEventStream";

const SESSION_STREAM_RECONNECT_MS = 3_000;

export type SessionEventStream = {
  readonly readyState: number;
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
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  private readonly listeners = new Map<string, Set<EventListener>>();
  private controller: AbortController | null = null;
  private reconnectTimer: number | null = null;
  private closed = false;

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
        onOpen: () => {
          if (this.closed || controller.signal.aborted) return;
          this.readyState = 1;
          this.onopen?.(new Event("open"));
        },
        onFrame: (frame) => {
          if (this.closed || controller.signal.aborted) return;
          const event = new MessageEvent<string>(frame.event, { data: frame.data });
          for (const listener of this.listeners.get(frame.event) ?? []) listener(event);
        },
      });
      if (!this.closed && !controller.signal.aborted) this.scheduleReconnect();
    } catch (error) {
      if (!this.closed && !controller.signal.aborted && !isFetchAbortError(error)) {
        this.scheduleReconnect();
      }
    } finally {
      if (this.controller === controller) this.controller = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.closed || this.reconnectTimer !== null) return;
    this.readyState = 0;
    this.onerror?.(new Event("error"));
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, SESSION_STREAM_RECONNECT_MS);
  }
}

export function createSessionEventStream(sessionId: string): SessionEventStream {
  return new FetchSessionEventStream(sessionEventsUrl(sessionId));
}
