import { describe, expect, it } from "vitest";
import {
  desktopWindowOperationForAction,
  fetchLauncherControlToken,
  launcherDesktopActionEndpoints,
  runDesktopActionOnce
} from "../src/protocol/desktopActionClient.js";

describe("desktopWindowOperationForAction", () => {
  it("maps approved desktop actions to window operations", () => {
    expect(desktopWindowOperationForAction("open_workbench")).toBe("open_or_focus_workbench");
    expect(desktopWindowOperationForAction("focus_workbench")).toBe("focus_workbench");
    expect(desktopWindowOperationForAction("close_workbench")).toBe("close_workbench");
  });

  it("does not map runtime-effect actions into Electron process commands", () => {
    expect(desktopWindowOperationForAction("restart_after_apply")).toBe("none");
    expect(desktopWindowOperationForAction("recover_after_crash")).toBe("none");
  });

  it("uses claim ack fail endpoints instead of next polling", () => {
    expect(launcherDesktopActionEndpoints("http://127.0.0.1:8765")).toEqual({
      claim: "http://127.0.0.1:8765/api/launcher/desktop-actions/claim",
      ack: "http://127.0.0.1:8765/api/launcher/desktop-actions/{actionId}/ack",
      fail: "http://127.0.0.1:8765/api/launcher/desktop-actions/{actionId}/fail"
    });
  });
});

describe("fetchLauncherControlToken", () => {
  it("reads the existing Launcher control-token endpoint without exposing it in summaries", async () => {
    const requests: string[] = [];
    const fetchImpl = async (url: string | URL | Request) => {
      requests.push(String(url));
      return jsonResponse({ header: "X-Vibelution-Control-Token", controlToken: "token-value" });
    };

    await expect(
      fetchLauncherControlToken({
        launcherOrigin: "http://127.0.0.1:8765/launcher",
        fetchImpl
      })
    ).resolves.toBe("token-value");
    expect(requests).toEqual(["http://127.0.0.1:8765/api/control-token"]);
  });
});

describe("runDesktopActionOnce", () => {
  it("claims one desktop action, executes the matching window operation, and acks the lease", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const operations: string[] = [];
    const fetchImpl = async (url: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(url), init: init ?? {} });
      if (String(url).endsWith("/claim")) {
        return jsonResponse({
          actionId: "action-1",
          intentId: "intent-1",
          action: "open_workbench",
          status: "claimed",
          payload: {},
          claimedBy: "desktop-session-1",
          leaseExpiresAt: "2026-06-26T10:00:00Z",
          claimAttempt: 1
        });
      }
      return jsonResponse({ status: "acked" }, 202);
    };

    const result = await runDesktopActionOnce({
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      desktopSessionId: "desktop-session-1",
      leaseSeconds: 30,
      fetchImpl,
      operations: {
        openOrFocusWorkbench: async () => {
          operations.push("open_or_focus_workbench");
          return { open: true };
        },
        focusWorkbench: async () => {
          operations.push("focus_workbench");
          return { focused: true };
        },
        closeWorkbench: async () => {
          operations.push("close_workbench");
          return { open: false };
        }
      }
    });

    expect(result).toEqual({
      claimed: true,
      actionId: "action-1",
      action: "open_workbench",
      status: "acked"
    });
    expect(operations).toEqual(["open_or_focus_workbench"]);
    expect(requests.map((request) => request.url)).toEqual([
      "http://127.0.0.1:8765/api/launcher/desktop-actions/claim",
      "http://127.0.0.1:8765/api/launcher/desktop-actions/action-1/ack"
    ]);
    expect(JSON.parse(String(requests[0].init.body))).toEqual({
      desktopSessionId: "desktop-session-1",
      leaseSeconds: 30
    });
    expect(JSON.parse(String(requests[1].init.body))).toEqual({
      desktopSessionId: "desktop-session-1",
      result: {
        operation: "open_or_focus_workbench",
        windowState: { open: true }
      }
    });
  });

  it("fails runtime-effect actions without executing a window operation", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = async (url: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(url), init: init ?? {} });
      if (String(url).endsWith("/claim")) {
        return jsonResponse({
          actionId: "action-runtime",
          intentId: "intent-runtime",
          action: "restart_after_apply",
          status: "claimed",
          payload: {},
          claimedBy: "desktop-session-1",
          leaseExpiresAt: "2026-06-26T10:00:00Z",
          claimAttempt: 1
        });
      }
      return jsonResponse({ status: "failed" }, 202);
    };

    const result = await runDesktopActionOnce({
      launcherOrigin: "http://127.0.0.1:8765",
      controlToken: "token",
      desktopSessionId: "desktop-session-1",
      leaseSeconds: 30,
      fetchImpl,
      operations: {
        openOrFocusWorkbench: async () => {
          throw new Error("must not execute");
        },
        focusWorkbench: async () => {
          throw new Error("must not execute");
        },
        closeWorkbench: async () => {
          throw new Error("must not execute");
        }
      }
    });

    expect(result).toEqual({
      claimed: true,
      actionId: "action-runtime",
      action: "restart_after_apply",
      status: "failed"
    });
    expect(requests.map((request) => request.url)).toEqual([
      "http://127.0.0.1:8765/api/launcher/desktop-actions/claim",
      "http://127.0.0.1:8765/api/launcher/desktop-actions/action-runtime/fail"
    ]);
    expect(JSON.parse(String(requests[1].init.body))).toEqual({
      desktopSessionId: "desktop-session-1",
      result: {
        reason: "unsupported_desktop_action",
        action: "restart_after_apply"
      }
    });
  });
});

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" }
  });
}
