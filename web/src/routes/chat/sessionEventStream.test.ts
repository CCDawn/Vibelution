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
});
