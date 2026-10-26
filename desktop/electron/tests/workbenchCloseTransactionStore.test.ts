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

  it("keeps an acknowledged window close pending until the backend is verified stopped", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({ mode: "normal", reason: "close", activeWorkState: "idle" });

    expect(store.authorizeWindowBeforeBackendStopped(submitted.closeId).phase).toBe("background_closing");
    expect(store.windowClosed(submitted.closeId)).toMatchObject({
      phase: "background_closing",
      windowAcknowledged: true
    });
    expect(store.windowClosed(submitted.closeId).phase).toBe("background_closing");
    expect(() => store.submit({ mode: "normal", reason: "close", activeWorkState: "idle" })).toThrow(
      "already in flight"
    );

    expect(store.backendStopped(submitted.closeId).phase).toBe("succeeded");
    expect(store.windowClosed(submitted.closeId).phase).toBe("succeeded");
  });

  it("waits for the window acknowledgement when the background backend stop finishes first", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({ mode: "normal", reason: "close", activeWorkState: "idle" });

    store.authorizeWindowBeforeBackendStopped(submitted.closeId);
    expect(store.backendStopped(submitted.closeId).phase).toBe("window_close_authorized");
    expect(submitted.windowAcknowledged).not.toBe(true);
    expect(store.windowClosed(submitted.closeId)).toMatchObject({
      phase: "succeeded",
      windowAcknowledged: true
    });
  });

  it("only authorizes an early window close while closing the backend", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({ mode: "normal", reason: "close", activeWorkState: "active" });

    expect(() => store.authorizeWindowBeforeBackendStopped(submitted.closeId)).toThrow("not closing the backend");
    expect(submitted.phase).toBe("confirmation_required");
    store.confirm(submitted.closeId, submitted.requestId!);
    store.authorizeWindowBeforeBackendStopped(submitted.closeId);
    expect(() => store.authorizeWindowBeforeBackendStopped(submitted.closeId)).toThrow("not closing the backend");
    store.backendStopped(submitted.closeId);
    expect(() => store.authorizeWindowBeforeBackendStopped(submitted.closeId)).toThrow("not closing the backend");
    expect(submitted.phase).toBe("window_close_authorized");
  });

  it.each([false, true])("preserves a background backend failure with window acknowledged first: %s", (acknowledgeFirst) => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({ mode: "normal", reason: "close", activeWorkState: "idle" });
    store.authorizeWindowBeforeBackendStopped(submitted.closeId);
    if (acknowledgeFirst) store.windowClosed(submitted.closeId);
    store.fail(submitted.closeId, "backend_stop_timeout", "backend did not stop");

    expect(store.windowClosed(submitted.closeId)).toMatchObject({
      phase: "failed",
      failureCode: "backend_stop_timeout",
      message: "backend did not stop"
    });
    expect(() => store.backendStopped(submitted.closeId)).toThrow("already reached failed");
    expect(submitted.phase).toBe("failed");
  });

  it("rejects stale or foreign callbacks without changing a new background close", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const previous = store.submit({ mode: "normal", reason: "close", activeWorkState: "idle" });
    store.backendStopped(previous.closeId);
    store.windowClosed(previous.closeId);
    const current = store.submit({ mode: "normal", reason: "close", activeWorkState: "idle" });
    store.authorizeWindowBeforeBackendStopped(current.closeId);
    const pending = { ...current };

    for (const closeId of [previous.closeId, "foreign-close"]) {
      expect(() => store.authorizeWindowBeforeBackendStopped(closeId)).toThrow("unknown workbench close transaction");
      expect(() => store.windowClosed(closeId)).toThrow("unknown workbench close transaction");
      expect(() => store.backendStopped(closeId)).toThrow("unknown workbench close transaction");
      expect(store.currentTransaction()).toEqual(pending);
    }
    store.windowClosed(current.closeId);
    expect(store.backendStopped(current.closeId).phase).toBe("succeeded");
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
