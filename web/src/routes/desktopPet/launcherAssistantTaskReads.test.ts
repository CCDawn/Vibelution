import { describe, expect, it, vi } from "vitest";
import { readLauncherAssistantTaskSource } from "./launcherAssistantTaskReads";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

describe("Launcher native task observation reads", () => {
  it("waits for the real IPC after observer abort and gives a later refetch a fresh receipt", async () => {
    const native = deferred<string>();
    const observer = new AbortController();
    const original = readLauncherAssistantTaskSource("same-assistant", observer.signal, () => native.promise);
    const rejected = expect(original).rejects.toMatchObject({ name: "AbortError" });
    await Promise.resolve();
    observer.abort();
    const freshRead = vi.fn(async () => "receipt after approval");
    const next = readLauncherAssistantTaskSource("same-assistant", new AbortController().signal, freshRead);
    await Promise.resolve();
    expect(freshRead).not.toHaveBeenCalled();
    native.resolve("receipt before approval");
    await rejected;
    expect(await next).toBe("receipt after approval");
    expect(freshRead).toHaveBeenCalledTimes(1);
  });

  it("skips an aborted queued read and lets the next source continue after failure", async () => {
    const native = deferred<void>();
    const first = readLauncherAssistantTaskSource("queued-assistant", new AbortController().signal, () => native.promise);
    const observer = new AbortController();
    const cancelledRead = vi.fn(async () => "obsolete");
    const cancelled = readLauncherAssistantTaskSource("queued-assistant", observer.signal, cancelledRead);
    const rejected = expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
    observer.abort();
    const failed = readLauncherAssistantTaskSource("queued-assistant", new AbortController().signal,
      async () => { throw new Error("source unavailable"); });
    const failure = expect(failed).rejects.toThrow("source unavailable");
    const recovered = readLauncherAssistantTaskSource("queued-assistant", new AbortController().signal, async () => "fresh");
    native.resolve();
    await first; await rejected; await failure;
    expect(cancelledRead).not.toHaveBeenCalled();
    expect(await recovered).toBe("fresh");
  });

  it("does not block a new identity behind a slow previous identity or share its data", async () => {
    const native = deferred<string>();
    const previous = readLauncherAssistantTaskSource("previous-assistant", new AbortController().signal, () => native.promise);
    const next = readLauncherAssistantTaskSource("new-assistant", new AbortController().signal, async () => "new identity");
    expect(await next).toBe("new identity");
    native.resolve("previous identity");
    expect(await previous).toBe("previous identity");
  });
});
