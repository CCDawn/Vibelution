import { createHash, randomBytes } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, openSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { AssistantProjectLifecycleRequestStore } from "../assistant/projectLifecycleRequestStore.js";
import type { VerifiedReminderLedger } from "./reminderSourceMutex.js";

const hex = /^[a-f0-9]{64}$/;
const dayPattern = /^[0-9]{8}$/;
const eventPattern = /^affair-reminder:[A-Za-z0-9._:-]{1,103}:([0-9]{8})$/;
const limit = 20000;
export type IndexedLegacyReminder = { ledgerKey: string; sourceKey: string; eventId: string; eventKey: string; settled: boolean; acknowledged: boolean };

function validDay(day: string): boolean {
  if (!dayPattern.test(day)) return false;
  const d = new Date(`${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6, 8)}T00:00:00Z`);
  return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10).replaceAll("-", "") === day;
}
function names(path: string, pattern: RegExp, missing = false): string[] {
  let info;
  try { info = lstatSync(path); } catch (error) {
    if (missing && (error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
  if (!info.isDirectory() || info.isSymbolicLink()) throw new Error("LEGACY_EVIDENCE_INVALID");
  const entries = readdirSync(path).sort();
  if (entries.length > limit || entries.some(name => !pattern.test(name))) throw new Error("LEGACY_EVIDENCE_INVALID");
  const after = lstatSync(path);
  if (info.dev !== after.dev || info.ino !== after.ino || info.mtimeMs !== after.mtimeMs
      || !after.isDirectory() || after.isSymbolicLink()) throw new Error("LEGACY_EVIDENCE_CHANGED");
  return entries;
}
function eventKey(sourceKey: string, eventId: string): string {
  return "legacy:" + createHash("sha256").update(JSON.stringify([sourceKey, eventId]), "ascii").digest("hex");
}
function fileName(id: string): string { return createHash("sha256").update(id, "utf8").digest("hex") + ".json"; }

/** Read only after the existing store has validated every record and ancestor.
 * The caller holds the global writer barrier across this entire synchronous scan. */
function rows(path: string): Array<{ requestId: string; projectId: string; operation: string }> {
  const entries = names(path, /^[a-f0-9]{64}\.json$/);
  new AssistantProjectLifecycleRequestStore({ directory: path, maxRequests: 4096 });
  const result = entries.map(name => {
    const full = join(path, name), before = lstatSync(full);
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.size < 1 || before.size > 16384)
      throw new Error("LEGACY_EVIDENCE_INVALID");
    const fd = openSync(full, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
    let bytes: Buffer;
    try {
      const opened = fstatSync(fd);
      if (opened.dev !== before.dev || opened.ino !== before.ino || opened.nlink !== 1 || opened.size !== before.size)
        throw new Error("LEGACY_EVIDENCE_CHANGED");
      bytes = readFileSync(fd);
      const after = fstatSync(fd), pathAfter = lstatSync(full);
      if (bytes.length !== before.size || before.dev !== after.dev || before.ino !== after.ino
          || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs || after.nlink !== 1
          || pathAfter.dev !== before.dev || pathAfter.ino !== before.ino || pathAfter.isSymbolicLink())
        throw new Error("LEGACY_EVIDENCE_CHANGED");
    } finally { closeSync(fd); }
    const row = JSON.parse(bytes.toString("utf8"));
    if (!row?.request || typeof row.request.requestId !== "string" || fileName(row.request.requestId) !== name)
      throw new Error("LEGACY_EVIDENCE_INVALID");
    return row.request;
  });
  if (JSON.stringify(names(path, /^[a-f0-9]{64}\.json$/)) !== JSON.stringify(entries))
    throw new Error("LEGACY_EVIDENCE_CHANGED");
  return result;
}

/** Main owns the global cross-process writer barrier and each ledger mutex.
 * Never pass this object or any identity to a renderer. Index entries precede
 * the old intent and all RPCs. Existing opaque records require matching here. */
export class LegacyReminderEvidenceIndex {
  constructor(private readonly directory: string, private readonly checkBarrier: () => void) {}

  private validate(ledgerKey: string, sourceKey: string, eventId: string): string {
    const match = typeof eventId === "string" && eventPattern.exec(eventId);
    if (!hex.test(ledgerKey) || !hex.test(sourceKey) || !match || !validDay(match[1]))
      throw new Error("LEGACY_EVIDENCE_INVALID");
    return match[1];
  }
  async begin(ledgerKey: string, sourceKey: string, eventId: string): Promise<boolean> {
    const day = this.validate(ledgerKey, sourceKey, eventId);
    this.checkBarrier();
    const store = new AssistantProjectLifecycleRequestStore({ directory: join(this.directory, ledgerKey, sourceKey, day, "intents"), maxRequests: 4096 });
    const result = await store.reserve({ requestId: eventId, projectId: sourceKey, operation: "start" });
    this.checkBarrier();
    return result.created;
  }
  async settle(ledgerKey: string, sourceKey: string, eventId: string): Promise<void> {
    const day = this.validate(ledgerKey, sourceKey, eventId);
    this.checkBarrier();
    const path = join(this.directory, ledgerKey, sourceKey, day, "intents");
    names(path, /^[a-f0-9]{64}\.json$/);
    const intents = new AssistantProjectLifecycleRequestStore({ directory: path, maxRequests: 4096 });
    const existing = await intents.get(eventId);
    if (!existing || existing.request.projectId !== sourceKey || existing.request.operation !== "start")
      throw new Error("LEGACY_EVIDENCE_INVALID");
    const store = new AssistantProjectLifecycleRequestStore({ directory: join(this.directory, ledgerKey, sourceKey, day, "settled"), maxRequests: 4096 });
    await store.reserve({ requestId: eventId, projectId: sourceKey, operation: "start" });
    this.checkBarrier();
  }

  /** Called only by the trusted recovery operation after complete evidence review. */
  async acknowledge(ledgerKey: string, sourceKey: string, eventId: string): Promise<void> {
    const day = this.validate(ledgerKey, sourceKey, eventId);
    this.checkBarrier();
    const path = join(this.directory, ledgerKey, sourceKey, day, "intents");
    names(path, /^[a-f0-9]{64}\.json$/);
    const existing = await new AssistantProjectLifecycleRequestStore({ directory: path, maxRequests: 4096 }).get(eventId);
    if (!existing || existing.request.projectId !== sourceKey || existing.request.operation !== "start")
      throw new Error("LEGACY_EVIDENCE_INVALID");
    const store = new AssistantProjectLifecycleRequestStore({ directory: join(this.directory, ledgerKey, sourceKey, day, "acknowledged"), maxRequests: 4096 });
    await store.reserve({ requestId: eventId, projectId: sourceKey, operation: "start" });
    this.checkBarrier();
  }

  async markUncertain(ledgerKey: string): Promise<string> {
    if (!hex.test(ledgerKey)) throw new Error("LEGACY_EVIDENCE_INVALID");
    this.checkBarrier();
    const store = new AssistantProjectLifecycleRequestStore({ directory: join(`${this.directory}.uncertain`, ledgerKey, "markers"), maxRequests: 4096 });
    const requestId = `uncertain_${randomBytes(32).toString("hex")}`;
    await store.reserve({ requestId, projectId: ledgerKey, operation: "start" });
    this.checkBarrier();
    return requestId;
  }

  uncertain(): Array<{ ledgerKey: string; requestId: string }> {
    this.checkBarrier();
    const result: Array<{ ledgerKey: string; requestId: string }> = [];
    const root = `${this.directory}.uncertain`;
    for (const ledgerKey of names(root, hex, true)) {
      const path = join(root, ledgerKey), children = names(path, /^(markers|resolved)$/);
      if (!children.includes("markers")) throw new Error("LEGACY_EVIDENCE_INVALID");
      const checkRow = (row: { requestId: string; projectId: string; operation: string }) => {
        if (row.projectId !== ledgerKey || row.operation !== "start" || !/^uncertain_[a-f0-9]{64}$/.test(row.requestId))
          throw new Error("LEGACY_EVIDENCE_INVALID");
        return row.requestId;
      };
      const resolved = new Set(children.includes("resolved") ? rows(join(path, "resolved")).map(checkRow) : []);
      for (const row of rows(join(path, "markers"))) {
        const requestId = checkRow(row);
        if (!resolved.delete(requestId)) result.push({ ledgerKey, requestId });
        if (result.length > limit) throw new Error("LEGACY_EVIDENCE_LIMIT");
      }
      if (resolved.size) throw new Error("LEGACY_EVIDENCE_INVALID");
    }
    this.checkBarrier();
    return result;
  }

  async resolveUncertain(ledgerKey: string, requestId: string): Promise<void> {
    if (!hex.test(ledgerKey) || !/^uncertain_[a-f0-9]{64}$/.test(requestId)) throw new Error("LEGACY_EVIDENCE_INVALID");
    this.checkBarrier();
    const base = join(`${this.directory}.uncertain`, ledgerKey);
    names(join(base, "markers"), /^[a-f0-9]{64}\.json$/);
    const original = await new AssistantProjectLifecycleRequestStore({ directory: join(base, "markers"), maxRequests: 4096 }).get(requestId);
    if (!original || original.request.projectId !== ledgerKey || original.request.operation !== "start") throw new Error("LEGACY_EVIDENCE_INVALID");
    await new AssistantProjectLifecycleRequestStore({ directory: join(base, "resolved"), maxRequests: 4096 })
      .reserve({ requestId, projectId: ledgerKey, operation: "start" });
    this.checkBarrier();
  }

  inventory(): IndexedLegacyReminder[] {
    this.checkBarrier();
    const result: IndexedLegacyReminder[] = [];
    for (const ledgerKey of names(this.directory, hex, true))
      for (const sourceKey of names(join(this.directory, ledgerKey), hex))
        for (const day of names(join(this.directory, ledgerKey, sourceKey), dayPattern)) {
          if (!validDay(day)) throw new Error("LEGACY_EVIDENCE_INVALID");
          const base = join(this.directory, ledgerKey, sourceKey, day);
          const children = names(base, /^(intents|settled|acknowledged)$/);
          if (!children.includes("intents")) throw new Error("LEGACY_EVIDENCE_INVALID");
          const settled = new Set(children.includes("settled") ? rows(join(base, "settled")).map(row => {
            if (row.projectId !== sourceKey || row.operation !== "start") throw new Error("LEGACY_EVIDENCE_INVALID");
            return row.requestId;
          }) : []);
          const acknowledged = new Set(children.includes("acknowledged") ? rows(join(base, "acknowledged")).map(row => {
            if (row.projectId !== sourceKey || row.operation !== "start") throw new Error("LEGACY_EVIDENCE_INVALID");
            return row.requestId;
          }) : []);
          for (const row of rows(join(base, "intents"))) {
            if (row.projectId !== sourceKey || row.operation !== "start" || this.validate(ledgerKey, sourceKey, row.requestId) !== day)
              throw new Error("LEGACY_EVIDENCE_INVALID");
            result.push({ ledgerKey, sourceKey, eventId: row.requestId, eventKey: eventKey(sourceKey, row.requestId),
              settled: settled.delete(row.requestId), acknowledged: acknowledged.delete(row.requestId) });
            if (result.length > limit) throw new Error("LEGACY_EVIDENCE_LIMIT");
          }
          if (settled.size || acknowledged.size) throw new Error("LEGACY_EVIDENCE_INVALID");
        }
    this.checkBarrier();
    return result;
  }
}

/** Enumerate the original Electron log; callers must correlate every row. */
export function inventoryLegacyReminderIntents(directory: string, checkBarrier: () => void): Array<{ day: string; eventKey: string }> {
  checkBarrier();
  const result: Array<{ day: string; eventKey: string }> = [];
  for (const day of names(directory, dayPattern, true)) {
    if (!validDay(day)) throw new Error("LEGACY_EVIDENCE_INVALID");
    for (const row of rows(join(directory, day))) {
      if (row.projectId !== "legacy-reminder-source" || row.operation !== "start" || !/^legacy_[a-f0-9]{64}$/.test(row.requestId))
        throw new Error("LEGACY_EVIDENCE_INVALID");
      result.push({ day, eventKey: "legacy:" + row.requestId.slice(7) });
      if (result.length > limit) throw new Error("LEGACY_EVIDENCE_LIMIT");
    }
  }
  checkBarrier();
  return result;
}

type ReceiptRow = { day: string; eventKey: string; state: "pending" | "submitted" | "opened";
  channel: "assistant_window" | "system_notification" | "attention_fallback" | null; inflight: boolean };
/** Verify complete inventories; unknown attempts remain unknown and are never replayed.
 * This is evidence matching, not proof that a sender stopped or a person saw a notification. */
export function reconcileLegacyReminderEvidence(index: IndexedLegacyReminder[], old: Array<{ day: string; eventKey: string }>,
  receiptInventory: unknown): { pending: IndexedLegacyReminder[]; registeredSenders: number } {
  if (!receiptInventory || typeof receiptInventory !== "object" || Array.isArray(receiptInventory)) throw new Error("LEGACY_EVIDENCE_INVALID");
  const value = receiptInventory as Record<string, unknown>;
  if (Object.keys(value).sort().join(",") !== "records,schemaVersion,senders" || value.schemaVersion !== 1
      || !Array.isArray(value.records) || value.records.length > limit || !Number.isSafeInteger(value.senders)
      || (value.senders as number) < 0) throw new Error("LEGACY_EVIDENCE_INVALID");
  const byKey = new Map<string, IndexedLegacyReminder>();
  for (const item of index) {
    const match = eventPattern.exec(item.eventId);
    if (!match || !validDay(match[1]) || !hex.test(item.ledgerKey) || !hex.test(item.sourceKey)
        || item.eventKey !== eventKey(item.sourceKey, item.eventId) || typeof item.settled !== "boolean" || typeof item.acknowledged !== "boolean"
        || byKey.has(item.eventKey)) throw new Error("LEGACY_EVIDENCE_INVALID");
    byKey.set(item.eventKey, item);
  }
  const oldKeys = new Set<string>();
  for (const row of old) {
    const indexed = byKey.get(row.eventKey);
    if (!indexed || indexed.eventId.slice(-8) !== row.day || oldKeys.has(row.eventKey))
      throw new Error("LEGACY_EVIDENCE_UNMATCHED");
    oldKeys.add(row.eventKey);
  }
  const receipts = new Map<string, ReceiptRow>();
  for (const raw of value.records) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("LEGACY_EVIDENCE_INVALID");
    const row = raw as ReceiptRow;
    if (Object.keys(row).sort().join(",") !== "channel,day,eventKey,inflight,state" || typeof row.day !== "string"
        || typeof row.eventKey !== "string" || !validDay(row.day) || typeof row.inflight !== "boolean"
        || !["pending", "submitted", "opened"].includes(row.state)
        || (row.state === "pending" ? row.channel !== null : !["assistant_window", "system_notification", "attention_fallback"].includes(row.channel ?? ""))
        || receipts.has(row.eventKey)) throw new Error("LEGACY_EVIDENCE_INVALID");
    const indexed = byKey.get(row.eventKey);
    if (!indexed || indexed.eventId.slice(-8) !== row.day || !oldKeys.has(row.eventKey))
      throw new Error("LEGACY_EVIDENCE_UNMATCHED");
    receipts.set(row.eventKey, row);
  }
  for (const item of index) {
    const receipt = receipts.get(item.eventKey);
    if (item.settled && (!oldKeys.has(item.eventKey) || !receipt || receipt.state === "pending" || receipt.inflight))
      throw new Error("LEGACY_EVIDENCE_UNMATCHED");
  }
  return { pending: index.filter(item => !item.settled && !item.acknowledged), registeredSenders: value.senders as number };
}

/** Trusted main-only plan. Persist every mapped ID as unknown on the target;
 * neither settlement nor acknowledgement is a claim that the user saw it. */
export function mapLegacyReminderSuppressions(input: {
  index: LegacyReminderEvidenceIndex;
  oldIntentDirectory: string;
  receiptInventory: unknown;
  ledger: VerifiedReminderLedger;
  /** Current global single-writer guard, held during both inventories. */
  verifyGlobal(): void;
  /** Independent proof that historical/unnegotiated sender evidence is complete. */
  verifyHistoryComplete(): void;
}): { schemaVersion: 1; ledgerKey: string; days: Array<{ day: string; eventIds: string[] }> } {
  if (!input || !input.index || !input.ledger || typeof input.ledger.ledgerKey !== "string"
      || !hex.test(input.ledger.ledgerKey) || typeof input.ledger.verify !== "function"
      || typeof input.verifyGlobal !== "function" || typeof input.verifyHistoryComplete !== "function")
    throw new Error("LEGACY_EVIDENCE_INVALID");
  const ledgerKey = input.ledger.ledgerKey;
  const check = () => {
    if ((input.ledger.verify as () => unknown)() !== undefined || input.ledger.ledgerKey !== ledgerKey
        || (input.verifyGlobal as () => unknown)() !== undefined
        || (input.verifyHistoryComplete as () => unknown)() !== undefined)
      throw new Error("LEGACY_EVIDENCE_UNAVAILABLE");
  };
  check();
  const indexed = input.index.inventory();
  const old = inventoryLegacyReminderIntents(input.oldIntentDirectory, check);
  reconcileLegacyReminderEvidence(indexed, old, input.receiptInventory);
  const byDay = new Map<string, Set<string>>();
  for (const item of indexed) {
    if (item.ledgerKey !== ledgerKey) continue;
    const match = /^affair-reminder:([A-Za-z0-9][A-Za-z0-9._-]{0,159}):([0-9]{8})$/.exec(item.eventId);
    if (!match || !validDay(match[2])) throw new Error("LEGACY_EVIDENCE_UNMAPPABLE");
    const ids = byDay.get(match[2]) ?? new Set<string>();
    ids.add("reminder:" + match[2] + ":" + createHash("sha256").update(match[1], "utf8").digest("hex"));
    if (ids.size > 4096) throw new Error("LEGACY_EVIDENCE_LIMIT");
    byDay.set(match[2], ids);
  }
  check();
  return { schemaVersion: 1, ledgerKey, days: [...byDay].sort(([a], [b]) => a.localeCompare(b))
    .map(([day, ids]) => ({ day, eventIds: [...ids].sort() })) };
}
