import { describe, expect, it } from "vitest";
import { decideShutdown, fetchLauncherActiveWorkStatus } from "../src/shutdown/shutdownCoordinator.js";

describe("decideShutdown", () => {
  it("blocks shutdown while active work exists", async () => {
    await expect(
      decideShutdown({
        ownershipMode: "started",
        activeWorkStatus: async () => ({ active: true, message: "running" })
      })
    ).resolves.toEqual({
      allowed: false,
      reason: "active_work_running",
      message: "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
    });
  });

  it("detaches from attached launcher service without stopping it", async () => {
    await expect(
      decideShutdown({
        ownershipMode: "attached",
        activeWorkStatus: async () => ({ active: false, message: "" })
      })
    ).resolves.toEqual({
      allowed: true,
      reason: "no_active_work",
      stopPythonLauncher: false
    });
  });

  it("stops only the python launcher service it started itself", async () => {
    await expect(
      decideShutdown({
        ownershipMode: "started",
        activeWorkStatus: async () => ({ active: false, message: "" })
      })
    ).resolves.toEqual({
      allowed: true,
      reason: "no_active_work",
      stopPythonLauncher: true
    });
  });
});

describe("fetchLauncherActiveWorkStatus", () => {
  it("reads active-work count from the existing launcher status projection", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = async (url: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(url), init: init ?? {} });
      return new Response(
        JSON.stringify({
          lifecycleProof: {
            activeWorkRuns: {
              count: 2
            }
          }
        }),
        { status: 200, headers: { "content-type": "application/json" } }
      );
    };

    await expect(
      fetchLauncherActiveWorkStatus({
        launcherOrigin: "http://127.0.0.1:8765/launcher",
        controlToken: "token",
        fetchImpl
      })
    ).resolves.toEqual({
      active: true,
      message: "2 active work item(s) block lifecycle commands."
    });
    expect(requests[0].url).toBe("http://127.0.0.1:8765/api/launcher/status");
    expect(requests[0].init.headers).toMatchObject({
      "X-Vibelution-Control-Token": "token"
    });
  });
});
