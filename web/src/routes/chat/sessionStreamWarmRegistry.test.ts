// @vitest-environment happy-dom
/**
 * Unit contract for the session stream keep-warm registry: reference counting,
 * 30s delayed release, single warm slot, parked watermark tracking, dispose.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SessionEventStream } from "./sessionEventStream";
import {
  acquireSessionStream,
  disposeSessionStreams,
  hasSessionStreamEntry,
  peekParkedSessionStreamLedgerSeq,
  releaseSessionStream,
  SESSION_STREAM_WARM_MS,
} from "./sessionStreamWarmRegistry";

class FakeStream {
  static created: FakeStream[] = [];

  readonly listeners = new Map<string, Set<(event: { data: string }) => void>>();
  readyState = 1;
  closed = false;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor() {
    FakeStream.created.push(this);
  }

  addEventListener(type: string, callback: (event: { data: string }) => void) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(callback);
  }

  removeEventListener(type: string, callback: (event: { data: string }) => void) {
    this.listeners.get(type)?.delete(callback);
  }

  emit(type: string, data: string) {
    for (const listener of this.listeners.get(type) ?? []) listener({ data });
  }

  close() {
    this.closed = true;
    this.readyState = 2;
  }
}

function factory(): (id: string) => SessionEventStream {
  return () => new FakeStream() as unknown as SessionEventStream;
}

function deltaFrame(ledgerSeq: number) {
  return JSON.stringify({ type: "assistant_delta", sessionId: "s1", ledgerSeq });
}

function detailFrame(ledgerSeq: number) {
  return JSON.stringify({ type: "session_detail", sessionId: "s1", ledgerSeq, detail: { ledgerSeq } });
}

beforeEach(() => {
  FakeStream.created = [];
});

afterEach(() => {
  disposeSessionStreams();
  vi.useRealTimers();
});

describe("sessionStreamWarmRegistry", () => {
  it("creates the stream once per session and reuses it across acquires", () => {
    const create = factory();
    const first = acquireSessionStream("s1", create);
    const second = acquireSessionStream("s1", create);
    expect(FakeStream.created).toHaveLength(1);
    expect(second.stream).toBe(first.stream);
    expect(second.reusedWarm).toBe(true);
    expect(second.parkedLedgerSeq).toBe(0);
    expect(hasSessionStreamEntry("s1")).toBe(true);
  });

  it("keeps the stream open on release and hard-closes it after the warm window", () => {
    vi.useFakeTimers();
    const create = factory();
    const acquired = acquireSessionStream("s1", create);
    releaseSessionStream("s1", acquired.stream);
    expect(acquired.stream.closed).toBe(false);
    expect(hasSessionStreamEntry("s1")).toBe(true);

    vi.advanceTimersByTime(SESSION_STREAM_WARM_MS - 1);
    expect(acquired.stream.closed).toBe(false);

    vi.advanceTimersByTime(1);
    expect(acquired.stream.closed).toBe(true);
    expect(hasSessionStreamEntry("s1")).toBe(false);
  });

  it("clears the warm timer when a parked stream is re-acquired", () => {
    vi.useFakeTimers();
    const create = factory();
    const first = acquireSessionStream("s1", create);
    releaseSessionStream("s1", first.stream);

    vi.advanceTimersByTime(SESSION_STREAM_WARM_MS - 5_000);
    const second = acquireSessionStream("s1", create);
    expect(second.reusedWarm).toBe(true);
    expect(second.stream).toBe(first.stream);
    expect(FakeStream.created).toHaveLength(1);

    vi.advanceTimersByTime(SESSION_STREAM_WARM_MS * 2);
    expect(first.stream.closed).toBe(false);
  });

  it("keeps the stream live until every reference is released", () => {
    vi.useFakeTimers();
    const create = factory();
    const acquired = acquireSessionStream("s1", create);
    acquireSessionStream("s1", create);

    releaseSessionStream("s1", acquired.stream);
    vi.advanceTimersByTime(SESSION_STREAM_WARM_MS * 2);
    // One owner remains: the stream never parked, so no warm timer fired.
    expect(acquired.stream.closed).toBe(false);
    expect(hasSessionStreamEntry("s1")).toBe(true);

    releaseSessionStream("s1", acquired.stream);
    vi.advanceTimersByTime(SESSION_STREAM_WARM_MS);
    expect(acquired.stream.closed).toBe(true);
  });

  it("keeps at most one warm session: acquiring another session closes the parked one", () => {
    vi.useFakeTimers();
    const create = factory();
    const first = acquireSessionStream("s1", create);
    releaseSessionStream("s1", first.stream);
    expect(first.stream.closed).toBe(false);

    const second = acquireSessionStream("s2", create);
    expect(first.stream.closed).toBe(true);
    expect(hasSessionStreamEntry("s1")).toBe(false);
    expect(hasSessionStreamEntry("s2")).toBe(true);

    releaseSessionStream("s2", second.stream);
    vi.advanceTimersByTime(SESSION_STREAM_WARM_MS);
    expect(second.stream.closed).toBe(true);
  });

  it("records only the ledger watermark from parked frames and consumes it on acquire", () => {
    vi.useFakeTimers();
    const create = factory();
    const acquired = acquireSessionStream("s1", create);
    releaseSessionStream("s1", acquired.stream);

    acquired.stream.emit("assistant_delta", deltaFrame(4));
    acquired.stream.emit("session_detail", detailFrame(7));
    acquired.stream.emit("assistant_delta", deltaFrame(5));
    acquired.stream.emit("assistant_delta", "not-json");
    expect(peekParkedSessionStreamLedgerSeq("s1")).toBe(7);

    const reacquired = acquireSessionStream("s1", create);
    expect(reacquired.parkedLedgerSeq).toBe(7);
    expect(peekParkedSessionStreamLedgerSeq("s1")).toBe(0);
  });

  it("ignores releases for unknown or stale streams", () => {
    vi.useFakeTimers();
    const create = factory();
    const acquired = acquireSessionStream("s1", create);

    releaseSessionStream("s-unknown", acquired.stream);
    releaseSessionStream("s1", new FakeStream() as unknown as SessionEventStream);
    expect(hasSessionStreamEntry("s1")).toBe(true);
    expect(acquired.stream.closed).toBe(false);
    expect(FakeStream.created).toHaveLength(2);

    releaseSessionStream("s1", acquired.stream);
    vi.advanceTimersByTime(SESSION_STREAM_WARM_MS);
    expect(acquired.stream.closed).toBe(true);
  });

  it("does not re-warm a closed stream: the next acquire creates a fresh one", () => {
    vi.useFakeTimers();
    const create = factory();
    const acquired = acquireSessionStream("s1", create);
    // Simulates an in-place force close (grace timeout / recovery path).
    acquired.stream.close();

    releaseSessionStream("s1", acquired.stream);
    expect(hasSessionStreamEntry("s1")).toBe(false);

    const next = acquireSessionStream("s1", create);
    expect(next.reusedWarm).toBe(false);
    expect(next.stream).not.toBe(acquired.stream);
    expect(FakeStream.created).toHaveLength(2);
  });

  it("disposes every tracked stream immediately", () => {
    const create = factory();
    const first = acquireSessionStream("s1", create);
    const second = acquireSessionStream("s2", create);
    releaseSessionStream("s2", second.stream);

    disposeSessionStreams();
    expect(first.stream.closed).toBe(true);
    expect(second.stream.closed).toBe(true);
    expect(hasSessionStreamEntry("s1")).toBe(false);
    expect(hasSessionStreamEntry("s2")).toBe(false);
  });
});
