import { describe, expect, it } from "vitest";
import { reportDesktopWindowState } from "../src/windows/desktopSessionClient.js";

describe("desktop session client", () => {
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
