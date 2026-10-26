import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

const failure = vi.hoisted(() => ({
  remaining: 0, calls: 0, code: "EPERM", onRename: () => {}
}));

function rejectTransientRename(): void {
  failure.calls += 1;
  failure.onRename();
  if (failure.remaining-- > 0) throw Object.assign(new Error("state file is busy"), { code: failure.code });
}

vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return { ...actual, renameSync: (...args: Parameters<typeof actual.renameSync>) => {
    rejectTransientRename();
    return actual.renameSync(...args);
  } };
});
import { writeLauncherStateFile } from "../src/process/workbenchBackend.js";

const roots: string[] = [];
function statePath(): string {
  const root = mkdtempSync(join(tmpdir(), "vibelution-state-replace-"));
  roots.push(root);
  const path = join(root, "state.json");
  writeFileSync(path, JSON.stringify({ phase: "previous" }));
  return path;
}

afterEach(() => {
  failure.remaining = 0;
  failure.calls = 0;
  failure.code = "EPERM";
  failure.onRename = () => {};
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("Launcher state replacement under transient file contention", () => {
  it.each(["EPERM", "EACCES", "EBUSY"])("retries %s and publishes complete state", async (code) => {
    const path = statePath();
    failure.code = code;
    failure.remaining = 1;
    await expect(writeLauncherStateFile(path, { phase: "steady" })).resolves.toBeUndefined();
    expect(JSON.parse(readFileSync(path, "utf8"))).toEqual({ phase: "steady" });
    expect(failure.calls).toBe(2);
    expect(readdirSync(roots[0])).toEqual(["state.json"]);
  });

  it("bounds retries and preserves the previous document when replacement stays denied", async () => {
    const path = statePath();
    failure.remaining = 100;
    await expect(writeLauncherStateFile(path, { phase: "steady" })).rejects.toMatchObject({ code: "EPERM" });
    expect(failure.calls).toBeGreaterThan(1);
    expect(failure.calls).toBeLessThanOrEqual(6);
    expect(JSON.parse(readFileSync(path, "utf8"))).toEqual({ phase: "previous" });
    expect(readdirSync(roots[0])).toEqual(["state.json"]);
  });

  it("propagates unrelated I/O failure without retry", async () => {
    const path = statePath();
    failure.code = "EIO";
    failure.remaining = 100;
    await expect(writeLauncherStateFile(path, { phase: "steady" })).rejects.toMatchObject({ code: "EIO" });
    expect(failure.calls).toBe(1);
    expect(JSON.parse(readFileSync(path, "utf8"))).toEqual({ phase: "previous" });
    expect(readdirSync(roots[0])).toEqual(["state.json"]);
  });

  it("does not publish a superseded intent during a retry", async () => {
    const path = statePath();
    const controller = new AbortController();
    failure.remaining = 100;
    failure.onRename = () => controller.abort(new Error("superseded"));
    await expect(writeLauncherStateFile(path, { phase: "steady" }, controller.signal)).rejects.toThrow();
    expect(failure.calls).toBe(1);
    expect(JSON.parse(readFileSync(path, "utf8"))).toEqual({ phase: "previous" });
    expect(readdirSync(roots[0])).toEqual(["state.json"]);
  });

  it("rejects an already cancelled write before touching the destination", async () => {
    const path = statePath();
    const controller = new AbortController();
    controller.abort(new Error("superseded"));
    await expect(writeLauncherStateFile(path, { phase: "steady" }, controller.signal)).rejects.toThrow();
    expect(failure.calls).toBe(0);
    expect(JSON.parse(readFileSync(path, "utf8"))).toEqual({ phase: "previous" });
    expect(readdirSync(roots[0])).toEqual(["state.json"]);
  });

  it("rechecks the background request fence after transient rename contention", async () => {
    const path = statePath();
    let current = true;
    failure.remaining = 1;
    failure.onRename = () => { current = false; };
    await expect(writeLauncherStateFile(path, { phase: "steady" }, undefined, () => current)).rejects.toThrow("superseded");
    expect(failure.calls).toBe(1);
    expect(JSON.parse(readFileSync(path, "utf8"))).toEqual({ phase: "previous" });
    expect(readdirSync(roots[0])).toEqual(["state.json"]);
  });
});
