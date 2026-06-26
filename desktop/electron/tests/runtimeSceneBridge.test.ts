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
