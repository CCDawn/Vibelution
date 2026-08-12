import { describe, expect, it } from "vitest";
import {
  fetchLauncherStatusSummary,
  formatLauncherStatusSummary,
  postLauncherControl
} from "../src/protocol/launcherControlClient.js";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" }
  });
}

describe("postLauncherControl", () => {
  it("posts launcher lifecycle paths with the control token header", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = async (url: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(url), init: init ?? {} });
      return jsonResponse({ accepted: true }, 202);
    };

    await postLauncherControl({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      path: "/api/launcher/start",
      fetchImpl
    });

    expect(requests).toHaveLength(1);
    expect(requests[0].url).toBe("http://127.0.0.1:8765/api/launcher/start");
    expect(requests[0].init.method).toBe("POST");
    expect(requests[0].init.headers).toMatchObject({
      "X-Vibelution-Control-Token": "token"
    });
  });

  it("includes the launcher trigger header for stop-style tray actions", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = async (url: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(url), init: init ?? {} });
      return jsonResponse({ accepted: true }, 202);
    };

    await postLauncherControl({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      path: "/api/launcher/force-stop",
      trigger: "electron_tray_stop_all",
      fetchImpl
    });

    expect(requests[0].url).toBe("http://127.0.0.1:8765/api/launcher/force-stop");
    expect(requests[0].init.headers).toMatchObject({
      "X-Vibelution-Control-Token": "token",
      "X-Vibelution-Launcher-Trigger": "electron_tray_stop_all"
    });
  });

  it("surfaces launcher rejection details", async () => {
    await expect(
      postLauncherControl({
        launcherOrigin: "http://127.0.0.1:8765/launcher",
        controlToken: "token",
        path: "/api/launcher/stop",
        fetchImpl: async () =>
          jsonResponse(
            {
              detail: {
                code: "active_work_stop_blocked",
                message: "有进行中的任务，无法停止。"
              }
            },
            409
          )
      })
    ).rejects.toThrow("有进行中的任务，无法停止。");
  });
});

describe("fetchLauncherStatusSummary", () => {
  it("reads overall/observed/consistency fields for tray status", async () => {
    const requests: string[] = [];
    const summary = await fetchLauncherStatusSummary({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      fetchImpl: async (url) => {
        requests.push(String(url));
        return jsonResponse({
          overallState: "ready",
          observedState: "open",
          workbench: { lifecycleConsistency: "consistent" }
        });
      }
    });

    expect(requests).toEqual(["http://127.0.0.1:8765/api/launcher/status"]);
    expect(summary).toEqual({
      overallState: "ready",
      observedState: "open",
      lifecycleConsistency: "consistent"
    });
    expect(formatLauncherStatusSummary(summary)).toBe("状态：ready / open / consistent");
  });
});
