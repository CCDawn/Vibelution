import { describe, expect, it } from "vitest";
import {
  closeDesktopSession,
  heartbeatDesktopSession,
  registerDesktopSession,
  reportDesktopWindowState
} from "../src/windows/desktopSessionClient.js";

describe("desktop session client", () => {
  it("registers, heartbeats, and closes a desktop session through the Launcher API", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = async (url: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(url), init: init ?? {} });
      return new Response(JSON.stringify({ desktopSessionId: "desktop-session-1", revision: requests.length }), {
        status: requests.length === 1 ? 201 : 200,
        headers: { "content-type": "application/json" }
      });
    };

    await registerDesktopSession({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      desktopSessionId: "desktop-session-1",
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      capabilities: ["desktop_actions.claim"],
      fetchImpl
    });
    await heartbeatDesktopSession({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      desktopSessionId: "desktop-session-1",
      fetchImpl
    });
    await closeDesktopSession({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      desktopSessionId: "desktop-session-1",
      fetchImpl
    });

    expect(requests.map((request) => [request.init.method, request.url])).toEqual([
      ["POST", "http://127.0.0.1:8765/api/launcher/desktop-sessions"],
      ["POST", "http://127.0.0.1:8765/api/launcher/desktop-sessions/desktop-session-1/heartbeat"],
      ["DELETE", "http://127.0.0.1:8765/api/launcher/desktop-sessions/desktop-session-1"]
    ]);
    expect(JSON.parse(String(requests[0].init.body))).toEqual({
      desktopSessionId: "desktop-session-1",
      provider: "electron",
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
      capabilities: ["desktop_actions.claim"]
    });
  });

  it("reports a bounded electron window state update", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = async (url: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(url), init: init ?? {} });
      return new Response(JSON.stringify({ desktopSessionId: "desktop-session-1", revision: 8 }), {
        status: 200,
        headers: { "content-type": "application/json" }
      });
    };

    const result = await reportDesktopWindowState({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      desktopSessionId: "desktop-session-1",
      role: "workbench",
      revision: 7,
      state: {
        role: "workbench",
        provider: "electron",
        open: true,
        focused: true,
        windowId: 42,
        rendererProcessId: 4242,
        url: "http://127.0.0.1:8000"
      },
      fetchImpl
    });

    expect(result).toEqual({ desktopSessionId: "desktop-session-1", revision: 8 });
    expect(requests).toHaveLength(1);
    expect(requests[0].url).toBe(
      "http://127.0.0.1:8765/api/launcher/desktop-sessions/desktop-session-1/windows/workbench"
    );
    expect(requests[0].init.method).toBe("PUT");
    expect(requests[0].init.headers).toMatchObject({
      "content-type": "application/json",
      "X-Vibelution-Control-Token": "token"
    });
    expect(JSON.parse(String(requests[0].init.body))).toEqual({
      revision: 7,
      provider: "electron",
      open: true,
      focused: true,
      windowId: 42,
      rendererProcessId: 4242,
      url: "http://127.0.0.1:8000"
    });
  });
});
