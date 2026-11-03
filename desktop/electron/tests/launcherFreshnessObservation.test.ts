import { describe, expect, it, vi } from "vitest";
import { createLauncherFreshnessObservation } from "../src/process/launcherFreshnessObservation.js";

describe("Launcher freshness observations", () => {
  it("shares concurrent reads without caching a settled read", async () => {
    let finish!: (value: number) => void;
    const load = vi.fn(() => new Promise<number>(resolve => { finish = resolve; }));
    const observe = createLauncherFreshnessObservation(() => "project:1", load);
    const readings = [observe(), observe(), observe()];
    await Promise.resolve();
    expect(load).toHaveBeenCalledOnce();
    finish(7);
    expect(await Promise.all(readings)).toEqual([7, 7, 7]);
    const next = observe();
    await Promise.resolve();
    expect(load).toHaveBeenCalledTimes(2);
    finish(8);
    expect(await next).toBe(8);
  });

  it("shares one trailing read after the project or epoch changes", async () => {
    let identity = "project:1";
    const finishes: Array<(value: number) => void> = [];
    const load = vi.fn(() => new Promise<number>(resolve => { finishes.push(resolve); }));
    const observe = createLauncherFreshnessObservation(() => identity, load);
    const readings = [observe(), observe()];
    await Promise.resolve();
    identity = "other-project:2";
    readings.push(observe());
    finishes[0](1);
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    finishes[1](2);
    expect(await Promise.all(readings)).toEqual([2, 2, 2]);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("allows a retry after a rejected read", async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error("read failed")).mockResolvedValueOnce(3);
    const observe = createLauncherFreshnessObservation(() => "project:1", load);
    await expect(observe()).rejects.toThrow("read failed");
    expect(await observe()).toBe(3);
  });

  it("does not return an old failure after the epoch changed", async () => {
    let epoch = 1;
    let reject!: (error: Error) => void;
    const load = vi.fn().mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail; }))
      .mockResolvedValueOnce(9);
    const observe = createLauncherFreshnessObservation(() => String(epoch), load);
    const reading = observe();
    await Promise.resolve();
    epoch += 1;
    reject(new Error("obsolete read"));
    expect(await reading).toBe(9);
  });

  it("bounds repeated invalidation instead of returning obsolete proof", async () => {
    let epoch = 0;
    const load = vi.fn(async () => { epoch += 1; return epoch; });
    const observe = createLauncherFreshnessObservation(() => String(epoch), load);
    await expect(observe()).rejects.toThrow("version changed during inspection");
    expect(load).toHaveBeenCalledTimes(2);
  });
});
