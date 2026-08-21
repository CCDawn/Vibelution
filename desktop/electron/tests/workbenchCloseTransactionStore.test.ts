import { describe, expect, it } from "vitest";

import { MainWorkbenchCloseTransactionStore } from "../src/lifecycle/workbenchCloseTransactionStore.js";

describe("MainWorkbenchCloseTransactionStore", () => {
  it("requires confirmation for normal closes with active or unknown work state", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const needsConfirm = store.submit({ mode: "normal", reason: "close", activeWorkState: "active" });
    expect(needsConfirm.phase).toBe("confirmation_required");
    expect(needsConfirm.requestId).toBeTruthy();

    const unknown = new MainWorkbenchCloseTransactionStore().submit({
      mode: "normal",
      reason: "close",
      activeWorkState: "unknown"
    });
    expect(unknown.phase).toBe("confirmation_required");
  });

  it("walks the close lifecycle from confirmation to success", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({ mode: "normal", reason: "close", activeWorkState: "active" });
    const closing = store.confirm(submitted.closeId, submitted.requestId!);
    expect(closing.phase).toBe("backend_closing");
    expect(closing.mode).toBe("force");
    const authorized = store.backendStopped(submitted.closeId);
    expect(authorized.phase).toBe("window_close_authorized");
    const done = store.windowClosed(submitted.closeId);
    expect(done.phase).toBe("succeeded");
  });

  it("rejects double submits while a transaction is in flight", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    store.submit({ mode: "normal", reason: "close", activeWorkState: "idle" });
    expect(() => store.submit({ mode: "normal", reason: "close", activeWorkState: "idle" })).toThrow(
      "already in flight"
    );
  });

  it("rejects out-of-order phase transitions", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({
      mode: "force",
      reason: "close",
      activeWorkState: "idle",
      requestId: "force-request"
    });
    expect(() => store.windowClosed(submitted.closeId)).toThrow("not authorized");
    expect(() => store.confirm(submitted.closeId, "force-request")).toThrow("not awaiting confirmation");
  });

  it("rejects force close without an explicit request id and mismatched confirmation", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    expect(() => store.submit({ mode: "force", reason: "close", activeWorkState: "active" })).toThrow(
      "requestId"
    );
    const submitted = store.submit({ mode: "normal", reason: "close", activeWorkState: "active" });
    expect(() => store.confirm(submitted.closeId, "wrong-request")).toThrow("request id");
  });

  it("records failures with a code and message", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({
      mode: "force",
      reason: "close",
      activeWorkState: "idle",
      requestId: "force-request"
    });
    const failed = store.fail(submitted.closeId, "backend_stop_timeout", "backend did not stop");
    expect(failed.phase).toBe("failed");
    expect(failed.failureCode).toBe("backend_stop_timeout");
    // A failed transaction allows a fresh submit.
    const next = store.submit({
      mode: "force",
      reason: "close",
      activeWorkState: "idle",
      requestId: "force-request-next"
    });
    expect(next.phase).toBe("backend_closing");
  });

  it("settles a fail-open window acknowledgement without hiding the failed backend outcome", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({
      mode: "force",
      reason: "close",
      activeWorkState: "idle",
      requestId: "force-request"
    });
    store.fail(submitted.closeId, "backend_stop_timeout", "backend did not stop");

    expect(() => store.windowClosed(submitted.closeId)).not.toThrow();
    expect(store.windowClosed(submitted.closeId)).toMatchObject({
      closeId: submitted.closeId,
      phase: "failed",
      failureCode: "backend_stop_timeout"
    });
  });

  it("closes the transaction when the user chooses to keep running", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({ mode: "normal", reason: "close", activeWorkState: "active" });
    const cancelled = store.fail(
      submitted.closeId,
      "user_cancelled",
      "Workbench close was cancelled while active work was present."
    );
    expect(cancelled.phase).toBe("failed");
    expect(cancelled.failureCode).toBe("user_cancelled");
    expect(() => store.submit({ mode: "normal", reason: "close", activeWorkState: "idle" })).not.toThrow();
  });
});
