// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests, seedControlTokenForTests } from "../../api/client";
import { consumeGuardedEventStream } from "./guardedEventStream";

afterEach(() => {
  resetControlTokenForTests();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("guarded event stream cleanup", () => {
  it("cancels the response and request when a frame callback throws", async () => {
    seedControlTokenForTests("guarded-stream-token");
    const cancel = vi.fn(() => { throw new Error("cancel failed"); });
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode("event: update\ndata: one\n\n"));
      },
      cancel,
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const failure = new Error("frame handler failed");

    await expect(consumeGuardedEventStream({
      url: "/api/events",
      signal: new AbortController().signal,
      onFrame: () => { throw failure; },
    })).rejects.toBe(failure);

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(request.signal?.aborted).toBe(true);
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("cancels a response when onOpen throws before the first read", async () => {
    seedControlTokenForTests("guarded-stream-token");
    const cancel = vi.fn();
    const body = new ReadableStream<Uint8Array>({ cancel });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const failure = new Error("open handler failed");

    await expect(consumeGuardedEventStream({
      url: "/api/events",
      signal: new AbortController().signal,
      onOpen: () => { throw failure; },
      onFrame: vi.fn(),
    })).rejects.toBe(failure);

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(request.signal?.aborted).toBe(true);
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("aborts the request when the response has no body", async () => {
    seedControlTokenForTests("guarded-stream-token");
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(consumeGuardedEventStream({
      url: "/api/events",
      signal: new AbortController().signal,
      onFrame: vi.fn(),
    })).rejects.toThrow("事件流没有返回响应体");

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(request.signal?.aborted).toBe(true);
  });

  it("preserves a read failure while aborting and releasing the errored response", async () => {
    seedControlTokenForTests("guarded-stream-token");
    const failure = new Error("response read failed");
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.error(failure);
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(consumeGuardedEventStream({
      url: "/api/events",
      signal: new AbortController().signal,
      onFrame: vi.fn(),
    })).rejects.toBe(failure);

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(request.signal?.aborted).toBe(true);
  });
});
