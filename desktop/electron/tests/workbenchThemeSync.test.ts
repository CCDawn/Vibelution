import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { IpcMainInvokeEvent } from "electron";
import { publishAssistantTheme, ThemeProjectionTracker, workbenchThemeScope } from "../src/assistant/workbenchThemeSync.js";
import { ThemeAuthority } from "../src/assistant/themeAuthority.js";
import { writeLauncherStateFile } from "../src/process/workbenchBackend.js";

const directories: string[] = [];
function path(): string { const dir = mkdtempSync(join(tmpdir(), "theme-authority-")); directories.push(dir); return join(dir, "theme.json"); }
afterEach(() => { for (const dir of directories.splice(0)) rmSync(dir, { recursive: true, force: true }); });

describe("theme authority", () => {
  it("persists without an assistant and restores the same revision after restart", async () => {
    const file = path(), publish = vi.fn(), authority = new ThemeAuthority(file, publish);
    expect((await authority.read()).code).toBe("uninitialized");
    const written = await authority.set("dark", null);
    expect(written.snapshot).toMatchObject({ theme: "dark", revision: 1 });
    expect(await new ThemeAuthority(file, vi.fn()).read()).toEqual({ code: "read", snapshot: written.snapshot });
  });

  it("serializes writes and rejects a delayed stale workbench choice", async () => {
    const file = path(); let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    const write = vi.fn(async (...args: Parameters<typeof writeLauncherStateFile>) => { await gate; return await writeLauncherStateFile(...args); });
    const authority = new ThemeAuthority(file, vi.fn(), write);
    const first = authority.set("dark", null), stale = authority.set("light", null);
    await vi.waitFor(() => expect(write).toHaveBeenCalledOnce());
    release();
    expect((await first).snapshot).toMatchObject({ theme: "dark", revision: 1 });
    expect((await stale).code).toBe("conflict");
    expect(write).toHaveBeenCalledOnce();
  });

  it("rechecks a queued document and leaves corrupt state unavailable", async () => {
    const file = path(), authority = new ThemeAuthority(file, vi.fn());
    expect((await authority.set("dark", null, undefined, () => false)).code).toBe("unavailable");
    writeFileSync(file, "not json");
    expect((await authority.read()).code).toBe("unavailable");
    expect((await authority.set("light")).code).toBe("unknown");
  });

  it("serializes opposite model writes and preserves their source for projections", async () => {
    const publish = vi.fn(), authority = new ThemeAuthority(path(), publish);
    const first = authority.set("dark"), second = authority.set("light");
    expect((await first).snapshot).toMatchObject({ revision: 1, theme: "dark" });
    expect((await second).snapshot).toMatchObject({ revision: 2, theme: "light" });
    expect(publish.mock.calls.map(call => [call[0].theme, call[1]])).toEqual([["dark", "model"], ["light", "model"]]);
  });

  it("admits only the registered main frame and keeps other projects local", () => {
    const frame = { url: "http://127.0.0.1:1234/config" }, sender = { mainFrame: frame };
    const event = { sender, senderFrame: frame } as unknown as IpcMainInvokeEvent;
    const provider = { trustedWorkbenchInstanceForSender: vi.fn(() => "main") };
    expect(workbenchThemeScope(event, provider)).toBe("main");
    provider.trustedWorkbenchInstanceForSender.mockReturnValue("branch");
    expect(workbenchThemeScope(event, provider)).toBe("local");
    expect(workbenchThemeScope({ ...event, senderFrame: { url: frame.url } } as IpcMainInvokeEvent, provider)).toBeNull();
  });

  it("projects only to the verified primary workbench", () => {
    const contents = { getURL: () => "http://127.0.0.1:1234/config" };
    const provider = { workbenchDialogParent: vi.fn(() => ({ webContents: contents })),
      trustedWorkbenchInstanceForSender: vi.fn(() => "main"), sendToWorkbench: vi.fn(() => true) };
    const snapshot = { epoch: "test", revision: 1, theme: "dark" as const, writeId: "a".repeat(32) };
    expect(publishAssistantTheme(snapshot, provider as never, "theme-event")).toBe(true);
    provider.trustedWorkbenchInstanceForSender.mockReturnValue("branch");
    expect(publishAssistantTheme(snapshot, provider as never, "theme-event")).toBe(false);
    expect(provider.sendToWorkbench).toHaveBeenCalledOnce();
  });

  it("requires an observed acknowledgement and reports a legacy conflict", async () => {
    const tracker = new ThemeProjectionTracker(), snapshot = { epoch: "epoch", revision: 1, theme: "dark" as const, writeId: "a".repeat(32) };
    tracker.begin(snapshot, "workbench", () => true);
    tracker.acknowledge(snapshot, "workbench", "conflict");
    expect(await tracker.wait(snapshot, "workbench")).toBe("conflict");
    const absent = { ...snapshot, revision: 2 };
    tracker.begin(absent, "workbench", () => false);
    expect(await tracker.wait(absent, "workbench")).toBe("unavailable");
  });
});
