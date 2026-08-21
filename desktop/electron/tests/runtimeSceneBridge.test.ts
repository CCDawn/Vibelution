import { describe, expect, it, vi } from "vitest";
import { RuntimeSceneBridge, electronEventPayload } from "../src/lifecycle/runtimeSceneBridge.js";

describe("RuntimeSceneBridge", () => {
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
