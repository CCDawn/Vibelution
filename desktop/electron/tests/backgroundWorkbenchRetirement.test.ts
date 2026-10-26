import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getBackgroundWorkbenchRetirement,
  hasBackgroundWorkbenchRetirement,
  startBackgroundWorkbenchRetirement,
  waitForBackgroundWorkbenchRetirement,
  type BackgroundWorkbenchRetirementInput
} from "../src/process/backgroundWorkbenchRetirement.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

let rootSequence = 0;
function fixture(overrides: Partial<BackgroundWorkbenchRetirementInput> = {}) {
  const retireCaptured = vi.fn(async () => true);
  const portClosed = vi.fn(async () => true);
  const isCurrent = vi.fn(() => true);
  const commitClosed = vi.fn(async () => true);
  const input: BackgroundWorkbenchRetirementInput = {
    workspaceRoot: `C:/background-retirement/${++rootSequence}`,
    requestId: "close-1", retireCaptured, portClosed, isCurrent, commitClosed,
    retryIntervalMs: 100, ...overrides
  };
  return { input, retireCaptured, portClosed, isCurrent, commitClosed };
}

describe("background owned workbench retirement", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("stays pending through late native retirement and late port closure", async () => {
    const native = deferred<boolean>();
    const f = fixture();
    f.retireCaptured.mockImplementation(() => native.promise);
    f.portClosed.mockResolvedValue(false);
    const owner = startBackgroundWorkbenchRetirement(f.input);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(owner.status).toBe("pending");
    expect(f.retireCaptured).toHaveBeenCalledOnce();
    expect(f.portClosed).not.toHaveBeenCalled();
    expect(f.commitClosed).not.toHaveBeenCalled();

    native.resolve(true);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(300);
    expect(owner.status).toBe("pending");
    expect(f.retireCaptured).toHaveBeenCalledOnce();
    f.portClosed.mockResolvedValue(true);
    await vi.advanceTimersByTimeAsync(100);
    await expect(owner.completion).resolves.toBe("closed");
    expect(f.commitClosed).toHaveBeenCalledOnce();
    expect(hasBackgroundWorkbenchRetirement(f.input.workspaceRoot)).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps an unavailable initial fence pending without starting retirement until it recovers", async () => {
    const f = fixture();
    f.isCurrent.mockImplementation(() => { throw new Error("state temporarily unreadable"); });
    const owner = startBackgroundWorkbenchRetirement(f.input);
    await vi.advanceTimersByTimeAsync(299);
    expect(owner.status).toBe("pending");
    expect(hasBackgroundWorkbenchRetirement(f.input.workspaceRoot)).toBe(true);
    expect(f.isCurrent).toHaveBeenCalledTimes(3);
    expect(f.retireCaptured).not.toHaveBeenCalled();
    expect(f.portClosed).not.toHaveBeenCalled();
    expect(f.commitClosed).not.toHaveBeenCalled();
    f.isCurrent.mockReturnValue(true);
    await vi.advanceTimersByTimeAsync(1);
    await expect(owner.completion).resolves.toBe("closed");
    expect(f.retireCaptured).toHaveBeenCalledOnce();
    expect(f.commitClosed).toHaveBeenCalledOnce();
  });

  it.each(["retire", "port"])("preserves confirmed retirement when the fence becomes unavailable after %s", async (stage) => {
    const f = fixture();
    let unavailable = false;
    f.isCurrent.mockImplementation(() => {
      if (unavailable) throw new Error("state temporarily unreadable");
      return true;
    });
    const makeUnavailable = async () => { unavailable = true; return true; };
    if (stage === "retire") f.retireCaptured.mockImplementationOnce(makeUnavailable);
    else f.portClosed.mockImplementationOnce(makeUnavailable);
    const owner = startBackgroundWorkbenchRetirement(f.input);
    await vi.advanceTimersByTimeAsync(299);
    expect(owner.status).toBe("pending");
    expect(hasBackgroundWorkbenchRetirement(f.input.workspaceRoot)).toBe(true);
    expect(f.retireCaptured).toHaveBeenCalledOnce();
    expect(f.portClosed).toHaveBeenCalledTimes(stage === "retire" ? 0 : 1);
    expect(f.commitClosed).not.toHaveBeenCalled();
    unavailable = false;
    await vi.advanceTimersByTimeAsync(1);
    await expect(owner.completion).resolves.toBe("closed");
    expect(f.retireCaptured).toHaveBeenCalledOnce();
    expect(f.portClosed).toHaveBeenCalledTimes(stage === "retire" ? 1 : 2);
    expect(f.commitClosed).toHaveBeenCalledOnce();
  });

  it.each(["false", "throws"])("retries native %s results serially at the configured interval", async (failure) => {
    const f = fixture();
    f.retireCaptured.mockImplementationOnce(async () => {
      if (failure === "throws") throw new Error("native still draining");
      return false;
    });
    const owner = startBackgroundWorkbenchRetirement(f.input);
    await vi.advanceTimersByTimeAsync(99);
    expect(owner.status).toBe("pending");
    expect(f.retireCaptured).toHaveBeenCalledOnce();
    expect(f.portClosed).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await expect(owner.completion).resolves.toBe("closed");
    expect(f.retireCaptured).toHaveBeenCalledTimes(2);
  });

  it("coalesces normalized roots without using replacement closures or request ids", async () => {
    const native = deferred<boolean>();
    const f = fixture();
    f.retireCaptured.mockImplementation(() => native.promise);
    const owner = startBackgroundWorkbenchRetirement(f.input);
    const other = fixture({ workspaceRoot: `${f.input.workspaceRoot.toUpperCase()}/./`, requestId: "close-2" });
    expect(startBackgroundWorkbenchRetirement(other.input)).toBe(owner);
    expect(owner.requestId).toBe("close-1");
    expect(getBackgroundWorkbenchRetirement(other.input.workspaceRoot)).toBe(owner);
    expect(hasBackgroundWorkbenchRetirement(other.input.workspaceRoot)).toBe(true);
    const waiting = waitForBackgroundWorkbenchRetirement(other.input.workspaceRoot);
    native.resolve(true);
    await expect(waiting).resolves.toBe("closed");
    expect(other.retireCaptured).not.toHaveBeenCalled();
    expect(other.commitClosed).not.toHaveBeenCalled();
    await expect(waitForBackgroundWorkbenchRetirement(f.input.workspaceRoot)).resolves.toBeUndefined();
  });

  it("keeps different roots independent while one native attempt remains in flight", async () => {
    const native = deferred<boolean>();
    const first = fixture();
    first.retireCaptured.mockImplementation(() => native.promise);
    const firstOwner = startBackgroundWorkbenchRetirement(first.input);
    const second = fixture();
    const secondOwner = startBackgroundWorkbenchRetirement(second.input);
    await expect(secondOwner.completion).resolves.toBe("closed");
    expect(firstOwner.status).toBe("pending");
    native.resolve(true);
    await expect(firstOwner.completion).resolves.toBe("closed");
  });

  it("never repeats successful native retirement when the port probe or commit throws", async () => {
    const f = fixture();
    f.portClosed.mockRejectedValueOnce(new Error("probe failed"));
    f.commitClosed.mockRejectedValueOnce(new Error("state temporarily unavailable"));
    const owner = startBackgroundWorkbenchRetirement(f.input);
    await vi.advanceTimersByTimeAsync(100);
    expect(owner.status).toBe("pending");
    expect(f.commitClosed).toHaveBeenCalledOnce();
    await vi.advanceTimersByTimeAsync(100);
    await expect(owner.completion).resolves.toBe("closed");
    expect(f.retireCaptured).toHaveBeenCalledOnce();
    expect(f.portClosed).toHaveBeenCalledTimes(3);
    expect(f.commitClosed).toHaveBeenCalledTimes(2);
  });

  it.each(["before-retire", "during-retire", "during-port", "during-retry"])("honors a superseded fence %s without committing", async (stage) => {
    const blocked = deferred<boolean>();
    const f = fixture();
    if (stage === "before-retire") f.isCurrent.mockReturnValue(false);
    if (stage === "during-retire") f.retireCaptured.mockImplementation(() => blocked.promise);
    if (stage === "during-port") f.portClosed.mockImplementation(() => blocked.promise);
    if (stage === "during-retry") f.retireCaptured.mockResolvedValue(false);
    const owner = startBackgroundWorkbenchRetirement(f.input);
    await vi.advanceTimersByTimeAsync(0);
    f.isCurrent.mockReturnValue(false);
    blocked.resolve(true);
    await vi.advanceTimersByTimeAsync(100);
    await expect(owner.completion).resolves.toBe("superseded");
    expect(f.commitClosed).not.toHaveBeenCalled();
    expect(f.retireCaptured).toHaveBeenCalledTimes(stage === "before-retire" ? 0 : 1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("treats a rejected commit fence as superseded and never reports closed", async () => {
    const f = fixture();
    f.commitClosed.mockResolvedValue(false);
    const owner = startBackgroundWorkbenchRetirement(f.input);
    await expect(owner.completion).resolves.toBe("superseded");
    expect(owner.status).toBe("superseded");
    await vi.advanceTimersByTimeAsync(10_000);
    expect(f.commitClosed).toHaveBeenCalledOnce();
    expect(hasBackgroundWorkbenchRetirement(f.input.workspaceRoot)).toBe(false);
  });

  it("does not let old completion cleanup delete a replacement owner", async () => {
    const f = fixture();
    const replacementNative = deferred<boolean>();
    const next = fixture({ workspaceRoot: f.input.workspaceRoot, requestId: "next-close" });
    next.retireCaptured.mockImplementation(() => replacementNative.promise);
    const oldOwner = startBackgroundWorkbenchRetirement(f.input);
    const replacement = oldOwner.completion.then(() => startBackgroundWorkbenchRetirement(next.input));
    const nextOwner = await replacement;
    await vi.advanceTimersByTimeAsync(0);
    expect(nextOwner).not.toBe(oldOwner);
    expect(getBackgroundWorkbenchRetirement(f.input.workspaceRoot)).toBe(nextOwner);
    replacementNative.resolve(true);
    await expect(nextOwner.completion).resolves.toBe("closed");
  });

  it("supports an injected retry timer without releasing the pending owner", async () => {
    const tick = deferred<void>();
    const delay = vi.fn(() => tick.promise);
    const f = fixture({ delay });
    f.retireCaptured.mockResolvedValueOnce(false);
    const owner = startBackgroundWorkbenchRetirement(f.input);
    await vi.advanceTimersByTimeAsync(0);
    expect(delay).toHaveBeenCalledWith(100);
    expect(hasBackgroundWorkbenchRetirement(f.input.workspaceRoot)).toBe(true);
    tick.resolve();
    await expect(owner.completion).resolves.toBe("closed");
  });
});
