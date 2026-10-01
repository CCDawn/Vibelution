// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests, seedControlTokenForTests } from "../../api/client";
import { createSessionEventStream, sessionEventsUrl } from "./sessionEventStream";

afterEach(() => {
  resetControlTokenForTests();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("session event stream", () => {
  it("uses the canonical encoded session events URL", () => {
    expect(sessionEventsUrl("session a/1")).toBe("/api/sessions/session%20a%2F1/events?initial=none");
  });

  it("opens through the control-token fetch boundary and routes named frames", async () => {
    seedControlTokenForTests("session-stream-token");
    const payload = JSON.stringify({ type: "session_detail", sessionId: "session-1" });
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(`event: session_detail\ndata: ${payload}\n\n`));
        controller.close();
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(body, {
      status: 200,
      headers: { "content-type": "text/event-stream" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const opened = vi.fn();
    const received = vi.fn();
    const stream = createSessionEventStream("session-1");
    stream.onopen = opened;
    stream.addEventListener("session_detail", ((event: MessageEvent<string>) => {
      received(event.data);
      stream.close();
    }) as EventListener);

    await vi.waitFor(() => expect(received).toHaveBeenCalledWith(payload));

    expect(opened).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/sessions/session-1/events?initial=none",
      expect.objectContaining({ credentials: "same-origin" }),
    );
    const requestInit = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(requestInit.headers).get("X-Vibelution-Control-Token")).toBe("session-stream-token");
  });

  it("mirrors the browser Last-Event-ID behavior: reconnects replay the last id line", async () => {
    seedControlTokenForTests("session-stream-token");
    vi.useFakeTimers();
    try {
      const firstPayload = JSON.stringify({ type: "session_detail", sessionId: "session-1" });
      const firstBody = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(
            new TextEncoder().encode(`id: 7\nevent: session_detail\ndata: ${firstPayload}\n\n`),
          );
          controller.close();
        },
      });
      const secondBody = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.close();
        },
      });
      const fetchMock = vi
        .fn()
        .mockResolvedValueOnce(new Response(firstBody, { status: 200, headers: { "content-type": "text/event-stream" } }))
        .mockResolvedValue(new Response(secondBody, { status: 200, headers: { "content-type": "text/event-stream" } }));
      vi.stubGlobal("fetch", fetchMock);

      const stream = createSessionEventStream("session-1");
      const receivedLastEventId: string[] = [];
      stream.addEventListener("session_detail", ((event: MessageEvent<string>) => {
        receivedLastEventId.push(event.lastEventId);
      }) as EventListener);

      // First connection consumed; the guarded stream ends and schedules the
      // 3s auto-reconnect (the fetch-stream equivalent of EventSource retry).
      await vi.advanceTimersByTimeAsync(0);
      expect(receivedLastEventId).toEqual(["7"]);
      await vi.advanceTimersByTimeAsync(3_000);

      expect(fetchMock).toHaveBeenCalledTimes(2);
      const reconnectHeaders = new Headers((fetchMock.mock.calls[1]?.[1] as RequestInit).headers);
      expect(reconnectHeaders.get("Last-Event-ID")).toBe("7");
      stream.close();
      await vi.advanceTimersByTimeAsync(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
