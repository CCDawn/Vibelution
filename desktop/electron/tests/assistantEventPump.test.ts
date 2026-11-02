/** SSE frame parsing and the session-event pump connection loop, plus the two
 * envelope fan-out targets (resident float and launcher control window). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { IPC_CHANNELS } from "../src/ipc.js";
import { LAUNCHER_ASSISTANT_URL } from "../src/assistant/assistantBridge.js";
import { SseFrameParser, startAssistantEventPump, type AssistantEventPumpLease, type SseFrame } from "../src/assistant/assistantEventPump.js";

vi.mock("electron", () => ({
  protocol: { handle: vi.fn() },
  BrowserWindow: class {},
  dialog: {},
  screen: {},
}));
vi.mock("../src/paths.js", () => ({
  resolvePreloadPath: () => "preload.js",
  resolveWorkspaceIconPath: () => "icon.ico",
}));

import { AssistantWindow } from "../src/assistant/assistantWindow.js";
import { ElectronWindowProvider, type ElectronWindowLike } from "../src/windows/electronWindowProvider.js";

afterEach(() => {
  vi.useRealTimers();
});

function sseLease(generationId: string, signal = new AbortController().signal): AssistantEventPumpLease {
  return { generationId, origin: "http://127.0.0.1:9999", token: "token-1", sessionId: "session-1", signal };
}

/** A server-sent-events body that honors aborts like undici does, optionally
 * closing after the queued chunks (uvicorn graceful close). */
function eventStream(init: { signal?: AbortSignal }, chunks: string[], closes = false): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      if (closes) controller.close();
      init.signal?.addEventListener("abort", () => controller.error(new Error("stream aborted")), { once: true });
    },
  });
  return new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } });
}

type FetchInit = { headers?: Record<string, string>; signal?: AbortSignal };

describe("SSE frame parsing", () => {
  it("parses a plain event with id, event and data fields", () => {
    const parser = new SseFrameParser();
    expect(parser.feed('id: 7\nevent: assistant_delta\ndata: {"type":"assistant_delta"}\n\n')).toEqual([
      { kind: "event", name: "assistant_delta", id: "7", data: '{"type":"assistant_delta"}', truncated: false },
    ]);
    expect(parser.lastEventId()).toBe("7");
  });

  it("joins multi-line data with newlines and strips one leading space", () => {
    const parser = new SseFrameParser();
    expect(parser.feed("event: m\ndata: first\ndata:second\ndata: third\n\n")).toEqual([
      { kind: "event", name: "m", data: "first\nsecond\nthird", truncated: false },
    ]);
  });

  it("emits comment-only blocks as keep-alive activity without an event", () => {
    const parser = new SseFrameParser();
    expect(parser.feed(": keep-alive\n\n")).toEqual([{ kind: "comment", text: " keep-alive" }]);
    // A blank block (no data, no comment) dispatches nothing.
    expect(parser.feed("\n\n")).toEqual([]);
  });

  it("reassembles frames split across feed boundaries", () => {
    const parser = new SseFrameParser();
    const source = 'id: 3\nevent: session_detail\ndata: {"type":"session_detail"}\n\n: keep-alive\n\n';
    const frames: SseFrame[] = [];
    for (const character of source) frames.push(...parser.feed(character));
    expect(frames).toEqual([
      { kind: "event", name: "session_detail", id: "3", data: '{"type":"session_detail"}', truncated: false },
      { kind: "comment", text: " keep-alive" },
    ]);
    expect(parser.feed('id: 4\nevent: m\ndata: x\n\n')).toEqual([
      { kind: "event", name: "m", id: "4", data: "x", truncated: false },
    ]);
  });

  it("tolerates CRLF terminators and an event without its own id field", () => {
    const parser = new SseFrameParser();
    const frames = parser.feed('id: 9\r\nevent: a\r\ndata: 1\r\n\r\nevent: b\r\ndata: 2\r\n\r\n');
    expect(frames).toEqual([
      { kind: "event", name: "a", id: "9", data: "1", truncated: false },
      // Per SSE semantics the most recent id applies until a new one arrives.
      { kind: "event", name: "b", id: "9", data: "2", truncated: false },
    ]);
  });

  it("keeps a truncated oversized frame dispatchable without its data", () => {
    const parser = new SseFrameParser();
    const oversized = 'id: 1\nevent: session_detail\ndata: {"detail":"' + "x".repeat(4 * 1024 * 1024 + 16) + '"}\n\n';
    const frames = parser.feed(oversized);
    expect(frames).toEqual([{ kind: "event", name: "session_detail", id: "1", data: "", truncated: true }]);
    expect(parser.lastEventId()).toBe("1");
  });
});

describe("assistant session event pump", () => {
  it("forwards event and heartbeat envelopes to both fans-out targets via publish, dropping payloads", async () => {
    const publish = vi.fn();
    const stop = new AbortController();
    const fetchImpl = vi.fn(async (_url: unknown, init: FetchInit) => eventStream(init, [
      'id: 7\nevent: assistant_delta\ndata: {"type":"assistant_delta","sessionId":"session-1","delta":"' + "long".repeat(256) + '"}\n\n',
      ": keep-alive\n\n",
    ]));
    const pump = startAssistantEventPump({ lease: () => sseLease("g1"), stop: stop.signal,
      fetch: fetchImpl as unknown as typeof fetch, publish, now: () => 5_000 });
    await vi.waitFor(() => expect(publish).toHaveBeenCalledTimes(2));
    const [url, init] = fetchImpl.mock.calls[0] as [unknown, { headers: Record<string, string> }];
    expect(String(url)).toBe("http://127.0.0.1:9999/api/assistant/events");
    // Bearer credential only; Node fetch sends no Origin header.
    expect(init.headers).toEqual({ Authorization: "Bearer token-1" });
    expect(publish).toHaveBeenNthCalledWith(1, { type: "assistant_delta", sessionId: "session-1", ledgerSeq: 7, at: 5_000 });
    expect(publish).toHaveBeenNthCalledWith(2, { type: "heartbeat", sessionId: "session-1", at: 5_000 });
    expect(Object.keys(publish.mock.calls[0][0] as object).sort()).toEqual(["at", "ledgerSeq", "sessionId", "type"]);
    stop.abort();
    await pump.done;
  });

  it("waits for the host lease before connecting, then connects when ready", async () => {
    const publish = vi.fn();
    const stop = new AbortController();
    let leased: AssistantEventPumpLease | null = null;
    const fetchImpl = vi.fn(async (_url: unknown, init: FetchInit) => eventStream(init, [": keep-alive\n\n"]));
    const pump = startAssistantEventPump({ lease: () => leased, stop: stop.signal,
      fetch: fetchImpl as unknown as typeof fetch, publish, now: () => 1 });
    await new Promise(done => setTimeout(done, 20));
    expect(fetchImpl).not.toHaveBeenCalled();
    leased = sseLease("g1");
    await vi.waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(publish).toHaveBeenCalledWith({ type: "heartbeat", sessionId: "session-1", at: 1 }));
    stop.abort();
    await pump.done;
  });

  it("reconnects with exponential backoff capped at five seconds", async () => {
    vi.useFakeTimers();
    const stop = new AbortController();
    const fetchImpl = vi.fn(async () => { throw new Error("transport down"); });
    const pump = startAssistantEventPump({ lease: () => sseLease("g1"), stop: stop.signal,
      fetch: fetchImpl as unknown as typeof fetch, publish: () => undefined, now: () => 1 });
    const settle = () => vi.advanceTimersByTimeAsync(0);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    for (const [step, expected] of [[100, 2], [200, 3], [400, 4], [800, 5], [1600, 6], [3200, 7]] as const) {
      await vi.advanceTimersByTimeAsync(step);
      await settle();
      expect(fetchImpl).toHaveBeenCalledTimes(expected);
    }
    // 6400 exceeds the cap: the retry fires at exactly 5000.
    await vi.advanceTimersByTimeAsync(4999);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(7);
    await vi.advanceTimersByTimeAsync(1);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(8);
    stop.abort();
    await pump.done;
  });

  it("resumes with Last-Event-ID after a dropped stream and resets backoff on frames", async () => {
    vi.useFakeTimers();
    const stop = new AbortController();
    const fetchImpl = vi.fn()
      .mockImplementationOnce(async (_url: unknown, init: FetchInit) =>
        eventStream(init, ['id: 42\nevent: session_detail\ndata: {"type":"session_detail","sessionId":"session-1"}\n\n'], true))
      .mockImplementationOnce(async (_url: unknown, init: FetchInit) =>
        eventStream(init, ['id: 43\nevent: assistant_delta\ndata: {"type":"assistant_delta","sessionId":"session-1"}\n\n'], true))
      .mockImplementationOnce(async (_url: unknown, init: FetchInit) => eventStream(init, [": keep-alive\n\n"]));
    const pump = startAssistantEventPump({ lease: () => sseLease("g1"), stop: stop.signal,
      fetch: fetchImpl as unknown as typeof fetch, publish: () => undefined, now: () => 1 });
    const settle = () => vi.advanceTimersByTimeAsync(0);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(100);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect((fetchImpl.mock.calls[1]![1] as { headers: Record<string, string> }).headers)
      .toEqual({ Authorization: "Bearer token-1", "Last-Event-ID": "42" });
    // A frame arrived on the second connection, so the next failure retries fast.
    await vi.advanceTimersByTimeAsync(100);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect((fetchImpl.mock.calls[2]![1] as { headers: Record<string, string> }).headers)
      .toEqual({ Authorization: "Bearer token-1", "Last-Event-ID": "43" });
    stop.abort();
    await pump.done;
  });

  it("never reconnects once the pump is explicitly stopped", async () => {
    vi.useFakeTimers();
    const stop = new AbortController();
    const fetchImpl = vi.fn(async () => { throw new Error("transport down"); });
    const pump = startAssistantEventPump({ lease: () => sseLease("g1"), stop: stop.signal,
      fetch: fetchImpl as unknown as typeof fetch, publish: () => undefined, now: () => 1 });
    const settle = () => vi.advanceTimersByTimeAsync(0);
    await settle();
    stop.abort();
    await pump.done;
    await vi.advanceTimersByTimeAsync(10_000);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("re-leases the next generation after retirement, resuming a fresh ledger", async () => {
    vi.useFakeTimers();
    const stop = new AbortController();
    const generation = new AbortController();
    let leased = sseLease("g1", generation.signal);
    const fetchImpl = vi.fn()
      .mockImplementationOnce(async (_url: unknown, init: FetchInit) =>
        eventStream(init, ['id: 9\nevent: session_detail\ndata: {"type":"session_detail"}\n\n'], true))
      .mockImplementationOnce(async (_url: unknown, init: FetchInit) => eventStream(init, [": keep-alive\n\n"]));
    const pump = startAssistantEventPump({ lease: () => leased, stop: stop.signal,
      fetch: fetchImpl as unknown as typeof fetch, publish: () => undefined, now: () => 1 });
    const settle = () => vi.advanceTimersByTimeAsync(0);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    // Retire the old generation and ready the replacement before the backoff elapses.
    generation.abort();
    leased = sseLease("g2");
    await vi.advanceTimersByTimeAsync(100);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect((fetchImpl.mock.calls[1]![1] as { headers: Record<string, string> }).headers)
      .toEqual({ Authorization: "Bearer token-1" });
    stop.abort();
    await pump.done;
  });

  it("treats a silent connection as dead after the idle deadline", async () => {
    vi.useFakeTimers();
    const stop = new AbortController();
    const signals: AbortSignal[] = [];
    const fetchImpl = vi.fn(async (_url: unknown, init: FetchInit) => {
      signals.push(init.signal!);
      return eventStream(init, []);
    });
    const pump = startAssistantEventPump({ lease: () => sseLease("g1"), stop: stop.signal,
      fetch: fetchImpl as unknown as typeof fetch, publish: () => undefined, now: () => 1, idleDeadlineMs: 45_000 });
    const settle = () => vi.advanceTimersByTimeAsync(0);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(44_999);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await settle();
    expect(signals[0]!.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(100);
    await settle();
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    stop.abort();
    await pump.done;
  });
});

type SentMessage = { channel: string; payload: unknown };

class FakeWindow implements ElectronWindowLike {
  readonly id = 7;
  sent: SentMessage[] = [];
  private destroyed = false;
  private handlers = new Map<string, Array<(...args: unknown[]) => void>>();
  constructor(private url: string) {}
  readonly webContents = {
    getOSProcessId: () => 7070,
    getURL: () => this.url,
    on: (event: string, listener: (...args: unknown[]) => void) => { this.track(`webContents:${event}`, listener); return this.webContents; },
    setWindowOpenHandler: () => undefined,
    send: (channel: string, payload: unknown) => { this.sent.push({ channel, payload }); },
  };
  focus(): void { this.track("focus"); }
  show(): void { this.track("show"); }
  hide(): void { this.track("hide"); }
  close(): void { this.destroyed = true; this.emit("closed"); }
  destroy(): void { this.destroyed = true; this.emit("closed"); }
  loadURL(url: string): Promise<void> { this.url = url; return Promise.resolve(); }
  isDestroyed(): boolean { return this.destroyed; }
  isFocused(): boolean { return false; }
  isMinimized(): boolean { return false; }
  restore(): void { this.track("restore"); }
  on(event: string, listener: (...args: unknown[]) => void): unknown { this.track(event, listener); return this; }
  emit(event: string, ...args: unknown[]): void {
    for (const listener of this.handlers.get(event) ?? []) listener(...args);
  }
  private track(event: string, listener?: (...args: unknown[]) => void): void {
    if (listener) this.handlers.set(event, [...(this.handlers.get(event) ?? []), listener]);
  }
}

const desktopPaths = {
  schemaVersion: 1,
  desktopBundleRoot: "C:/Program Files/Vibelution/resources/app.asar/dist",
  resourcesRoot: "C:/Program Files/Vibelution/resources",
  workspaceRoot: "C:/Users/Administrator/Desktop/Vibelution",
  userDataRoot: "C:/Users/Administrator/AppData/Roaming/Vibelution",
};

describe("session event fan-out targets", () => {
  const envelope = { type: "assistant_delta", sessionId: "session-1", ledgerSeq: 7, at: 5_000 };

  it("sends the envelope on the assistant:session-event channel to the float", () => {
    const float = new AssistantWindow({} as never, {} as never, () => false);
    (float as unknown as { window: unknown }).window = {
      isDestroyed: () => false,
      webContents: { getURL: () => LAUNCHER_ASSISTANT_URL, send: vi.fn() },
    };
    expect(float.publishSessionEvent(envelope)).toBe(true);
    const webContents = (float as unknown as { window: { webContents: { send: ReturnType<typeof vi.fn> } } }).window.webContents;
    expect(webContents.send).toHaveBeenCalledExactlyOnceWith(IPC_CHANNELS.assistantSessionEvent, envelope);
  });

  it("silently drops the float push when the window is gone or off-route", () => {
    const float = new AssistantWindow({} as never, {} as never, () => false);
    expect(float.publishSessionEvent(envelope)).toBe(false);
    const send = vi.fn();
    (float as unknown as { window: unknown }).window = {
      isDestroyed: () => true,
      webContents: { getURL: () => LAUNCHER_ASSISTANT_URL, send },
    };
    expect(float.publishSessionEvent(envelope)).toBe(false);
    (float as unknown as { window: unknown }).window = {
      isDestroyed: () => false,
      webContents: { getURL: () => "vibelution-launcher://launcher/other", send },
    };
    expect(float.publishSessionEvent(envelope)).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it("sends the envelope on the assistant:session-event channel to the launcher control window", async () => {
    let control: FakeWindow | undefined;
    const provider = new ElectronWindowProvider(desktopPaths as never, "http://127.0.0.1:8765/launcher", "http://127.0.0.1:8000", {
      createLauncherWindow: url => { control = new FakeWindow(url); return control; },
    });
    await provider.openLauncher();
    expect(provider.sendToLauncher(IPC_CHANNELS.assistantSessionEvent, envelope)).toBe(true);
    expect(control!.sent).toEqual([{ channel: IPC_CHANNELS.assistantSessionEvent, payload: envelope }]);
    control!.destroy();
    expect(provider.sendToLauncher(IPC_CHANNELS.assistantSessionEvent, envelope)).toBe(false);
  });
});
