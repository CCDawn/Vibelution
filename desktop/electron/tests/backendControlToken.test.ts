import { describe, expect, it, vi } from "vitest";
import {
  BackendControlTokenOwner,
  type BackendControlProcessIdentity
} from "../src/protocol/backendControlToken.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function fixture(fetchControlToken = vi.fn(async () => "token-one")) {
  let identity: BackendControlProcessIdentity | null = { pid: 10, createTime: 100 };
  const owner = new BackendControlTokenOwner({
    workspaceRoot: "C:/workspace/one",
    launcherOrigin: "http://localhost:8765/launcher",
    readBackendIdentity: () => identity,
    fetchControlToken
  });
  return { owner, fetchControlToken, setIdentity: (value: typeof identity) => { identity = value; } };
}

describe("BackendControlTokenOwner", () => {
  it("shares a single fetch and reuses a trimmed token for the same process", async () => {
    const request = deferred<string>();
    const { owner, fetchControlToken } = fixture(vi.fn(() => request.promise));
    const first = owner.resolve();
    const second = owner.resolve();
    await Promise.resolve();
    expect(fetchControlToken).toHaveBeenCalledTimes(1);
    request.resolve("  token-one\n");
    await expect(Promise.all([first, second])).resolves.toEqual(["token-one", "token-one"]);
    await expect(owner.resolve()).resolves.toBe("token-one");
    expect(fetchControlToken).toHaveBeenCalledTimes(1);
  });

  it.each([
    { pid: 11, createTime: 100 },
    { pid: 10, createTime: 101 }
  ])("refreshes when either process identity field changes: %j", async (identity) => {
    const { owner, fetchControlToken, setIdentity } = fixture();
    await expect(owner.resolve()).resolves.toBe("token-one");
    setIdentity(identity);
    fetchControlToken.mockResolvedValue("token-two");
    await expect(owner.resolve()).resolves.toBe("token-two");
    expect(fetchControlToken).toHaveBeenCalledTimes(2);
  });

  it("does not return a late old-process token or clear the new pending request", async () => {
    const oldRequest = deferred<string>();
    const newRequest = deferred<string>();
    const fetchControlToken = vi.fn().mockReturnValueOnce(oldRequest.promise).mockReturnValueOnce(newRequest.promise);
    const { owner, setIdentity } = fixture(fetchControlToken);
    const oldWaiter = owner.resolve();
    await Promise.resolve();
    setIdentity({ pid: 20, createTime: 200 });
    const newWaiter = owner.resolve();
    await Promise.resolve();
    oldRequest.resolve("old-secret-token");
    await Promise.resolve();
    await Promise.resolve();
    const laterWaiter = owner.resolve();
    newRequest.resolve("new-token");
    await expect(Promise.all([oldWaiter, newWaiter, laterWaiter])).resolves.toEqual([
      "new-token", "new-token", "new-token"
    ]);
    await expect(owner.resolve()).resolves.toBe("new-token");
    expect(fetchControlToken).toHaveBeenCalledTimes(2);
  });

  it("does not overwrite a new cache when an old request finishes last", async () => {
    const oldRequest = deferred<string>();
    const fetchControlToken = vi.fn().mockReturnValueOnce(oldRequest.promise).mockResolvedValueOnce("new-token");
    const { owner, setIdentity } = fixture(fetchControlToken);
    const oldWaiter = owner.resolve();
    await Promise.resolve();
    setIdentity({ pid: 20, createTime: 200 });
    await expect(owner.resolve()).resolves.toBe("new-token");
    oldRequest.resolve("old-secret-token");
    await expect(oldWaiter).resolves.toBe("new-token");
    await expect(owner.resolve()).resolves.toBe("new-token");
    expect(fetchControlToken).toHaveBeenCalledTimes(2);
  });

  it("invalidates the old cache immediately and joins force and normal refresh callers", async () => {
    const request = deferred<string>();
    const { owner, fetchControlToken } = fixture();
    await owner.resolve();
    fetchControlToken.mockReturnValue(request.promise);
    const forced = owner.resolve({ forceRefresh: true });
    const normal = owner.resolve();
    const alsoForced = owner.resolve({ forceRefresh: true });
    request.resolve("refreshed-token");
    await expect(Promise.all([forced, normal, alsoForced])).resolves.toEqual([
      "refreshed-token", "refreshed-token", "refreshed-token"
    ]);
    expect(fetchControlToken).toHaveBeenCalledTimes(2);
  });

  it.each([
    null,
    { pid: 0, createTime: 100 },
    { pid: 1.5, createTime: 100 },
    { pid: 10, createTime: 0 },
    { pid: 10, createTime: Number.NaN },
    { pid: 10, createTime: Number.POSITIVE_INFINITY }
  ])("shares unknown identity only while the fetch is pending: %j", async (identity) => {
    const request = deferred<string>();
    const { owner, setIdentity, fetchControlToken } = fixture(vi.fn(() => request.promise));
    setIdentity(identity);
    const first = owner.resolve();
    const second = owner.resolve();
    request.resolve("unknown-token");
    await expect(Promise.all([first, second])).resolves.toEqual(["unknown-token", "unknown-token"]);
    await expect(owner.resolve()).resolves.toBe("unknown-token");
    expect(fetchControlToken).toHaveBeenCalledTimes(2);
  });

  it("fences a fetch when a previously unknown identity becomes known", async () => {
    const request = deferred<string>();
    const fetchControlToken = vi.fn().mockReturnValueOnce(request.promise).mockResolvedValueOnce("known-token");
    const { owner, setIdentity } = fixture(fetchControlToken);
    setIdentity(null);
    const waiter = owner.resolve();
    await Promise.resolve();
    setIdentity({ pid: 20, createTime: 200 });
    request.resolve("untrusted-old-token");
    await expect(waiter).resolves.toBe("known-token");
    expect(fetchControlToken).toHaveBeenCalledTimes(2);
  });

  it("discards a cached known-process token while identity is unavailable", async () => {
    const { owner, fetchControlToken, setIdentity } = fixture();
    await expect(owner.resolve()).resolves.toBe("token-one");
    setIdentity(null);
    fetchControlToken.mockResolvedValue("unknown-token");
    await expect(owner.resolve()).resolves.toBe("unknown-token");
    await expect(owner.resolve()).resolves.toBe("unknown-token");
    expect(fetchControlToken).toHaveBeenCalledTimes(3);
  });

  it("retries against the new process when an old-process fetch fails late", async () => {
    const request = deferred<string>();
    const fetchControlToken = vi.fn().mockReturnValueOnce(request.promise).mockResolvedValueOnce("new-token");
    const { owner, setIdentity } = fixture(fetchControlToken);
    const waiter = owner.resolve();
    await Promise.resolve();
    setIdentity({ pid: 20, createTime: 200 });
    await expect(owner.resolve()).resolves.toBe("new-token");
    request.reject(new Error("old-secret-token"));
    await expect(waiter).resolves.toBe("new-token");
    expect(fetchControlToken).toHaveBeenCalledTimes(2);
  });

  it("retries once and reports a safe context error if the process keeps changing", async () => {
    const { owner, setIdentity, fetchControlToken } = fixture();
    fetchControlToken.mockImplementationOnce(async () => {
      setIdentity({ pid: 20, createTime: 200 });
      return "old-secret-token";
    }).mockImplementationOnce(async () => {
      setIdentity({ pid: 30, createTime: 300 });
      return "another-secret-token";
    });
    await expect(owner.resolve()).rejects.toThrow("control context changed");
    expect(fetchControlToken).toHaveBeenCalledTimes(2);
  });

  it("recovers after a failed fetch without exposing dependency errors", async () => {
    const fetchControlToken = vi.fn().mockRejectedValueOnce(new Error("secret-token-in-error"))
      .mockResolvedValueOnce("recovered-token");
    const { owner } = fixture(fetchControlToken);
    await expect(owner.resolve()).rejects.toThrow(/^backend control token fetch failed$/);
    await expect(owner.resolve()).resolves.toBe("recovered-token");
    expect(fetchControlToken).toHaveBeenCalledTimes(2);
  });

  it("does not restore a stale cached token after a forced refresh fails", async () => {
    const { owner, fetchControlToken } = fixture();
    await owner.resolve();
    fetchControlToken.mockRejectedValueOnce(new Error("private-failure")).mockResolvedValueOnce("recovered-token");
    await expect(owner.resolve({ forceRefresh: true })).rejects.toThrow("backend control token fetch failed");
    await expect(owner.resolve()).resolves.toBe("recovered-token");
    expect(fetchControlToken).toHaveBeenCalledTimes(3);
  });

  it("rejects empty results and can fetch again", async () => {
    const fetchControlToken = vi.fn().mockResolvedValueOnce(" \n ").mockResolvedValueOnce("valid-token");
    const { owner } = fixture(fetchControlToken);
    await expect(owner.resolve()).rejects.toThrow("backend control token is empty");
    await expect(owner.resolve()).resolves.toBe("valid-token");
  });

  it("cancels one waiter immediately while another caller receives the shared token", async () => {
    const request = deferred<string>();
    const { owner, fetchControlToken } = fixture(vi.fn(() => request.promise));
    const controller = new AbortController();
    const removeListener = vi.spyOn(controller.signal, "removeEventListener");
    const cancelled = owner.resolve({ signal: controller.signal });
    const other = owner.resolve();
    controller.abort(new Error("private-abort-reason"));
    await expect(cancelled).rejects.toMatchObject({ name: "AbortError", message: "backend control token wait aborted" });
    expect(removeListener).toHaveBeenCalledWith("abort", expect.any(Function));
    request.resolve("shared-token");
    await expect(other).resolves.toBe("shared-token");
    await expect(owner.resolve()).resolves.toBe("shared-token");
    expect(fetchControlToken).toHaveBeenCalledTimes(1);
  });

  it("removes an abort listener after successful resolution", async () => {
    const { owner } = fixture();
    const controller = new AbortController();
    const removeListener = vi.spyOn(controller.signal, "removeEventListener");
    await expect(owner.resolve({ signal: controller.signal })).resolves.toBe("token-one");
    expect(removeListener).toHaveBeenCalledWith("abort", expect.any(Function));
  });

  it("does not start a fetch for a caller that was already aborted", async () => {
    const { owner, fetchControlToken } = fixture();
    const controller = new AbortController();
    controller.abort();
    await expect(owner.resolve({ signal: controller.signal })).rejects.toMatchObject({ name: "AbortError" });
    expect(fetchControlToken).not.toHaveBeenCalled();
  });

  it("captures process identity values instead of retaining a mutable dependency object", async () => {
    const identity = { pid: 10, createTime: 100 };
    const request = deferred<string>();
    const fetchControlToken = vi.fn().mockReturnValueOnce(request.promise).mockResolvedValueOnce("new-token");
    const { owner, setIdentity } = fixture(fetchControlToken);
    setIdentity(identity);
    const waiter = owner.resolve();
    await Promise.resolve();
    identity.createTime = 200;
    request.resolve("old-token");
    await expect(waiter).resolves.toBe("new-token");
  });

  it("keeps each owner's cache and pending request scoped to its workspace and normalized origin", async () => {
    const identity = () => ({ pid: 10, createTime: 100 });
    const owners = [
      ["C:/workspace/one", "http://localhost:8765/a", "one"],
      ["C:/workspace/two", "http://localhost:8765/b", "two"],
      ["C:/workspace/one", "http://localhost:9876/a", "three"],
      ["C:/workspace/one", "http://localhost:8765/a", "four"]
    ].map(([workspaceRoot, launcherOrigin, token]) => new BackendControlTokenOwner({
      workspaceRoot, launcherOrigin, readBackendIdentity: identity, fetchControlToken: async () => token
    }));
    await expect(Promise.all(owners.map((owner) => owner.resolve()))).resolves.toEqual(["one", "two", "three", "four"]);
    expect(owners[0].isForScope("C:/workspace/one", "http://LOCALHOST:8765/other?x=1")).toBe(true);
    expect(owners[0].isForScope("C:/workspace/two", "http://localhost:8765")).toBe(false);
    expect(owners[0].isForScope("C:/workspace/one", "http://localhost:9876")).toBe(false);
    expect(owners[0].isForScope("C:/workspace/one", "invalid-origin")).toBe(false);
  });
});
