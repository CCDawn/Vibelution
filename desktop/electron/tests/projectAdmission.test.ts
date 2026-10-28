import { mkdirSync, mkdtempSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ProjectAdmission, registeredInstancesForPhysicalRoot } from "../src/lifecycle/projectAdmission.js";

describe("process-local project admission", () => {
  it("observes unresolved calls without changing them and refuses a seal until they finish", async () => {
    const temp = mkdtempSync(join(tmpdir(), "project-observed-"));
    try {
      const gate = new ProjectAdmission();
      let finish!: () => void;
      const pending = new Promise<void>(resolve => { finish = resolve; });
      const running = gate.observe(() => { throw new Error("unregistered"); }, async ticket => {
        expect(ticket).toBeUndefined(); await pending; return "original result";
      });
      expect(() => gate.seal(temp)).toThrow("PROJECT_ADMISSION_UNKNOWN");
      finish(); expect(await running).toBe("original result");
      const seal = gate.seal(temp); seal.check(); seal.release();
    } finally { rmSync(temp, { recursive: true, force: true }); }
  });

  it("revokes an active seal before allowing an unclassifiable call and blocks only the bound project", async () => {
    const temp = mkdtempSync(join(tmpdir(), "project-observed-seal-"));
    try {
      const a = join(temp, "a"), b = join(temp, "b"); mkdirSync(a); mkdirSync(b);
      const gate = new ProjectAdmission(), seal = gate.seal(a);
      expect(await gate.observe(() => b, async () => "other project")).toBe("other project");
      await expect(gate.observe(() => a, async () => "must not execute")).rejects.toThrow("PROJECT_ADMISSION_SEALED");
      expect(await gate.observe(() => { throw new Error("unregistered"); }, async () => "unchanged")).toBe("unchanged");
      expect(seal.signal.aborted).toBe(true);
      expect(() => seal.check()).toThrow("PROJECT_ADMISSION_UNKNOWN");
      await expect(seal.drain()).rejects.toThrow("PROJECT_ADMISSION_UNKNOWN");
    } finally { rmSync(temp, { recursive: true, force: true }); }
  });

  it("revokes synchronously but waits for the captured worker drain before allowing unknown work", async () => {
    const temp = mkdtempSync(join(tmpdir(), "project-observed-drain-"));
    try {
      const gate = new ProjectAdmission();
      let finish!: () => void;
      const drained = new Promise<void>(resolve => { finish = resolve; });
      const seal = gate.seal(temp, { drainOnRevoke: () => drained });
      let entered = false;
      const work = gate.observe(() => { throw new Error("unregistered"); }, async () => { entered = true; return "allowed"; });
      expect(seal.signal.aborted).toBe(true);
      expect(() => seal.check()).toThrow("PROJECT_ADMISSION_UNKNOWN");
      expect(entered).toBe(false);
      await expect(gate.observe(() => temp, async () => "same project")).rejects.toThrow("PROJECT_ADMISSION_SEALED");
      finish();
      expect(await work).toBe("allowed");
      expect(entered).toBe(true);
      expect(gate.hasSeals()).toBe(false);
    } finally { rmSync(temp, { recursive: true, force: true }); }
  });
  it("matches registry aliases by physical identity and rejects every unattributed row", () => {
    const temp = mkdtempSync(join(tmpdir(), "project-admission-alias-"));
    try {
      const a = join(temp, "a"), b = join(temp, "b"), alias = join(temp, "alias");
      mkdirSync(a); mkdirSync(b); symlinkSync(a, alias, process.platform === "win32" ? "junction" : "dir");
      expect(registeredInstancesForPhysicalRoot({ one: { projectRoot: alias }, two: { projectRoot: b } }, a)).toEqual(["one"]);
      expect(() => registeredInstancesForPhysicalRoot({ unknown: {} }, a)).toThrow("PROJECT_ADMISSION_UNKNOWN");
      if (process.platform === "win32")
        expect(registeredInstancesForPhysicalRoot({ one: { projectRoot: a.toUpperCase() } }, a)).toEqual(["one"]);
    } finally { rmSync(temp, { recursive: true, force: true }); }
  });
  it("fails closed on unattributed work, then drains bound work while blocking new opens", async () => {
    const temp = mkdtempSync(join(tmpdir(), "project-admission-"));
    try {
      const a = join(temp, "a"), b = join(temp, "b"); mkdirSync(a); mkdirSync(b);
      const gate = new ProjectAdmission();
      const first = gate.enter();
      expect(() => gate.seal(a)).toThrow("PROJECT_ADMISSION_UNKNOWN");
      first.bind(a);
      expect(() => first.check(b)).toThrow("PROJECT_ADMISSION_UNKNOWN");
      const seal = gate.seal(a);
      expect(() => first.check()).toThrow("PROJECT_ADMISSION_SEALED");
      expect(() => gate.enter()).toThrow("PROJECT_ADMISSION_UNKNOWN");
      expect(() => gate.enter(a)).toThrow("PROJECT_ADMISSION_SEALED");
      const other = gate.enter(b); other.check();
      expect(await gate.run(() => b, async ticket => { ticket.check(); return "other-project"; })).toBe("other-project");
      let drained = false;
      const drain = seal.drain().then(() => { drained = true; });
      await Promise.resolve();
      expect(drained).toBe(false);
      first.finish(); await drain;
      expect(drained).toBe(true);
      other.finish(); seal.release();
      const later = gate.enter(a); later.check(); later.finish();
    } finally { rmSync(temp, { recursive: true, force: true }); }
  });
});
