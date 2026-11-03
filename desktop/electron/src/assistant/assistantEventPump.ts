/** Main-only pump for the host session-event SSE stream. Envelopes always
 * carry identity and ordering; assistant_delta frames are additionally reduced
 * to a small content projection (done flag, turn id, tail-capped answer-text
 * preview) so renderers can show live output without re-pulling detail. A hard
 * per-envelope size cap falls back to an identity-only envelope and logs when
 * exceeded, and the bearer token never leaves this process. */

export type AssistantSessionEventEnvelope = {
  type: string;
  sessionId: string;
  ledgerSeq?: number;
  at: number;
  /** assistant_delta only, all optional and additive. `done` is the frame's
   * terminal flag (only true proves the turn finished); `turnId` names the
   * generating turn; `textPreview` is the newest assistant answer text from
   * the frame's turnItems projection, tail-capped — a display hint, never an
   * authority (session_detail stays authoritative). Absent means unknown. */
  turnId?: string;
  done?: boolean;
  textPreview?: string;
};

const DELTA_TURN_ID_MAX_CHARS = 200;
const DELTA_TEXT_PREVIEW_MAX_CHARS = 8_000;
/** IPC/renderer safety cap for one published envelope. The projection above
 * keeps normal envelopes far below it; exceeding it means a pathological host
 * frame, which fans out as identity only. */
const MAX_ENVELOPE_CHARS = 256 * 1024;

/** Newest assistant answer text from one assistant_delta frame's turnItems
 * projection: the last `agent_message` item's body, tail-capped so the newest
 * streaming output survives. reasoning/tool/status items are not the response
 * body and are never forwarded; the projection is read, not copied. */
function deltaTextPreview(turnItems: unknown): string | undefined {
  if (!Array.isArray(turnItems)) return undefined;
  for (let index = turnItems.length - 1; index >= 0; index -= 1) {
    const item: unknown = turnItems[index];
    if (!item || typeof item !== "object" || Array.isArray(item)) continue;
    const record = item as Record<string, unknown>;
    if (record.type !== "agent_message" || typeof record.text !== "string" || !record.text) continue;
    const text = record.text;
    if (text.length <= DELTA_TEXT_PREVIEW_MAX_CHARS) return text;
    // Tail wins for live display; avoid splitting a surrogate pair at the cut.
    const cut = text.length - DELTA_TEXT_PREVIEW_MAX_CHARS;
    const preview = text.slice(cut);
    const head = preview.charCodeAt(0);
    return head >= 0xdc00 && head <= 0xdfff ? preview.slice(1) : preview;
  }
  return undefined;
}

/** One parsed SSE frame reduced to the publish envelope: identity and ordering
 * for every event type, plus the bounded assistant_delta content projection.
 * If the assembled envelope would exceed the size cap, the content projection
 * is stripped back to identity (identity itself clamped) and the fallback is
 * logged — a huge host frame can never fan out to renderer windows. */
export function sessionEventEnvelope(input: {
  data: Record<string, unknown> | null;
  frameName: string;
  frameId?: string;
  leaseSessionId: string;
  at: number;
}): AssistantSessionEventEnvelope {
  const data = input.data;
  const type = typeof data?.type === "string" && data.type ? data.type : input.frameName;
  const sessionId = typeof data?.sessionId === "string" && data.sessionId ? data.sessionId : input.leaseSessionId;
  const seq = typeof input.frameId === "string" && /^[0-9]+$/.test(input.frameId) ? Number(input.frameId) : Number.NaN;
  const ledger = Number.isSafeInteger(seq) && seq >= 0 ? { ledgerSeq: seq } : {};
  const envelope: AssistantSessionEventEnvelope = { type, sessionId, ...ledger, at: input.at };
  if (type === "assistant_delta" && data) {
    if (typeof data.done === "boolean") envelope.done = data.done;
    if (typeof data.turnId === "string" && data.turnId) envelope.turnId = data.turnId.slice(0, DELTA_TURN_ID_MAX_CHARS);
    const preview = deltaTextPreview(data.turnItems);
    if (preview !== undefined) envelope.textPreview = preview;
  }
  if (JSON.stringify(envelope).length > MAX_ENVELOPE_CHARS) {
    console.warn("ASSISTANT_EVENT_ENVELOPE_OVERSIZE",
      { type: envelope.type.slice(0, 80), sessionId: envelope.sessionId.slice(0, 80), at: input.at });
    return { type: envelope.type.slice(0, 80), sessionId: envelope.sessionId.slice(0, 80), ...ledger, at: input.at };
  }
  return envelope;
}

/** One live host generation's connection facts, leased per connection attempt. */
export type AssistantEventPumpLease = {
  generationId: string;
  origin: string;
  token: string;
  sessionId: string;
  signal: AbortSignal;
};

export type SseFrame =
  | { kind: "comment"; text: string }
  | { kind: "event"; name: string; id?: string; data: string; truncated: boolean };

const DEFAULT_MIN_RETRY_MS = 100;
const DEFAULT_MAX_RETRY_MS = 5_000;
const DEFAULT_IDLE_DEADLINE_MS = 45_000;
const DEFAULT_MAX_FRAME_BYTES = 4 * 1024 * 1024;

/** Incremental SSE frame parser (id/event/data/comment, blank-line dispatch,
 * multi-line data joined with "\n", CRLF tolerated, comment-only blocks are
 * heartbeat activity). A truncated frame keeps its event name but drops data. */
export class SseFrameParser {
  private buffer = "";
  private eventType = "";
  private dataLines: string[] = [];
  private dataBytes = 0;
  private dataSeen = false;
  private comment = "";
  private sawComment = false;
  private discarding = false;
  private lastId?: string;

  feed(chunk: string): SseFrame[] {
    this.buffer += chunk;
    const frames: SseFrame[] = [];
    for (;;) {
      const end = this.buffer.search(/\r\n|\r|\n/);
      if (end < 0) {
        // An unterminated block cannot legitimately exceed the frame cap.
        if (this.buffer.length > DEFAULT_MAX_FRAME_BYTES) this.buffer = "";
        break;
      }
      // A lone trailing "\r" may precede "\n" in the next chunk; wait for it.
      if (this.buffer[end] === "\r" && end + 1 === this.buffer.length) break;
      const line = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + (this.buffer[end] === "\r" && this.buffer[end + 1] === "\n" ? 2 : 1));
      const frame = this.line(line);
      if (frame) frames.push(frame);
    }
    return frames;
  }

  lastEventId(): string | undefined {
    return this.lastId;
  }

  private line(line: string): SseFrame | null {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) {
      this.sawComment = true;
      this.comment = line.slice(1);
      return null;
    }
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.eventType = value;
    else if (field === "data") {
      this.dataSeen = true;
      if (!this.discarding) {
        this.dataLines.push(value);
        this.dataBytes += value.length;
        if (this.dataBytes > DEFAULT_MAX_FRAME_BYTES) {
          this.dataLines = [];
          this.discarding = true;
        }
      }
    } else if (field === "id" && !value.includes("\u0000")) this.lastId = value;
    // "retry" and unknown fields stay unhandled: reconnection policy is owned here.
    return null;
  }

  private dispatch(): SseFrame | null {
    const data = this.dataLines.join("\n");
    const frame: SseFrame | null = this.dataSeen
      ? { kind: "event", name: this.eventType || "message", ...(this.lastId !== undefined ? { id: this.lastId } : {}), data, truncated: this.discarding }
      : this.sawComment
        ? { kind: "comment", text: this.comment }
        : null;
    this.eventType = "";
    this.dataLines = [];
    this.dataBytes = 0;
    this.dataSeen = false;
    this.comment = "";
    this.sawComment = false;
    this.discarding = false;
    return frame;
  }
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  return new Promise(done => {
    const onAbort = () => { clearTimeout(timer); done(); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", onAbort); done(); }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export function startAssistantEventPump(options: {
  /** Current generation connection facts, or null while the host is not ready. */
  lease: () => AssistantEventPumpLease | null;
  /** Explicit pump-lifetime stop; generation retirement comes through lease.signal. */
  stop: AbortSignal;
  publish: (envelope: AssistantSessionEventEnvelope) => void;
  fetch?: typeof globalThis.fetch;
  now?: () => number;
  minRetryMs?: number;
  maxRetryMs?: number;
  idleDeadlineMs?: number;
}): { done: Promise<void> } {
  const minRetryMs = options.minRetryMs ?? DEFAULT_MIN_RETRY_MS;
  const maxRetryMs = options.maxRetryMs ?? DEFAULT_MAX_RETRY_MS;
  const idleDeadlineMs = options.idleDeadlineMs ?? DEFAULT_IDLE_DEADLINE_MS;
  const fetchImpl = options.fetch ?? globalThis.fetch;
  const now = options.now ?? Date.now;
  const stop = options.stop;

  const run = async (): Promise<void> => {
    let retryMs = minRetryMs;
    let lastEventId: string | null = null;
    let connectedGeneration: string | null = null;
    while (!stop.aborted) {
      const lease = options.lease();
      if (!lease || lease.signal.aborted) {
        // Host not ready or churning generations: the old ledger is void.
        if (connectedGeneration !== null) { connectedGeneration = null; lastEventId = null; }
        await sleep(retryMs, stop);
        retryMs = Math.min(maxRetryMs, retryMs * 2);
        continue;
      }
      if (connectedGeneration !== lease.generationId) { connectedGeneration = lease.generationId; lastEventId = null; }
      const idle = new AbortController();
      let idleTimer: ReturnType<typeof setTimeout> | undefined;
      let idleDead = false;
      const armIdle = () => {
        clearTimeout(idleTimer);
        idleTimer = setTimeout(() => { idleDead = true; idle.abort(); }, idleDeadlineMs);
        idleTimer.unref?.();
      };
      // Node fetch never sends an Origin header, and the host middleware forbids one.
      const connection = AbortSignal.any([lease.signal, stop, idle.signal]);
      const headers: Record<string, string> = { Authorization: `Bearer ${lease.token}` };
      if (lastEventId !== null) headers["Last-Event-ID"] = lastEventId;
      try {
        const response = await fetchImpl(`${lease.origin}/api/assistant/events`, {
          redirect: "error",
          signal: connection,
          headers,
        });
        if (!response.ok) {
          await response.body?.cancel().catch(() => undefined);
          throw new Error("ASSISTANT_EVENT_STREAM_HTTP_FAILED");
        }
        if (!response.body) throw new Error("ASSISTANT_EVENT_STREAM_INVALID");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const parser = new SseFrameParser();
        try {
          armIdle();
          for (;;) {
            const part = await reader.read();
            if (connection.aborted) throw new Error(idleDead ? "ASSISTANT_EVENT_STREAM_IDLE" : "ASSISTANT_EVENT_STREAM_STOPPED");
            if (part.done) throw new Error("ASSISTANT_EVENT_STREAM_ENDED");
            armIdle();
            for (const frame of parser.feed(decoder.decode(part.value, { stream: true }))) {
              armIdle();
              // Any complete frame — event or keep-alive comment — proves liveness.
              retryMs = minRetryMs;
              if (frame.kind === "comment") {
                options.publish({ type: "heartbeat", sessionId: lease.sessionId || "", at: now() });
                continue;
              }
              if (frame.id !== undefined) lastEventId = frame.id;
              let data: Record<string, unknown> | null = null;
              if (frame.data && !frame.truncated) {
                try {
                  const parsed: unknown = JSON.parse(frame.data);
                  if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) data = parsed as Record<string, unknown>;
                } catch { data = null; }
              }
              options.publish(sessionEventEnvelope({ data, frameName: frame.name,
                ...(frame.id !== undefined ? { frameId: frame.id } : {}), leaseSessionId: lease.sessionId || "", at: now() }));
            }
          }
        } finally {
          clearTimeout(idleTimer);
          await reader.cancel().catch(() => undefined);
          reader.releaseLock();
        }
      } catch {
        clearTimeout(idleTimer);
        if (stop.aborted) return;
        if (!lease.signal.aborted) {
          // Generation retirement re-leases immediately; everything else backs off.
          await sleep(retryMs, stop);
          retryMs = Math.min(maxRetryMs, retryMs * 2);
        }
      }
    }
  };
  return { done: run() };
}
