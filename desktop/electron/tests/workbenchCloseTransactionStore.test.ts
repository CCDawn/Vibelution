import { describe, expect, it } from "vitest";

import { MainWorkbenchCloseTransactionStore } from "../src/lifecycle/workbenchCloseTransactionStore.js";

describe("MainWorkbenchCloseTransactionStore", () => {
  it("requires confirmation only for normal closes with active work", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const needsConfirm = store.submit({ mode: "normal", reason: "close", activeWork: true });
    expect(needsConfirm.phase).toBe("confirmation_required");

    const straight = new MainWorkbenchCloseTransactionStore().submit({ mode: "force", reason: "close", activeWork: true });
    expect(straight.phase).toBe("backend_closing");
  });

  it("walks the close lifecycle from confirmation to success", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({ mode: "normal", reason: "close", activeWork: true });
    const closing = store.confirm(submitted.closeId);
    expect(closing.phase).toBe("backend_closing");
    const authorized = store.backendStopped(submitted.closeId);
    expect(authorized.phase).toBe("window_close_authorized");
    const done = store.windowClosed(submitted.closeId);
    expect(done.phase).toBe("succeeded");
  });

  it("rejects double submits while a transaction is in flight", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    store.submit({ mode: "normal", reason: "close", activeWork: false });
    expect(() => store.submit({ mode: "normal", reason: "close", activeWork: false })).toThrow(
      "already in flight"
    );
  });

  it("rejects out-of-order phase transitions", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({ mode: "force", reason: "close", activeWork: false });
    expect(() => store.windowClosed(submitted.closeId)).toThrow("not authorized");
    expect(() => store.confirm(submitted.closeId)).toThrow("not awaiting confirmation");
  });

  it("records failures with a code and message", () => {
    const store = new MainWorkbenchCloseTransactionStore();
    const submitted = store.submit({ mode: "force", reason: "close", activeWork: false });
    const failed = store.fail(submitted.closeId, "backend_stop_timeout", "backend did not stop");
    expect(failed.phase).toBe("failed");
    expect(failed.failureCode).toBe("backend_stop_timeout");
    // A failed transaction allows a fresh submit.
    const next = store.submit({ mode: "force", reason: "close", activeWork: false });
    expect(next.phase).toBe("backend_closing");
  });
});
