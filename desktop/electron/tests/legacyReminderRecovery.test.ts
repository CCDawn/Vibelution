import { createHash } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";

const mocked = vi.hoisted(() => ({ acquire: vi.fn() }));
vi.mock("../src/notifications/reminderSourceMutex.js", () => ({ tryAcquireReminderSourceMutex: mocked.acquire }));
import { LegacyReminderCoordinator, LegacyReminderDailyIntentStores } from "../src/notifications/legacyReminderCoordinator.js";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); vi.clearAllMocks(); });

it("persists uncertainty and only acknowledges old unknown events after explicit verified recovery", async () => {
  const root = mkdtempSync(join(tmpdir(), "reminder-recovery-")); roots.push(root);
  const sourceKey = "a".repeat(64), ledgerKey = "b".repeat(64), token = "c".repeat(64);
  const priorId = "affair-reminder:prior:20261028", newId = "affair-reminder:new:20261028";
  const clock = () => new Date("2026-10-28T01:00:00Z");
  const eventKey = (id: string) => "legacy:" + createHash("sha256").update(JSON.stringify([sourceKey, id]), "ascii").digest("hex");
  const records: Array<{ day: string; eventKey: string; state: string; channel: string; inflight: boolean }> = [];
  const attempts = {
    reserve: vi.fn(async (request: { eventId: string }) => {
      if (request.eventId === priorId) throw new Error("unknown reserve");
      return { schemaVersion: 1, eventKey: eventKey(request.eventId), state: "reserved", attemptToken: token };
    }),
    settle: vi.fn(async (request: { eventId: string }) => {
      records.push({ day: "20261028", eventKey: eventKey(request.eventId), state: "submitted", channel: "system_notification", inflight: false });
      return { schemaVersion: 1, eventKey: eventKey(request.eventId), state: "submitted", channel: "system_notification" };
    }),
    abandon: vi.fn(),
  };
  let proof = false, globalHeld = false, abandoned = false, failSecondProof = false, proofCalls = 0;
  const resolver = () => ({ ledgerKey, verify: () => {} });
  mocked.acquire.mockImplementation(binding => ({ abandoned, check: binding.verify, release: () => {} }));
  const authority = {
    indexDirectory: join(root, "index"), oldIntentDirectory: join(root, "old"),
    tryAcquireGlobal: () => {
      if (globalHeld) return null;
      globalHeld = true;
      return { check: () => { if (!globalHeld) throw new Error("guard lost"); }, release: () => { globalHeld = false; } };
    },
    inventoryReceipts: async () => ({ schemaVersion: 1, records: [...records], senders: 0 }),
    verifyRecovery: () => { if (!proof || (failSecondProof && ++proofCalls === 2)) throw new Error("uncontrolled sender"); },
  };
  const make = () => new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(authority.oldIntentDirectory), attempts, clock, resolver, authority);
  const send = vi.fn(async () => ({ delivered: "system_notification" as const }));
  const request = (eventId: string) => ({ sourceKey, eventId, isCurrent: () => true, send });
  const first = make();
  expect(await first.dispatch(request(priorId))).toEqual({ delivered: "attempt_pending" });
  expect(await first.dispatch(request(newId))).toEqual({ delivered: "source_recovery_required" });
  expect(await first.recoverSource(sourceKey, () => true)).toBe("unknown");
  const restarted = make();
  expect(await restarted.dispatch(request(newId))).toEqual({ delivered: "source_recovery_required" });
  proof = true;
  failSecondProof = true;
  expect(await restarted.recoverSource(sourceKey, () => true)).toBe("unknown");
  expect(await make().dispatch(request(newId))).toEqual({ delivered: "source_recovery_required" });
  failSecondProof = false;
  expect(await restarted.recoverSource(sourceKey, () => true)).toBe("recovered");
  expect(await make().dispatch(request(priorId))).toEqual({ delivered: "attempt_pending" });
  expect(await restarted.dispatch({ ...request(priorId), sourceKey: "d".repeat(64) })).toEqual({ delivered: "attempt_pending" });
  expect(await restarted.dispatch(request(newId))).toEqual({ delivered: "system_notification" });
  expect(send).toHaveBeenCalledOnce();
  abandoned = true;
  expect(await restarted.dispatch(request("affair-reminder:later:20261028"))).toEqual({ delivered: "source_recovery_required" });
  abandoned = false;
  expect(await make().dispatch(request("affair-reminder:later:20261028"))).toEqual({ delivered: "source_recovery_required" });
  expect(await make().recoverSource(sourceKey, () => true)).toBe("recovered");
}, 20_000);

it("retains an index-only interrupted event across restart and never replays it", async () => {
  const root = mkdtempSync(join(tmpdir(), "reminder-index-only-")); roots.push(root);
  const sourceKey = "a".repeat(64), ledgerKey = "b".repeat(64), old = join(root, "old");
  mocked.acquire.mockImplementation(binding => ({ abandoned: false, check: binding.verify, release: () => {} }));
  const attempts = { reserve: vi.fn(), settle: vi.fn() }, send = vi.fn();
  const authority = { indexDirectory: join(root, "index"), oldIntentDirectory: old,
    tryAcquireGlobal: () => ({ check: () => {}, release: () => {} }),
    inventoryReceipts: async () => ({ schemaVersion: 1, records: [], senders: 0 }), verifyRecovery: () => {} };
  const resolver = () => ({ ledgerKey, verify: () => {} }), clock = () => new Date("2026-10-28T01:00:00Z");
  const failing = { forDay: () => ({ reserve: async () => { throw new Error("interrupted old intent"); } }) };
  const request = { sourceKey, eventId: "affair-reminder:original:20261028", isCurrent: () => true, send };
  expect(await new LegacyReminderCoordinator(failing as never, attempts, clock, resolver, authority).dispatch(request)).toEqual({ delivered: "attempt_pending" });
  const restarted = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(old), attempts, clock, resolver, authority);
  expect(await restarted.dispatch(request)).toEqual({ delivered: "source_recovery_required" });
  expect(await restarted.recoverSource(sourceKey, () => true)).toBe("recovered");
  expect(await restarted.dispatch(request)).toEqual({ delivered: "attempt_pending" });
  expect(attempts.reserve).not.toHaveBeenCalled();
  expect(send).not.toHaveBeenCalled();
});

it("refuses unindexed historical intents and leaves new events unsent", async () => {
  const root = mkdtempSync(join(tmpdir(), "reminder-unmatched-")); roots.push(root);
  const sourceKey = "a".repeat(64), ledgerKey = "b".repeat(64), old = join(root, "old");
  await new LegacyReminderDailyIntentStores(old).forDay("20261028").reserve({ requestId: "legacy_" + "e".repeat(64), projectId: "legacy-reminder-source", operation: "start" });
  mocked.acquire.mockImplementation(binding => ({ abandoned: false, check: binding.verify, release: () => {} }));
  const guard = { check: () => {}, release: () => {} };
  const attempts = { reserve: vi.fn(), settle: vi.fn() }, send = vi.fn();
  const coordinator = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(old), attempts, () => new Date("2026-10-28T01:00:00Z"),
    () => ({ ledgerKey, verify: () => {} }), { indexDirectory: join(root, "index"), oldIntentDirectory: old,
      tryAcquireGlobal: () => guard, inventoryReceipts: async () => ({ schemaVersion: 1, records: [], senders: 0 }), verifyRecovery: () => {} });
  expect(await coordinator.dispatch({ sourceKey, eventId: "affair-reminder:new:20261028", isCurrent: () => true, send }))
    .toEqual({ delivered: "source_unavailable" });
  expect(await coordinator.recoverSource(sourceKey, () => true)).toBe("unknown");
  expect(attempts.reserve).not.toHaveBeenCalled();
  expect(send).not.toHaveBeenCalled();
});

it("includes explicit recovery in a source seal and shutdown drain", async () => {
  const root = mkdtempSync(join(tmpdir(), "reminder-recovery-drain-")); roots.push(root);
  const sourceKey = "a".repeat(64), ledgerKey = "b".repeat(64), old = join(root, "old");
  mocked.acquire.mockImplementation(binding => ({ abandoned: false, check: binding.verify, release: () => {} }));
  let resume!: (value: unknown) => void;
  const authority = { indexDirectory: join(root, "index"), oldIntentDirectory: old,
    tryAcquireGlobal: () => ({ check: () => {}, release: () => {} }),
    inventoryReceipts: () => new Promise(resolve => { resume = resolve; }), verifyRecovery: () => {} };
  const coordinator = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(old), { reserve: vi.fn(), settle: vi.fn() },
    () => new Date("2026-10-28T01:00:00Z"), () => ({ ledgerKey, verify: () => {} }), authority);
  const recovery = coordinator.recoverSource(sourceKey, () => true);
  await vi.waitFor(() => expect(resume).toBeTypeOf("function"));
  const seal = coordinator.sealSource(sourceKey);
  let drained = false;
  const waiting = seal.drain().then(() => { drained = true; });
  const stopping = coordinator.stopAndDrain();
  await Promise.resolve();
  expect(drained).toBe(false);
  expect(await coordinator.recoverSource(sourceKey, () => true)).toBe("unknown");
  resume({ schemaVersion: 1, records: [], senders: 0 });
  expect(await recovery).toBe("recovered");
  await waiting;
  await stopping;
  expect(drained).toBe(true);
  seal.release();
});

it.each(["reserve", "send", "settle"])("rechecks the global guard after %s and retains unknown evidence", async stage => {
  const root = mkdtempSync(join(tmpdir(), "reminder-guard-loss-")); roots.push(root);
  const sourceKey = "a".repeat(64), ledgerKey = "b".repeat(64), token = "c".repeat(64);
  const eventId = "affair-reminder:fixture:20261028";
  const eventKey = "legacy:" + createHash("sha256").update(JSON.stringify([sourceKey, eventId]), "ascii").digest("hex");
  let valid = true;
  const records: Array<{ day: string; eventKey: string; state: string; channel: string; inflight: boolean }> = [];
  const attempts = {
    reserve: vi.fn(async () => { if (stage === "reserve") valid = false; return { schemaVersion: 1, eventKey, state: "reserved", attemptToken: token }; }),
    settle: vi.fn(async () => { records.push({ day: "20261028", eventKey, state: "submitted", channel: "system_notification", inflight: false });
      if (stage === "settle") valid = false; return { schemaVersion: 1, eventKey, state: "submitted", channel: "system_notification" }; }),
    abandon: vi.fn(async () => ({})),
  };
  mocked.acquire.mockImplementation(binding => ({ abandoned: false, check: binding.verify, release: () => {} }));
  const authority = { indexDirectory: join(root, "index"), oldIntentDirectory: join(root, "old"),
    tryAcquireGlobal: () => ({ check: () => { if (!valid) throw new Error("global authority revoked"); }, release: () => {} }),
    inventoryReceipts: async () => ({ schemaVersion: 1, records, senders: 0 }), verifyRecovery: () => {} };
  const make = () => new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(authority.oldIntentDirectory), attempts,
    () => new Date("2026-10-28T01:00:00Z"), () => ({ ledgerKey, verify: () => {} }), authority);
  const send = vi.fn(async () => { if (stage === "send") valid = false; return { delivered: "system_notification" as const }; });
  expect(await make().dispatch({ sourceKey, eventId, isCurrent: () => true, send })).toEqual({ delivered: "attempt_pending" });
  expect(send).toHaveBeenCalledTimes(stage === "reserve" ? 0 : 1);
  expect(attempts.settle).toHaveBeenCalledTimes(stage === "settle" ? 1 : 0);
  expect(attempts.abandon).toHaveBeenCalledOnce();
  valid = true;
  expect(await make().dispatch({ sourceKey, eventId, isCurrent: () => true, send })).toEqual({ delivered: "source_recovery_required" });
});


it.each(["reserve", "send", "settle"])("holds and rechecks an asynchronous source permit around %s", async stage => {
  const root = mkdtempSync(join(tmpdir(), "reminder-async-permit-")); roots.push(root);
  const sourceKey = "a".repeat(64), ledgerKey = "b".repeat(64), token = "c".repeat(64);
  const eventId = "affair-reminder:fixture:20261028";
  const eventKey = "legacy:" + createHash("sha256").update(JSON.stringify([sourceKey, eventId]), "ascii").digest("hex");
  let valid = true, held = false;
  const permit = { check: vi.fn(async () => { if (!held || !valid) throw new Error("permit revoked"); }),
    release: vi.fn(async () => { held = false; }) };
  const attempts = {
    reserve: vi.fn(async () => { expect(held).toBe(true); if (stage === "reserve") valid = false;
      return { schemaVersion: 1, eventKey, state: "reserved", attemptToken: token }; }),
    settle: vi.fn(async () => { expect(held).toBe(true); if (stage === "settle") valid = false;
      return { schemaVersion: 1, eventKey, state: "submitted", channel: "system_notification" }; }),
    abandon: vi.fn(async () => ({})),
  };
  mocked.acquire.mockImplementation(binding => ({ abandoned: false, check: binding.verify, release: () => {} }));
  const authority = { indexDirectory: join(root, "index"), oldIntentDirectory: join(root, "old"),
    tryAcquireGlobal: () => ({ check: () => {}, release: () => {} }),
    inventoryReceipts: async () => ({ schemaVersion: 1, records: [], senders: 0 }), verifyRecovery: () => {} };
  const coordinator = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(authority.oldIntentDirectory), attempts,
    () => new Date("2026-10-28T01:00:00Z"), () => ({ ledgerKey, verify: () => {}, acquirePermit: async () => { held = true; return permit; } }), authority);
  const send = vi.fn(async () => { expect(held).toBe(true); if (stage === "send") valid = false;
    return { delivered: "system_notification" as const }; });
  expect(await coordinator.dispatch({ sourceKey, eventId, isCurrent: () => true, send })).toEqual({ delivered: "attempt_pending" });
  expect(send).toHaveBeenCalledTimes(stage === "reserve" ? 0 : 1);
  expect(attempts.settle).toHaveBeenCalledTimes(stage === "settle" ? 1 : 0);
  expect(permit.release).toHaveBeenCalledOnce();
  expect(held).toBe(false);
});


it("keeps source admission sealed if releasing the host permit has an unknown outcome", async () => {
  const root = mkdtempSync(join(tmpdir(), "reminder-permit-release-")); roots.push(root);
  const sourceKey = "a".repeat(64), ledgerKey = "b".repeat(64);
  const permit = { check: async () => {}, release: vi.fn(async () => { throw new Error("release unknown"); }) };
  mocked.acquire.mockImplementation(binding => ({ abandoned: false, check: binding.verify, release: vi.fn() }));
  const guard = { check: () => {}, release: vi.fn() };
  const authority = { indexDirectory: join(root, "index"), oldIntentDirectory: join(root, "old"),
    tryAcquireGlobal: () => guard, inventoryReceipts: async () => ({ schemaVersion: 1, records: [], senders: 0 }), verifyRecovery: () => {} };
  const coordinator = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(authority.oldIntentDirectory),
    { reserve: vi.fn(async () => { throw new Error("unknown"); }), settle: vi.fn() },
    () => new Date("2026-10-28T01:00:00Z"), () => ({ ledgerKey, verify: () => {}, acquirePermit: async () => permit }), authority);
  const request = { sourceKey, eventId: "affair-reminder:fixture:20261028", isCurrent: () => true,
    send: vi.fn(async () => ({ delivered: "system_notification" as const })) };
  expect(await coordinator.dispatch(request)).toEqual({ delivered: "attempt_pending" });
  expect(permit.release).toHaveBeenCalledOnce();
  expect(guard.release).not.toHaveBeenCalled();
  expect(await coordinator.dispatch(request)).toEqual({ delivered: "source_busy" });
  expect(() => coordinator.sealSource(sourceKey)).toThrow("LEGACY_REMINDER_SEAL_UNAVAILABLE");
  await expect(coordinator.stopAndDrain()).rejects.toThrow("LEGACY_REMINDER_DRAIN_UNKNOWN");
});
