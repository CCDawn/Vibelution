import { fsyncSync, mkdtempSync, mkdirSync, readdirSync, renameSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LegacyReminderSourceFence } from "../src/notifications/legacyReminderSourceFence.js";

vi.mock("node:fs", async importOriginal => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return { ...actual, fsyncSync: vi.fn(actual.fsyncSync), readdirSync: vi.fn(actual.readdirSync) };
});

const roots: string[] = [];
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "legacy-reminder-source-"));
  roots.push(root);
  const a = join(root, "project-a"), b = join(root, "project-b"), directory = join(root, "fences");
  mkdirSync(a); mkdirSync(b);
  const binding = (projectId: string, physicalRoot: string) => {
    const info = statSync(physicalRoot, { bigint: true });
    return { projectId, instanceId: "main", physicalRoot, physicalIdentity: { device: info.dev.toString(), inode: info.ino.toString() } };
  };
  return { root, directory, source: binding("project-a", a), other: binding("project-b", b), binding,
    fence: new LegacyReminderSourceFence(directory) };
}
afterEach(() => { vi.clearAllMocks(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

describe("current-process legacy reminder source fence", () => {
  it("persists stop before draining admitted submissions and leaves other sources active", async () => {
    const { fence, directory, source, other } = fixture();
    let finish!: (value: string) => void;
    const sending = vi.fn(() => new Promise<string>(resolve => { finish = resolve; }));
    const admitted = fence.submit(source, sending);
    await vi.waitFor(() => expect(sending).toHaveBeenCalledOnce());
    let drained = false;
    const stop = fence.stop(source).then(value => { drained = true; return value; });
    expect(await fence.submit(source, sending)).toEqual({ delivered: "source_retired" });
    expect(await fence.submit(other, async () => "other" )).toBe("other");
    expect(drained).toBe(false);
    finish("submitted");
    expect(await admitted).toBe("submitted");
    expect(await stop).toEqual({ boundCallsDrained: true, readyForCutover: false });
    // Re-import with a new module state to simulate a process restart; the
    // result must come from the on-disk reservation, not the in-memory fence.
    vi.resetModules();
    const reopenedModule = await import("../src/notifications/legacyReminderSourceFence.js");
    const restarted = new reopenedModule.LegacyReminderSourceFence(directory);
    expect(await restarted.isStopped(source)).toBe(true);
    expect(await restarted.submit(source, sending)).toEqual({ delivered: "source_retired" });
    expect(await restarted.submit(null, async () => "unbound")).toBe("unbound");
    expect(await restarted.submit(other, async () => "other")).toBe("other");
    expect(sending).toHaveBeenCalledOnce();
  });

  it("shares admission and drain state between owners of the same directory in one process", async () => {
    const { fence, directory, source } = fixture();
    const second = new LegacyReminderSourceFence(directory);
    let finish!: () => void;
    const send = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
    const admitted = fence.submit(source, send);
    await vi.waitFor(() => expect(send).toHaveBeenCalledOnce());
    let done = false;
    const stopped = second.stop(source).then(() => { done = true; });
    expect(await fence.submit(source, send)).toEqual({ delivered: "source_retired" });
    expect(done).toBe(false);
    finish();
    await admitted;
    await stopped;
    expect(done).toBe(true);
  });

  it("keeps the physical instance fenced across registry ID changes", async () => {
    const { fence, source } = fixture();
    await fence.stop(source);
    expect(await fence.isStopped({ ...source, projectId: "new-registration" })).toBe(true);
    expect(await fence.submit({ ...source, projectId: "new-registration" }, async () => "bad"))
      .toEqual({ delivered: "source_retired" });
  });

  it("does not apply an old stop to a replacement project at the same path", async () => {
    const { root, fence, source, binding, directory } = fixture();
    await fence.stop(source);
    renameSync(source.physicalRoot, join(root, "previous-project"));
    mkdirSync(source.physicalRoot);
    const replacement = binding("project-new", source.physicalRoot);
    await expect(fence.isStopped(source)).rejects.toThrow("LEGACY_REMINDER_SOURCE_CHANGED");
    expect(await fence.isStopped(replacement)).toBe(false);
    expect(await fence.submit(replacement, async () => "new project")).toBe("new project");
    vi.resetModules();
    const reopenedModule = await import("../src/notifications/legacyReminderSourceFence.js");
    const restarted = new reopenedModule.LegacyReminderSourceFence(directory);
    expect(await restarted.isStopped(replacement)).toBe(false);
  });

  it("does not claim a confirmed stop after a write flush error even if a record exists", async () => {
    const { fence, source, directory } = fixture();
    vi.mocked(fsyncSync).mockImplementationOnce(() => { throw new Error("flush failed"); });
    await expect(fence.stop(source)).rejects.toMatchObject({ code: "request_store_write_failed" });
    expect(readdirSync(directory)).toHaveLength(1);
    await expect(fence.isStopped(source)).rejects.toThrow("LEGACY_REMINDER_FENCE_UNCONFIRMED");
    await expect(fence.stop(source)).rejects.toThrow("LEGACY_REMINDER_FENCE_UNCONFIRMED");
    expect(await fence.submit(source, async () => "not sent")).toEqual({ delivered: "source_retired" });
  });

  it("does not report a completed drain when the source directory changes during an admitted call", async () => {
    const { root, fence, source } = fixture();
    let finish!: () => void;
    const send = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
    const admitted = fence.submit(source, send);
    await vi.waitFor(() => expect(send).toHaveBeenCalledOnce());
    const stopping = fence.stop(source);
    const rejected = expect(stopping).rejects.toThrow("LEGACY_REMINDER_SOURCE_CHANGED");
    renameSync(source.physicalRoot, join(root, "previous-project"));
    mkdirSync(source.physicalRoot);
    finish();
    await admitted;
    await rejected;
    renameSync(source.physicalRoot, join(root, "replacement-project"));
    renameSync(join(root, "previous-project"), source.physicalRoot);
    await expect(fence.isStopped(source)).rejects.toThrow("LEGACY_REMINDER_FENCE_UNCONFIRMED");
  });

  it("rejects a stale binding when the directory changes between lookup and submission", async () => {
    const { root, fence, source } = fixture();
    const send = vi.fn(async () => "submitted");
    const pending = fence.submit(source, send);
    const rejected = expect(pending).rejects.toThrow("LEGACY_REMINDER_SOURCE_CHANGED");
    renameSync(source.physicalRoot, join(root, "previous-project"));
    mkdirSync(source.physicalRoot);
    await rejected;
    expect(send).not.toHaveBeenCalled();
  });

  it("never reports stop on a store read error and preserves unbound legacy behavior", async () => {
    const { fence, source } = fixture();
    vi.mocked(readdirSync).mockImplementationOnce(() => { throw new Error("cannot read"); });
    await expect(fence.isStopped(source)).rejects.toMatchObject({ code: "request_store_read_failed" });
    expect(await fence.submit(null, async () => "unbound")).toBe("unbound");
    expect(await fence.isStopped(source)).toBe(false);
    await fence.stop(source);
    vi.mocked(readdirSync).mockImplementationOnce(() => { throw new Error("cannot read"); });
    await expect(fence.isStopped(source)).rejects.toMatchObject({ code: "request_store_read_failed" });
    expect(await fence.submit(source, async () => "not sent")).toEqual({ delivered: "source_retired" });
  });

  it("never treats a missing or corrupt persisted record as proof of stop", async () => {
    const { fence, directory, source } = fixture();
    await fence.stop(source);
    const record = join(directory, readdirSync(directory)[0]!);
    rmSync(record);
    await expect(fence.isStopped(source)).rejects.toThrow("LEGACY_REMINDER_FENCE_UNCONFIRMED");
    expect(await fence.submit(source, async () => "bad")).toEqual({ delivered: "source_retired" });
    writeFileSync(record, "incomplete");
    await expect(fence.isStopped(source)).rejects.toMatchObject({ code: "request_store_invalid" });
  });

  it("does not infer a previous stop after its durable record disappears across restart", async () => {
    const { fence, directory, source } = fixture();
    await fence.stop(source);
    rmSync(join(directory, readdirSync(directory)[0]!));
    vi.resetModules();
    const reopenedModule = await import("../src/notifications/legacyReminderSourceFence.js");
    const restarted = new reopenedModule.LegacyReminderSourceFence(directory);
    expect(await restarted.isStopped(source)).toBe(false);
    expect(await restarted.submit(source, async () => "old-sender-still-active")).toBe("old-sender-still-active");
  });
});
