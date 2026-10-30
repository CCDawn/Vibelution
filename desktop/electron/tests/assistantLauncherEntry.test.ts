import { describe, expect, it, vi } from "vitest";
import { createAssistantLauncherEntry } from "../src/assistant/launcherEntry.js";

describe("Resident assistant Launcher entry", () => {
  it("opens directly without selecting or connecting a project", async () => {
    const present = vi.fn(async () => undefined);
    const open = createAssistantLauncherEntry({ isQuitting: () => false, present });
    await expect(open()).resolves.toEqual({ opened: true });
    expect(present).toHaveBeenCalledOnce();
  });
  it("coalesces concurrent clicks and retries after failure", async () => {
    let finish!: () => void;
    const present = vi.fn().mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve; }))
      .mockRejectedValueOnce(new Error("unavailable")).mockResolvedValue(undefined);
    const open = createAssistantLauncherEntry({ isQuitting: () => false, present });
    const first = open(); expect(open()).toBe(first); finish();
    await expect(first).resolves.toEqual({ opened: true });
    await expect(open()).rejects.toThrow("unavailable");
    await expect(open()).resolves.toEqual({ opened: true });
    expect(present).toHaveBeenCalledTimes(3);
  });
  it("does not present during shutdown", async () => {
    const present = vi.fn(async () => undefined);
    const open = createAssistantLauncherEntry({ isQuitting: () => true, present });
    await expect(open()).resolves.toEqual({ opened: false });
    expect(present).not.toHaveBeenCalled();
  });
});
