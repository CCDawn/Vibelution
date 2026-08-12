import { describe, expect, it, vi } from "vitest";
import { executeApprovedDesktopShellShutdown, withDesktopShellExitTimeout } from "../src/shutdown/desktopShellExit.js";
import {
  decideShutdown,
  executeShutdownAuthorizationBoundary,
  fetchLauncherActiveWorkStatus
} from "../src/shutdown/shutdownCoordinator.js";

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

  it("fails closed without stopping services when active-work status cannot be resolved", async () => {
    const sideEffects: string[] = [];
    const decision = await decideShutdown({
      ownershipMode: "started",
      activeWorkStatus: async () => {
        throw new Error("status unreachable");
      }
    });

    expect(decision).toEqual({
      allowed: false,
      reason: "active_work_status_unavailable",
      message: "暂时无法确认是否有进行中的任务，已取消退出。请稍后重试。"
    });
    await expect(
      executeApprovedDesktopShellShutdown({
        decision,
        closeDesktopSession: async () => {
          sideEffects.push("close-session");
        },
        recordEvent: async () => {
          sideEffects.push("record-event");
        },
        stopPythonLauncher: async () => {
          sideEffects.push("stop-python-launcher");
          throw new Error("must not stop");
        },
        approveShutdown: () => {
          sideEffects.push("approve-shutdown");
        },
        stopDesktopActionLoop: () => {
          sideEffects.push("stop-action-loop");
        },
        quitApp: () => {
          sideEffects.push("quit-app");
        }
      })
    ).resolves.toBeNull();
    expect(sideEffects).toEqual([]);
  });

  it("does not enter the approved fail-open path when active-work status times out", async () => {
    vi.useFakeTimers();
    const sideEffects: string[] = [];
    const pending = executeShutdownAuthorizationBoundary({
      authorize: async () =>
        await decideShutdown({
          ownershipMode: "started",
          activeWorkStatus: async () =>
            await withDesktopShellExitTimeout(new Promise(() => undefined), 25, "active-work status")
        }),
      onDenied: () => {
        sideEffects.push("denied");
      },
      runApproved: async () => {
        sideEffects.push("approved");
      },
      failOpenAfterApproval: async () => {
        sideEffects.push("fail-open");
      }
    });

    await vi.advanceTimersByTimeAsync(30);
    await expect(pending).resolves.toMatchObject({
      allowed: false,
      reason: "active_work_status_unavailable"
    });
    expect(sideEffects).toEqual(["denied"]);
    vi.useRealTimers();
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
