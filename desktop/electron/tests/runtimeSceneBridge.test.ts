import { once } from "node:events";
import { createServer } from "node:http";
import { describe, expect, it, vi } from "vitest";
import {
  RuntimeSceneBridge,
  RuntimeSceneEventRejectedError,
  electronEventPayload
} from "../src/lifecycle/runtimeSceneBridge.js";

describe("RuntimeSceneBridge", () => {
  it("releases a real response socket after accepting headers with an unfinished body", async () => {
    let socketClosed = false;
    const server = createServer((request, response) => {
      request.socket.once("close", () => { socketClosed = true; });
      response.writeHead(202, { "content-type": "application/json" });
      response.write("{\"accepted\":");
    });
    server.listen(0, "127.0.0.1");
    await once(server, "listening");
    const port = (server.address() as { port: number }).port;
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: `http://127.0.0.1:${port}`,
      controlToken: "isolated-token",
      maxBufferedEvents: 2
    });
    try {
      await bridge.record({ eventCode: "exit.requested", message: "message", fields: {} });
      expect(bridge.bufferedCount()).toBe(0);
      await vi.waitFor(() => expect(socketClosed).toBe(true));
    } finally {
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });
  it("bounds a hung event request and keeps its head available for retry", async () => {
    vi.useFakeTimers();
    try {
      let observedSignal: AbortSignal | undefined;
      let hang = true;
      const fetchImpl: typeof fetch = async (_url, init) => {
        if (!hang) return new Response("{}", { status: 202 });
        observedSignal = init?.signal ?? undefined;
        return new Promise<Response>((_resolve, reject) => {
          observedSignal?.addEventListener("abort", () => reject(observedSignal?.reason), { once: true });
        });
      };
      const bridge = new RuntimeSceneBridge({
        launcherOrigin: "http://127.0.0.1:8765",
        controlToken: "token",
        maxBufferedEvents: 2,
        fetchImpl
      });
      const pending = bridge.record({ eventCode: "exit.failed", message: "message", fields: {} });
      await vi.advanceTimersByTimeAsync(5_000);
      await pending;
      expect(observedSignal?.aborted).toBe(true);
      expect(vi.getTimerCount()).toBe(0);
      expect(bridge.bufferedCount()).toBe(1);
      hang = false;
      await bridge.flush();
      expect(bridge.bufferedCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
  it("posts bounded events to the launcher runtime-scene route", async () => {
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 202 }));
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      maxBufferedEvents: 5,
      fetchImpl
    });

    await bridge.record({
      eventCode: "electron.desktop_action.claimed",
      message: "Desktop action claimed.",
      fields: { actionId: "desktop-action-1" }
    });

    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/launcher/runtime-scene/events",
      expect.objectContaining({ method: "POST" })
    );
    const body = JSON.parse(String(fetchImpl.mock.calls[0][1]?.body));
    expect(body).toEqual({
      component: "electron_launcher",
      phase: "desktop_supervisor",
      eventCode: "electron.desktop_action.claimed",
      message: "Desktop action claimed.",
      fields: { actionId: "desktop-action-1" }
    });
  });

  it("bounds event text and buffered offline events", async () => {
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 503 }));
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "token",
      maxBufferedEvents: 2,
      fetchImpl
    });

    await bridge.record({ eventCode: "x".repeat(200), message: "m".repeat(800), fields: { ["k".repeat(120)]: "v".repeat(800) } });
    await bridge.record({ eventCode: "event-2", message: "message-2", fields: {} });
    await bridge.record({ eventCode: "event-3", message: "message-3", fields: {} });

    expect(bridge.bufferedCount()).toBe(2);
    const firstBody = JSON.parse(String(fetchImpl.mock.calls[0][1]?.body));
    expect(firstBody.eventCode).toHaveLength(120);
    expect(firstBody.message).toHaveLength(500);
    expect(Object.keys(firstBody.fields)[0]).toHaveLength(80);
    expect(Object.values(firstBody.fields)[0]).toHaveLength(500);
  });

  it("serializes concurrent flushes and keeps a failed head retryable without duplicate posts", async () => {
    let releaseFirstPost: (() => void) | null = null;
    let postCount = 0;
    const fetchImpl = vi.fn((input: RequestInfo | URL) => {
      void input;
      postCount += 1;
      if (postCount === 1) {
        return new Promise<Response>((resolve) => {
          releaseFirstPost = () => resolve(new Response("{}", { status: 202 }));
        });
      }
      if (postCount === 2) {
        return Promise.resolve(new Response("{}", { status: 503 }));
      }
      return Promise.resolve(new Response("{}", { status: 202 }));
    });
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "token",
      maxBufferedEvents: 5,
      fetchImpl
    });

    const first = bridge.record({ eventCode: "event-1", message: "message-1", fields: {} });
    const second = bridge.record({ eventCode: "event-2", message: "message-2", fields: {} });
    await Promise.resolve();
    expect(postCount).toBe(1);
    releaseFirstPost?.();
    await Promise.all([first, second]);

    expect(bridge.bufferedCount()).toBe(1);
    await bridge.flush();
    expect(bridge.bufferedCount()).toBe(0);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    const bodies = fetchImpl.mock.calls.map((call) => JSON.parse(String(call[1]?.body)));
    expect(bodies.map((body) => body.eventCode)).toEqual(["event-1", "event-2", "event-2"]);
    expect(bodies.filter((body) => body.eventCode === "event-1")).toHaveLength(1);
    expect(bodies.filter((body) => body.eventCode === "event-2")).toHaveLength(2);
  });

  it("hands off the flush owner when a record arrives at the final-post settle boundary", async () => {
    let releaseFinalPost: (() => void) | null = null;
    let boundaryRecord: Promise<void> | null = null;
    let postCount = 0;
    const fetchImpl = vi.fn(() => {
      postCount += 1;
      if (postCount === 1) {
        return new Promise<Response>((resolve) => {
          releaseFinalPost = () => {
            resolve(new Response("{}", { status: 202 }));
            queueMicrotask(() => {
              boundaryRecord = bridge.record({ eventCode: "event-after-settle", message: "message", fields: {} });
            });
          };
        });
      }
      return Promise.resolve(new Response("{}", { status: 202 }));
    });
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "token",
      maxBufferedEvents: 5,
      fetchImpl
    });

    const first = bridge.record({ eventCode: "event-final", message: "message", fields: {} });
    await Promise.resolve();
    expect(postCount).toBe(1);
    releaseFinalPost?.();
    await first;
    await Promise.resolve();
    await boundaryRecord;

    expect(postCount).toBe(2);
    expect(bridge.bufferedCount()).toBe(0);
    const bodies = fetchImpl.mock.calls.map((call) => JSON.parse(String(call[1]?.body)));
    expect(bodies.map((body) => body.eventCode)).toEqual(["event-final", "event-after-settle"]);
  });
});

describe("RuntimeSceneBridge control-token self-heal", () => {
  function controlTokenResponse(token: string, status = 200): Response {
    return new Response(
      JSON.stringify({ header: "X-Vibelution-Control-Token", controlToken: token }),
      { status, headers: { "content-type": "application/json" } }
    );
  }

  function tokenHeaderOf(init?: RequestInit): string {
    const headers = init?.headers as Record<string, string> | undefined;
    return String(headers?.["X-Vibelution-Control-Token"] ?? "");
  }

  function eventCodeOf(init?: RequestInit): string {
    return JSON.parse(String(init?.body)).eventCode as string;
  }

  it.each([403, 401])(
    "refreshes the control token after a %s and retries the queue head with the rotated token",
    async (authStatus) => {
      const eventPosts: Array<{ token: string; eventCode: string }> = [];
      let eventPostCount = 0;
      let tokenFetchCount = 0;
      const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const href = String(input);
        if (href.endsWith("/api/control-token")) {
          tokenFetchCount += 1;
          return controlTokenResponse("fresh-token");
        }
        expect(href).toBe("http://127.0.0.1:8765/api/launcher/runtime-scene/events");
        eventPostCount += 1;
        eventPosts.push({ token: tokenHeaderOf(init), eventCode: eventCodeOf(init) });
        return eventPostCount === 1
          ? new Response("{}", { status: authStatus })
          : new Response("{}", { status: 202 });
      });
      const bridge = new RuntimeSceneBridge({
        launcherOrigin: "http://127.0.0.1:8765",
        controlToken: "stale-token",
        maxBufferedEvents: 5,
        fetchImpl
      });

      await bridge.record({ eventCode: "event-1", message: "message", fields: {} });

      expect(tokenFetchCount).toBe(1);
      expect(eventPosts).toEqual([
        { token: "stale-token", eventCode: "event-1" },
        { token: "fresh-token", eventCode: "event-1" }
      ]);
      expect(bridge.bufferedCount()).toBe(0);

      // The rotated token sticks for later events without another refresh.
      await bridge.record({ eventCode: "event-2", message: "message", fields: {} });
      expect(tokenFetchCount).toBe(1);
      expect(eventPosts[2]).toEqual({ token: "fresh-token", eventCode: "event-2" });
      expect(bridge.bufferedCount()).toBe(0);
    }
  );

  it("backs off after a failed refresh instead of hammering the token endpoint", async () => {
    let now = 0;
    let tokenFetchCount = 0;
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const href = String(input);
      if (href.endsWith("/api/control-token")) {
        tokenFetchCount += 1;
        return new Response("backend unavailable", { status: 500 });
      }
      return new Response("{}", { status: 403 });
    });
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "stale-token",
      maxBufferedEvents: 50,
      fetchImpl,
      clock: () => now,
      tokenRefreshBackoffBaseMs: 1_000,
      tokenRefreshBackoffMaxMs: 30_000
    });

    await bridge.record({ eventCode: "event-1", message: "message", fields: {} });
    expect(tokenFetchCount).toBe(1);

    // Still inside the base backoff window: the head is retried with the old
    // token but no second refresh may be issued.
    await bridge.record({ eventCode: "event-2", message: "message", fields: {} });
    expect(tokenFetchCount).toBe(1);
    expect(bridge.bufferedCount()).toBe(2);

    now = 1_500;
    await bridge.record({ eventCode: "event-3", message: "message", fields: {} });
    expect(tokenFetchCount).toBe(2);

    // Second failure doubles the backoff: eligible again only at 1500 + 2000.
    now = 3_000;
    await bridge.record({ eventCode: "event-4", message: "message", fields: {} });
    expect(tokenFetchCount).toBe(2);
  });

  it("stops refreshing for a cooldown window after repeated failed refreshes", async () => {
    let now = 0;
    let tokenFetchCount = 0;
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const href = String(input);
      if (href.endsWith("/api/control-token")) {
        tokenFetchCount += 1;
        return new Response("backend unavailable", { status: 500 });
      }
      return new Response("{}", { status: 403 });
    });
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "stale-token",
      maxBufferedEvents: 50,
      fetchImpl,
      clock: () => now,
      tokenRefreshBackoffBaseMs: 100,
      tokenRefreshBackoffMaxMs: 400,
      tokenRefreshMaxFailures: 3,
      tokenRefreshCooldownMs: 5_000
    });

    now = 0;
    await bridge.record({ eventCode: "event-1", message: "message", fields: {} });
    now = 100;
    await bridge.record({ eventCode: "event-2", message: "message", fields: {} });
    now = 300;
    await bridge.record({ eventCode: "event-3", message: "message", fields: {} });
    expect(tokenFetchCount).toBe(3);

    // Three consecutive failures opened a cooldown until 300 + 5000; requests
    // inside that window retry the head silently but never touch the token
    // endpoint, even once the exponential backoff alone would allow it.
    now = 2_000;
    await bridge.record({ eventCode: "event-4", message: "message", fields: {} });
    expect(tokenFetchCount).toBe(3);
    now = 5_299;
    await bridge.record({ eventCode: "event-5", message: "message", fields: {} });
    expect(tokenFetchCount).toBe(3);

    // After the cooldown the refresh cycle starts over.
    now = 5_300;
    await bridge.record({ eventCode: "event-6", message: "message", fields: {} });
    expect(tokenFetchCount).toBe(4);
    expect(bridge.bufferedCount()).toBe(6);
  });

  it("does not retry the post when the refreshed token is unchanged", async () => {
    let now = 0;
    let tokenFetchCount = 0;
    let eventPostCount = 0;
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      const href = String(input);
      if (href.endsWith("/api/control-token")) {
        tokenFetchCount += 1;
        return controlTokenResponse("same-token");
      }
      eventPostCount += 1;
      return new Response("{}", { status: 403 });
    });
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "same-token",
      maxBufferedEvents: 50,
      fetchImpl,
      clock: () => now,
      tokenRefreshBackoffBaseMs: 1_000
    });

    await bridge.record({ eventCode: "event-1", message: "message", fields: {} });
    expect(tokenFetchCount).toBe(1);
    expect(eventPostCount).toBe(1);
    expect(bridge.bufferedCount()).toBe(1);

    // An identical token is treated as an unhelpful refresh: no pointless
    // duplicate POST of the head and no refresh storm on later records.
    await bridge.record({ eventCode: "event-2", message: "message", fields: {} });
    expect(tokenFetchCount).toBe(1);
    expect(eventPostCount).toBe(2);
    expect(bridge.bufferedCount()).toBe(2);
  });
});

describe("RuntimeSceneBridge structural rejection (queue head poisoning)", () => {
  function bodiesOf(fetchImpl: ReturnType<typeof vi.fn>): Array<{ eventCode: string }> {
    return fetchImpl.mock.calls.map((call) => JSON.parse(String((call[1] as RequestInit | undefined)?.body)));
  }

  it("drops a 400-poisoned head within one flush and still delivers the queued follower", async () => {
    let releaseFirstPost: (() => void) | null = null;
    let postCount = 0;
    const fetchImpl = vi.fn(() => {
      postCount += 1;
      if (postCount === 1) {
        return new Promise<Response>((resolve) => {
          releaseFirstPost = () => resolve(new Response("{}", { status: 400 }));
        });
      }
      return Promise.resolve(new Response("{}", { status: 202 }));
    });
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "token",
      maxBufferedEvents: 5,
      fetchImpl
    });

    const poisoned = bridge.record({ eventCode: "poison.event", message: "message", fields: {} });
    const follower = bridge.record({ eventCode: "follower.event", message: "message", fields: {} });
    await Promise.resolve();
    expect(postCount).toBe(1);
    releaseFirstPost?.();

    await expect(poisoned).rejects.toBeInstanceOf(RuntimeSceneEventRejectedError);
    await follower;
    expect(bridge.bufferedCount()).toBe(0);
    expect(bodiesOf(fetchImpl).map((body) => body.eventCode)).toEqual([
      "poison.event",
      "follower.event"
    ]);
  });

  it("rejects record() with the dropped bounded event and status when its own event gets a 400", async () => {
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 400 }));
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "token",
      maxBufferedEvents: 5,
      fetchImpl
    });
    const original = {
      eventCode: "not.whitelisted",
      message: "not in the backend event whitelist",
      fields: { reason: "unknown event code" }
    };

    let caught: unknown;
    try {
      await bridge.record(original);
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(RuntimeSceneEventRejectedError);
    const rejected = caught as RuntimeSceneEventRejectedError;
    // The caller's catch block can recover the event and the status itself.
    expect(rejected.status).toBe(400);
    expect(rejected.event).toEqual(original);
    expect(rejected.droppedEvents[0]).toBe(rejected.event);
    expect(bridge.bufferedCount()).toBe(0);
  });

  it("lets later records deliver normally after a poisoned head was dropped", async () => {
    const statuses = [400, 202];
    const fetchImpl = vi.fn(async () => new Response("{}", { status: statuses.shift() ?? 202 }));
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "token",
      maxBufferedEvents: 5,
      fetchImpl
    });

    await expect(
      bridge.record({ eventCode: "poison.event", message: "message", fields: {} })
    ).rejects.toBeInstanceOf(RuntimeSceneEventRejectedError);

    await bridge.record({ eventCode: "healthy.event", message: "message", fields: {} });
    expect(bridge.bufferedCount()).toBe(0);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(bodiesOf(fetchImpl).map((body) => body.eventCode)).toEqual([
      "poison.event",
      "healthy.event"
    ]);
  });

  it.each([404, 422])(
    "drops a structurally rejected head on %s instead of keeping it queued",
    async (status) => {
      const fetchImpl = vi.fn(async () => new Response("{}", { status }));
      const bridge = new RuntimeSceneBridge({
        launcherOrigin: "http://127.0.0.1:8765",
        controlToken: "token",
        maxBufferedEvents: 5,
        fetchImpl
      });

      await expect(
        bridge.record({ eventCode: "rejected.event", message: "message", fields: {} })
      ).rejects.toMatchObject({ name: "RuntimeSceneEventRejectedError", status });
      expect(bridge.bufferedCount()).toBe(0);
    }
  );

  it("keeps a 429 head queued for retry instead of dropping it", async () => {
    let status = 429;
    const fetchImpl = vi.fn(async () => new Response("{}", { status }));
    const bridge = new RuntimeSceneBridge({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "token",
      maxBufferedEvents: 5,
      fetchImpl
    });

    await bridge.record({ eventCode: "throttled.event", message: "message", fields: {} });
    expect(bridge.bufferedCount()).toBe(1);

    status = 202;
    await bridge.flush();
    expect(bridge.bufferedCount()).toBe(0);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});

describe("electronEventPayload", () => {
  it("keeps runtime scene authority fields fixed", () => {
    expect(
      electronEventPayload({
        eventCode: "electron.launcher.supervisor.started",
        message: "Supervisor started.",
        fields: { provider: "electron" }
      })
    ).toEqual({
      component: "electron_launcher",
      phase: "desktop_supervisor",
      eventCode: "electron.launcher.supervisor.started",
      message: "Supervisor started.",
      fields: { provider: "electron" }
    });
  });
});
