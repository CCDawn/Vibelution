import { describe, expect, it, vi } from "vitest";
import {
  runWorkbenchWaitingRecovery,
  WORKBENCH_WAITING_RECOVERY_POLL_INTERVAL_MS,
  WORKBENCH_WAITING_RECOVERY_TIMEOUT_MS,
  type WorkbenchWaitingRecoveryInput
} from "../src/windows/workbenchWaitingRecovery.js";

const targetUrl = "http://127.0.0.1:8000/";

/**
 * Every run injects waitForHttp: the default is the real network poller and
 * must never be reached from a unit test.
 */
function input(overrides: Partial<WorkbenchWaitingRecoveryInput> = {}): WorkbenchWaitingRecoveryInput {
  return {
    targetUrl,
    isStillWaiting: () => true,
    recover: vi.fn(async () => undefined),
    showFinalError: vi.fn(async () => undefined),
    waitForHttp: vi.fn(async () => undefined),
    ...overrides
  };
}

describe("workbench waiting recovery runner", () => {
  it("keeps its defaults inside the agreed bands: 60–120s budget, 2–4s poll", () => {
    expect(WORKBENCH_WAITING_RECOVERY_TIMEOUT_MS).toBeGreaterThanOrEqual(60_000);
    expect(WORKBENCH_WAITING_RECOVERY_TIMEOUT_MS).toBeLessThanOrEqual(120_000);
    expect(WORKBENCH_WAITING_RECOVERY_POLL_INTERVAL_MS).toBeGreaterThanOrEqual(2_000);
    expect(WORKBENCH_WAITING_RECOVERY_POLL_INTERVAL_MS).toBeLessThanOrEqual(4_000);
  });

  it("hands the target, budget, interval and signal to the bounded HTTP wait", async () => {
    const waitForHttp = vi.fn(async () => undefined);
    const controller = new AbortController();

    await runWorkbenchWaitingRecovery(input({ waitForHttp, timeoutMs: 1234, pollIntervalMs: 56, signal: controller.signal }));

    expect(waitForHttp).toHaveBeenCalledTimes(1);
    expect(waitForHttp).toHaveBeenCalledWith({ url: targetUrl, timeoutMs: 1234, pollIntervalMs: 56, signal: controller.signal });
  });

  it("uses the exported defaults when no budget or interval is given", async () => {
    const waitForHttp = vi.fn(async () => undefined);

    await runWorkbenchWaitingRecovery(input({ waitForHttp }));

    expect(waitForHttp).toHaveBeenCalledWith(expect.objectContaining({
      timeoutMs: WORKBENCH_WAITING_RECOVERY_TIMEOUT_MS,
      pollIntervalMs: WORKBENCH_WAITING_RECOVERY_POLL_INTERVAL_MS
    }));
  });

  it("recovers exactly once when the backend answers, and never shows the terminal page", async () => {
    const recover = vi.fn(async () => undefined);
    const showFinalError = vi.fn();

    const result = await runWorkbenchWaitingRecovery(input({ recover, showFinalError }));

    expect(result).toEqual({ outcome: "recovered", targetUrl });
    expect(recover).toHaveBeenCalledTimes(1);
    expect(showFinalError).not.toHaveBeenCalled();
  });

  it("times out into the terminal page when the wait exhausts its budget", async () => {
    const recover = vi.fn();
    const showFinalError = vi.fn(async () => undefined);
    const waitForHttp = vi.fn(async () => {
      throw new Error("workbench HTTP was not reachable at http://127.0.0.1:8000/: ECONNREFUSED");
    });

    const result = await runWorkbenchWaitingRecovery(input({ recover, showFinalError, waitForHttp }));

    expect(result.outcome).toBe("timed-out");
    expect(result.error).toContain("ECONNREFUSED");
    expect(showFinalError).toHaveBeenCalledTimes(1);
    expect(recover).not.toHaveBeenCalled();
  });

  it("reports a failed reload and still shows the terminal page", async () => {
    const showFinalError = vi.fn(async () => undefined);
    const recover = vi.fn(async () => {
      throw new Error("Workbench navigation failed for http://127.0.0.1:8000: ERR_CONNECTION_REFUSED");
    });

    const result = await runWorkbenchWaitingRecovery(input({ recover, showFinalError }));

    expect(result.outcome).toBe("failed");
    expect(result.error).toContain("ERR_CONNECTION_REFUSED");
    expect(showFinalError).toHaveBeenCalledTimes(1);
  });

  it("does nothing when the window already moved on before the poll started", async () => {
    const waitForHttp = vi.fn(async () => undefined);
    const recover = vi.fn();
    const showFinalError = vi.fn();

    const result = await runWorkbenchWaitingRecovery(input({ isStillWaiting: () => false, waitForHttp, recover, showFinalError }));

    expect(result).toEqual({ outcome: "superseded", targetUrl });
    expect(waitForHttp).not.toHaveBeenCalled();
    expect(recover).not.toHaveBeenCalled();
    expect(showFinalError).not.toHaveBeenCalled();
  });

  it("steps aside instead of reloading when the window moved on while the poll was pending", async () => {
    let waiting = true;
    const recover = vi.fn();
    const showFinalError = vi.fn();
    const waitForHttp = vi.fn(async () => {
      waiting = false; // a user retry replaced the waiting page meanwhile
    });

    const result = await runWorkbenchWaitingRecovery(input({ isStillWaiting: () => waiting, waitForHttp, recover, showFinalError }));

    expect(result.outcome).toBe("superseded");
    expect(recover).not.toHaveBeenCalled();
    expect(showFinalError).not.toHaveBeenCalled();
  });

  it("never paints the terminal page over a window whose run was aborted", async () => {
    const controller = new AbortController();
    const showFinalError = vi.fn();
    const recover = vi.fn();
    const waitForHttp = vi.fn(async () => {
      controller.abort();
      throw new Error("workbench HTTP readiness aborted");
    });

    const result = await runWorkbenchWaitingRecovery(input({ signal: controller.signal, waitForHttp, showFinalError, recover }));

    expect(result.outcome).toBe("superseded");
    expect(showFinalError).not.toHaveBeenCalled();
    expect(recover).not.toHaveBeenCalled();
  });

  it("treats an abort that lands during the reload as superseded, not failed", async () => {
    const controller = new AbortController();
    const showFinalError = vi.fn();
    const recover = vi.fn(async () => {
      controller.abort(); // the window closed mid-reload
      throw new Error("Workbench open or focus blocked while closing");
    });

    const result = await runWorkbenchWaitingRecovery(input({ signal: controller.signal, recover, showFinalError }));

    expect(result.outcome).toBe("superseded");
    expect(showFinalError).not.toHaveBeenCalled();
  });

  it("swallows a throwing terminal-page swap so the outcome still settles", async () => {
    const waitForHttp = vi.fn(async () => {
      throw new Error("unreachable");
    });
    const showFinalError = vi.fn(() => {
      throw new Error("window gone");
    });

    await expect(runWorkbenchWaitingRecovery(input({ waitForHttp, showFinalError }))).resolves.toMatchObject({
      outcome: "timed-out"
    });
  });
});
