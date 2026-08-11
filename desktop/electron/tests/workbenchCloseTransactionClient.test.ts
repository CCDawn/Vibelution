import { describe, expect, it } from "vitest";
import {
  acknowledgeWorkbenchCloseWindowClosed,
  fetchWorkbenchCloseTransaction,
  submitWorkbenchCloseTransaction
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
});
