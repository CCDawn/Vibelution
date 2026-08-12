import { describe, expect, it } from "vitest";
import {
  classifyTrayBranchInstances,
  fetchLauncherBranchInstances,
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

describe("tray branch instance classification", () => {
  it("marks checked-out idle worktrees startable and live ones stoppable", () => {
    const items = classifyTrayBranchInstances({
      items: [
        { id: "main", shortName: "主", branch: "main", kind: "main", checkedOut: true, alive: true },
        { id: "worktree:task", shortName: "task", branch: "codex/task", kind: "worktree", checkedOut: true, alive: false },
        { id: "branch:feature", branch: "feature", kind: "local_branch", checkedOut: false, alive: false },
        { id: "retired:old", kind: "retired", checkedOut: false, alive: false }
      ]
    });
    expect(items).toEqual([
      { id: "main", label: "主", startable: false, stoppable: true },
      { id: "worktree:task", label: "task", startable: true, stoppable: false },
      { id: "branch:feature", label: "feature", startable: false, stoppable: false },
      { id: "retired:old", label: "retired:old", startable: false, stoppable: false }
    ]);
  });

  it("fetches and classifies launcher branch instances", async () => {
    const items = await fetchLauncherBranchInstances({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      fetchImpl: async (url) => {
        expect(String(url)).toBe("http://127.0.0.1:8765/api/launcher/branch-instances");
        return jsonResponse({
          items: [{ id: "main", shortName: "主", kind: "main", checkedOut: true, alive: true }]
        });
      }
    });
    expect(items).toEqual([{ id: "main", label: "主", startable: false, stoppable: true }]);
  });

  it("posts selected instance start with a JSON body", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    await postLauncherControl({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      path: "/api/launcher/branch-instances/start",
      body: { instanceId: "worktree:task" },
      fetchImpl: async (url, init) => {
        requests.push({ url: String(url), init: init ?? {} });
        return jsonResponse({ accepted: true }, 202);
      }
    });
    expect(requests[0].url).toBe("http://127.0.0.1:8765/api/launcher/branch-instances/start");
    expect(requests[0].init.body).toBe(JSON.stringify({ instanceId: "worktree:task" }));
  });
});
