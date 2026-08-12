import { describe, expect, it } from "vitest";
import {
  acknowledgeWorkbenchCloseWindowClosed,
  fetchWorkbenchCloseTransaction,
  isRecoverableWorkbenchCloseTransactionControlRejection,
  retryRejectedWorkbenchCloseSubmitOnce,
  submitWorkbenchCloseTransaction,
  WorkbenchCloseTransactionRequestError
} from "../src/protocol/workbenchCloseTransactionClient.js";

describe("workbench close transaction client", () => {
  it("submits, polls, and acknowledges the Electron window through the Launcher transaction API", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const fetchImpl = async (url: string | URL | Request, init?: RequestInit) => {
      requests.push({ url: String(url), init: init ?? {} });
      const payload =
        requests.length === 1
          ? {
              closeId: "workbench-close-1",
              phase: "backend_closing",
              nextPollAfterMs: 180,
              retryable: true
            }
          : requests.length === 2
            ? {
                closeId: "workbench-close-1",
                phase: "window_close_authorized",
                nextPollAfterMs: 250,
                retryable: true
              }
            : { closeId: "workbench-close-1", phase: "succeeded", retryable: false };
      return new Response(JSON.stringify(payload), {
        status: requests.length === 1 ? 202 : 200,
        headers: { "content-type": "application/json" }
      });
    };
    const shared = {
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      desktopSessionId: "desktop-session-1",
      fetchImpl
    };

    await submitWorkbenchCloseTransaction({
      ...shared,
      idempotencyKey: "desktop-session-1:close-1",
      mode: "normal",
      reason: "workbench_window_close"
    });
    await fetchWorkbenchCloseTransaction({ ...shared, closeId: "workbench-close-1" });
    await acknowledgeWorkbenchCloseWindowClosed({
      ...shared,
      closeId: "workbench-close-1",
      desktopSessionRevision: 9
    });

    expect(requests.map((request) => [request.init.method, request.url])).toEqual([
      ["POST", "http://127.0.0.1:8765/api/launcher/workbench-close-transactions"],
      ["GET", "http://127.0.0.1:8765/api/launcher/workbench-close-transactions/workbench-close-1"],
      ["POST", "http://127.0.0.1:8765/api/launcher/workbench-close-transactions/workbench-close-1/window-closed"]
    ]);
    expect(requests[0].init.headers).toMatchObject({
      "content-type": "application/json",
      "X-Vibelution-Control-Token": "token"
    });
    expect(JSON.parse(String(requests[0].init.body))).toEqual({
      desktopSessionId: "desktop-session-1",
      idempotencyKey: "desktop-session-1:close-1",
      mode: "normal",
      reason: "workbench_window_close",
      confirmationCloseId: ""
    });
    expect(JSON.parse(String(requests[2].init.body))).toEqual({
      desktopSessionId: "desktop-session-1",
      desktopSessionRevision: 9
    });
  });

  it("identifies an unauthorized submit so Electron can recover control before any close is accepted", async () => {
    const input = {
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "stale-token",
      desktopSessionId: "desktop-session-1",
      idempotencyKey: "desktop-session-1:close-1",
      mode: "normal" as const,
      reason: "workbench_window_close",
      fetchImpl: async () => new Response("", { status: 403 })
    };

    await expect(submitWorkbenchCloseTransaction(input)).rejects.toMatchObject<Partial<WorkbenchCloseTransactionRequestError>>({
      name: "WorkbenchCloseTransactionRequestError",
      operation: "submit",
      status: 403
    });
  });

  it("refreshes control once and retries only an unaccepted unauthorized submit", async () => {
    let submits = 0;
    let recoveries = 0;

    await expect(
      retryRejectedWorkbenchCloseSubmitOnce(
        async () => {
          submits += 1;
          if (submits === 1) {
            throw new WorkbenchCloseTransactionRequestError("submit", 403);
          }
          return "accepted";
        },
        async () => {
          recoveries += 1;
        }
      )
    ).resolves.toBe("accepted");

    expect({ submits, recoveries }).toEqual({ submits: 2, recoveries: 1 });
  });

  it("never retries a poll failure or a second rejected submit", async () => {
    let recoveries = 0;

    await expect(
      retryRejectedWorkbenchCloseSubmitOnce(
        async () => {
          throw new WorkbenchCloseTransactionRequestError("fetch", 403);
        },
        async () => {
          recoveries += 1;
        }
      )
    ).rejects.toMatchObject({ operation: "fetch", status: 403 });
    expect(recoveries).toBe(0);

    let submits = 0;
    await expect(
      retryRejectedWorkbenchCloseSubmitOnce(
        async () => {
          submits += 1;
          throw new WorkbenchCloseTransactionRequestError("submit", 401);
        },
        async () => {
          recoveries += 1;
        }
      )
    ).rejects.toMatchObject({ operation: "submit", status: 401 });
    expect({ submits, recoveries }).toEqual({ submits: 2, recoveries: 1 });
  });

  it("identifies only rejected requests for the requested transaction operation", () => {
    expect(
      isRecoverableWorkbenchCloseTransactionControlRejection(
        new WorkbenchCloseTransactionRequestError("fetch", 403),
        "fetch"
      )
    ).toBe(true);
    expect(
      isRecoverableWorkbenchCloseTransactionControlRejection(
        new WorkbenchCloseTransactionRequestError("submit", 403),
        "fetch"
      )
    ).toBe(false);
    expect(
      isRecoverableWorkbenchCloseTransactionControlRejection(
        new WorkbenchCloseTransactionRequestError("fetch", 500),
        "fetch"
      )
    ).toBe(false);
  });
});
