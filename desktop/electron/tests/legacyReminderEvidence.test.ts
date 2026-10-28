import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, expect, it, vi } from "vitest";
import { LegacyReminderEvidenceIndex, inventoryLegacyReminderIntents, mapLegacyReminderSuppressions, reconcileLegacyReminderEvidence } from "../src/notifications/legacyReminderEvidence.js";
import { createHash } from "node:crypto";
import { LegacyReminderDailyIntentStores } from "../src/notifications/legacyReminderCoordinator.js";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
const make = () => { const root = mkdtempSync(join(tmpdir(), "legacy-evidence-")); roots.push(root); return root; };

it("persists source, ledger and original event identity across days and restart", async () => {
  const root = make(), check = vi.fn(), ledger = "a".repeat(64), source = "b".repeat(64);
  const first = "affair-reminder:first:20261028", second = "affair-reminder:second:20261029";
  const index = new LegacyReminderEvidenceIndex(join(root, "index"), check);
  expect(index.inventory()).toEqual([]);
  expect(await index.begin(ledger, source, first)).toBe(true);
  expect(await index.begin(ledger, source, first)).toBe(false);
  await index.settle(ledger, source, first);
  expect(await index.begin(ledger, source, second)).toBe(true);
  const restarted = new LegacyReminderEvidenceIndex(join(root, "index"), check);
  expect(restarted.inventory().map(({ eventId, settled }) => ({ eventId, settled })))
    .toEqual([{ eventId: first, settled: true }, { eventId: second, settled: false }]);
  expect(check).toHaveBeenCalled();
});

it("inventories old logs and fails closed on unexpected or corrupt entries", async () => {
  const root = make(), check = vi.fn(), old = join(root, "old");
  expect(inventoryLegacyReminderIntents(old, check)).toEqual([]);
  const stores = new LegacyReminderDailyIntentStores(old);
  await stores.forDay("20261028").reserve({ requestId: "legacy_" + "c".repeat(64), projectId: "legacy-reminder-source", operation: "start" });
  expect(inventoryLegacyReminderIntents(old, check)).toEqual([{ day: "20261028", eventKey: "legacy:" + "c".repeat(64) }]);
  mkdirSync(join(old, "unexpected"));
  expect(() => inventoryLegacyReminderIntents(old, check)).toThrow();
  const index = new LegacyReminderEvidenceIndex(join(root, "index"), check);
  await index.begin("a".repeat(64), "b".repeat(64), "affair-reminder:item:20261028");
  const indexDay = join(root, "index", "a".repeat(64), "b".repeat(64), "20261028");
  writeFileSync(join(indexDay, "unexpected"), "bad");
  expect(() => index.inventory()).toThrow();
});

it("matches both historical logs to indexed original IDs and retains unknown outcomes", async () => {
  const root = make(), check = () => {}, ledger = "a".repeat(64), source = "b".repeat(64);
  const eventId = "affair-reminder:unknown:20261028";
  const index = new LegacyReminderEvidenceIndex(join(root, "index"), check);
  await index.begin(ledger, source, eventId);
  const indexed = index.inventory(), eventKey = indexed[0].eventKey;
  const stores = new LegacyReminderDailyIntentStores(join(root, "old"));
  await stores.forDay("20261028").reserve({ requestId: "legacy_" + eventKey.slice(7), projectId: "legacy-reminder-source", operation: "start" });
  const old = inventoryLegacyReminderIntents(join(root, "old"), check);
  const receipt = { schemaVersion: 1, records: [{ day: "20261028", eventKey, state: "pending", channel: null, inflight: true }], senders: 1 };
  expect(reconcileLegacyReminderEvidence(indexed, old, receipt)).toEqual({ pending: indexed, registeredSenders: 1 });
  expect(() => reconcileLegacyReminderEvidence([], old, receipt)).toThrow("UNMATCHED");
  expect(() => reconcileLegacyReminderEvidence(indexed, [], receipt)).toThrow("UNMATCHED");
  expect(() => reconcileLegacyReminderEvidence(indexed, old, { ...receipt, records: [...receipt.records, receipt.records[0]] })).toThrow();
  await index.settle(ledger, source, eventId);
  expect(() => reconcileLegacyReminderEvidence(index.inventory(), old, receipt)).toThrow("UNMATCHED");
  receipt.records[0] = { ...receipt.records[0], state: "submitted", channel: "system_notification", inflight: false };
  expect(reconcileLegacyReminderEvidence(index.inventory(), old, receipt).pending).toEqual([]);
});

it("maps all old submitted and unknown attempts by original item and UTC day, scoped to the physical ledger", async () => {
  const root = make(), ledger = "a".repeat(64), otherLedger = "e".repeat(64), source = "b".repeat(64), alias = "d".repeat(64);
  const guard = vi.fn(), history = vi.fn(), verify = vi.fn(), index = new LegacyReminderEvidenceIndex(join(root, "index"), guard);
  const old = join(root, "old"), stores = new LegacyReminderDailyIntentStores(old);
  for (const [key, src, id] of [[ledger, source, "affair-reminder:one:20261028"], [ledger, alias, "affair-reminder:one:20261028"],
    [ledger, source, "affair-reminder:two:20261029"], [otherLedger, source, "affair-reminder:other:20261028"]]) await index.begin(key, src, id);
  await index.settle(ledger, source, "affair-reminder:one:20261028");
  const indexed = index.inventory();
  for (const item of indexed) await stores.forDay(item.eventId.slice(-8)).reserve({ requestId: "legacy_" + item.eventKey.slice(7),
    projectId: "legacy-reminder-source", operation: "start" });
  const submitted = indexed.find(item => item.settled)!;
  const receipts = { schemaVersion: 1, records: [{ day: "20261028", eventKey: submitted.eventKey, state: "submitted",
    channel: "system_notification", inflight: false }], senders: 0 };
  const makeId = (day: string, item: string) => `reminder:${day}:` + createHash("sha256").update(item, "utf8").digest("hex");
  const args = { index, oldIntentDirectory: old, receiptInventory: receipts, ledger: { ledgerKey: ledger, verify },
    verifyGlobal: guard, verifyHistoryComplete: history };
  expect(mapLegacyReminderSuppressions(args)).toEqual({ schemaVersion: 1, ledgerKey: ledger, days: [
    { day: "20261028", eventIds: [makeId("20261028", "one")] },
    { day: "20261029", eventIds: [makeId("20261029", "two")] },
  ] });
  expect(history).toHaveBeenCalled();
  expect(() => mapLegacyReminderSuppressions({ ...args, verifyHistoryComplete: () => { throw new Error("unknown historical sender"); } })).toThrow();
  expect(() => mapLegacyReminderSuppressions({ ...args, receiptInventory: { ...receipts, records: [] } })).toThrow("UNMATCHED");
  await index.begin(ledger, source, "affair-reminder:item:with:colon:20261028");
  expect(() => mapLegacyReminderSuppressions(args)).toThrow("UNMAPPABLE");
});
