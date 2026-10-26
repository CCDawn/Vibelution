import { describe, expect, it, vi } from "vitest";
import { createAssistantLauncherEntry } from "../src/assistant/launcherEntry.js";

function fixture() {
  const actions = {
    isQuitting: vi.fn(() => false), openExisting: vi.fn(async () => false),
    chooseProject: vi.fn(async (): Promise<string | null> => "human-project"),
    connect: vi.fn(async (_root: string) => true), openConnected: vi.fn(async () => undefined),
  };
  return { actions, open: createAssistantLauncherEntry(actions) };
}

describe("Resident assistant Launcher entry", () => {
  it("focuses the connected project manager without another selection or connection", async () => {
    const { actions, open } = fixture(); actions.openExisting.mockResolvedValue(true);
    await expect(open()).resolves.toEqual({ opened: true });
    expect(actions.chooseProject).not.toHaveBeenCalled(); expect(actions.connect).not.toHaveBeenCalled();
  });
  it("selects context explicitly and opens management without a runtime start action", async () => {
    const { actions, open } = fixture();
    await expect(open()).resolves.toEqual({ opened: true });
    expect(actions.connect).toHaveBeenCalledExactlyOnceWith("human-project");
    expect(actions.openConnected).toHaveBeenCalledTimes(1);
  });
  it("deduplicates simultaneous header and tray requests and allows retry after cancellation", async () => {
    const { actions, open } = fixture();
    let finish!: (root: string | null) => void;
    actions.chooseProject.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const first = open(); expect(open()).toBe(first);
    await Promise.resolve(); finish(null);
    await expect(first).resolves.toEqual({ opened: false });
    expect(actions.connect).not.toHaveBeenCalled();
    await expect(open()).resolves.toEqual({ opened: true });
    expect(actions.chooseProject).toHaveBeenCalledTimes(2);
  });
  it("does not open after shutdown or an unconfirmed connection", async () => {
    const { actions, open } = fixture(); actions.connect.mockResolvedValueOnce(false);
    await expect(open()).rejects.toThrow("ASSISTANT_LAUNCHER_UNAVAILABLE");
    expect(actions.openConnected).not.toHaveBeenCalled();
    actions.isQuitting.mockReturnValue(true);
    await expect(open()).resolves.toEqual({ opened: false });
    expect(actions.chooseProject).toHaveBeenCalledTimes(1);
  });
});
