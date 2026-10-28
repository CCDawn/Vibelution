import { describe, expect, it, vi } from "vitest";
import { createRequire } from "node:module";
import { randomBytes } from "node:crypto";
import { createHash } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { resolve } from "node:path";
import { join } from "node:path";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";

const addonPath = process.env.VIBELUTION_MUTEX_TEST_ADDON;
vi.mock("../src/process/workbenchJob.js", async () => {
  const { createRequire } = await import("node:module");
  const require = createRequire(import.meta.url);
  return { loadWorkbenchJobNative: () => require(process.env.VIBELUTION_MUTEX_TEST_ADDON!) };
});
import { tryAcquireReminderSourceMutex } from "../src/notifications/reminderSourceMutex.js";
import { LegacyReminderCoordinator, LegacyReminderDailyIntentStores } from "../src/notifications/legacyReminderCoordinator.js";

function evidenceFixture() {
  const root = mkdtempSync(join(tmpdir(), "mutex-evidence-"));
  const globalKey = randomBytes(32).toString("hex");
  return { root, authority: {
    indexDirectory: join(root, "index"), oldIntentDirectory: join(root, "old"),
    tryAcquireGlobal: () => tryAcquireReminderSourceMutex({ ledgerKey: globalKey, verify: () => {} }),
    inventoryReceipts: async () => ({ schemaVersion: 1, records: [], senders: 0 }),
    verifyRecovery: () => {},
  } };
}

describe.skipIf(!addonPath)("Windows source mutex wrapper", () => {
  it("checks trusted binding and never permits recursive acquire", () => {
    const key = randomBytes(32).toString("hex"), verify = vi.fn();
    const first = tryAcquireReminderSourceMutex({ ledgerKey: key, verify });
    expect(first?.abandoned).toBe(false);
    expect(verify).toHaveBeenCalledTimes(2);
    expect(tryAcquireReminderSourceMutex({ ledgerKey: key, verify })).toBeNull();
    first!.check();
    first!.release();
    expect(() => first!.release()).toThrow("REMINDER_MUTEX_RELEASED");
    const second = tryAcquireReminderSourceMutex({ ledgerKey: key, verify });
    expect(second).not.toBeNull();
    second!.release();
  });

  it("rejects a changed trusted binding and releases a lock after revalidation fails", () => {
    const key = randomBytes(32).toString("hex"), verify = vi.fn().mockImplementationOnce(() => {}).mockImplementationOnce(() => { throw new Error("changed"); });
    expect(() => tryAcquireReminderSourceMutex({ ledgerKey: key, verify })).toThrow("changed");
    const next = tryAcquireReminderSourceMutex({ ledgerKey: key, verify: () => {} });
    expect(next).not.toBeNull();
    next!.release();
    expect(() => tryAcquireReminderSourceMutex({ ledgerKey: "C:/renderer-path", verify: () => {} })).toThrow("REMINDER_MUTEX_INVALID");
    expect(() => tryAcquireReminderSourceMutex({ ledgerKey: key, verify: async () => {} })).toThrow("REMINDER_MUTEX_BINDING_CHANGED");
  });

  it("rejects unsafe native input and wrong external handles", () => {
    const addon = createRequire(import.meta.url)(addonPath!);
    expect(() => addon.tryAcquireReminderMutex("a".repeat(65))).toThrow("REMINDER_MUTEX_INVALID");
    expect(() => addon.releaseReminderMutex({})).toThrow("REMINDER_MUTEX_INVALID");
  });

  it("keeps the real sender mutex through settlement and reports contention before any intent", async () => {
    const ledgerKey = randomBytes(32).toString("hex"), sourceKey = randomBytes(32).toString("hex");
    const eventId = "affair-reminder:fixture:20261028";
    const eventKey = "legacy:" + createHash("sha256").update(JSON.stringify([sourceKey, eventId]), "ascii").digest("hex");
    const token = "b".repeat(64), cwd = resolve(process.cwd(), "../..");
    const code = "import os,sys; from core.infrastructure.reminder_source_mutex import _try_digest; h=_try_digest(os.environ['MUTEX_TEST_KEY']); print('held' if h else 'busy',flush=True); sys.stdin.readline(); h.release()";
    const child = spawn("python", ["-c", code], { cwd, env: { ...process.env, MUTEX_TEST_KEY: ledgerKey }, windowsHide: true, stdio: "pipe" });
    const fixture = evidenceFixture();
    try {
      const [data] = await once(child.stdout!, "data");
      expect(String(data).trim()).toBe("held");
      const stores = new LegacyReminderDailyIntentStores(fixture.authority.oldIntentDirectory);
      const reserveIntent = vi.fn((request) => stores.forDay("20261028").reserve(request));
      const attempts = { reserve: vi.fn(async () => ({ schemaVersion: 1, eventKey, state: "reserved", attemptToken: token })),
        settle: vi.fn(), abandon: vi.fn() };
      let releaseSettlement!: () => void;
      attempts.settle.mockImplementation(() => new Promise(resolve => { releaseSettlement = () => resolve({ schemaVersion: 1, eventKey, state: "submitted", channel: "system_notification" }); }));
      const coordinator = new LegacyReminderCoordinator({ forDay: () => ({ reserve: reserveIntent }) } as never,
        attempts, () => new Date("2026-10-28T01:00:00Z"), () => ({ ledgerKey, verify: () => {} }), fixture.authority);
      const send = vi.fn(async () => ({ delivered: "system_notification" as const }));
      const request = { sourceKey, eventId, isCurrent: () => true, send };
      expect(await coordinator.dispatch(request)).toEqual({ delivered: "source_busy" });
      expect(reserveIntent).not.toHaveBeenCalled();
      child.stdin!.end("release\n");
      expect((await once(child, "exit"))[0]).toBe(0);
      const pending = coordinator.dispatch(request);
      await vi.waitFor(() => expect(releaseSettlement).toBeTypeOf("function"));
      const probe = "import os; from core.infrastructure.reminder_source_mutex import _try_digest; h=_try_digest(os.environ['MUTEX_TEST_KEY']); print('free' if h else 'busy'); h and h.release()";
      const inspect = () => spawnSync("python", ["-c", probe], { cwd, env: { ...process.env, MUTEX_TEST_KEY: ledgerKey }, windowsHide: true, encoding: "utf8" });
      expect(inspect().stdout.trim()).toBe("busy");
      releaseSettlement();
      expect(await pending).toEqual({ delivered: "system_notification" });
      expect(inspect().stdout.trim()).toBe("free");
    } finally {
      if (child.exitCode === null) child.kill();
      rmSync(fixture.root, { recursive: true, force: true });
    }
  }, 15000);

  it("keeps an intent outcome unknown if authority changes after the intent was started", async () => {
    const ledgerKey = randomBytes(32).toString("hex"), sourceKey = randomBytes(32).toString("hex");
    let changed = false;
    const fixture = evidenceFixture();
    const stores = new LegacyReminderDailyIntentStores(fixture.authority.oldIntentDirectory);
    const reserveIntent = vi.fn(async request => { const result = await stores.forDay("20261028").reserve(request); changed = true; return result; });
    const attempts = { reserve: vi.fn(), settle: vi.fn(), abandon: vi.fn() };
    const coordinator = new LegacyReminderCoordinator({ forDay: () => ({ reserve: reserveIntent }) } as never,
      attempts, () => new Date("2026-10-28T01:00:00Z"), () => ({ ledgerKey, verify: () => {
        if (changed) throw new Error("source changed");
      } }), fixture.authority);
    const send = vi.fn();
    const request = { sourceKey, eventId: "affair-reminder:fixture:20261028", isCurrent: () => true, send };
    expect(await coordinator.dispatch(request)).toEqual({ delivered: "attempt_pending" });
    expect(reserveIntent).toHaveBeenCalledOnce();
    expect(attempts.reserve).not.toHaveBeenCalled();
    changed = false;
    expect(await coordinator.dispatch(request)).toEqual({ delivered: "source_recovery_required" });
    expect(send).not.toHaveBeenCalled();
    rmSync(fixture.root, { recursive: true, force: true });
  });
});
