import { createHash } from "node:crypto";
import { join } from "node:path";
import { AssistantProjectLifecycleRequestStore } from "../assistant/projectLifecycleRequestStore.js";
import type { DesktopHumanAttentionNotifyResult, HumanAttentionDelivery } from "./humanAttentionNotifications.js";
import { tryAcquireReminderSourceMutex, type ReminderSourceMutexLease, type ReminderSourcePermit, type VerifiedReminderLedger } from "./reminderSourceMutex.js";
import { LegacyReminderEvidenceIndex, inventoryLegacyReminderIntents, reconcileLegacyReminderEvidence } from "./legacyReminderEvidence.js";

/** All inputs come from the trusted main-process adapter, never a renderer. */
export type LegacyReminderAttemptApi = {
  reserve(request: { sourceKey: string; eventId: string }): Promise<unknown>;
  settle(request: { sourceKey: string; eventId: string; attemptToken: string; channel: HumanAttentionDelivery }): Promise<unknown>;
  abandon?(request: { sourceKey: string; eventId: string; attemptToken: string }): Promise<unknown>;
};
export type LegacyReminderCoordinatorInput = {
  sourceKey: string;
  eventId: string;
  /** Synchronous registry/document/source authority check, immediately before send. */
  isCurrent(): boolean;
  /** Must synchronously begin the main-owned notification operation. */
  send(): Promise<DesktopHumanAttentionNotifyResult>;
};
export type LegacyReminderSourceSeal = {
  /** Wait for admitted work, including reservation, delivery and settlement. */
  drain(): Promise<void>;
  /** Revalidate that this exact admission barrier remains held. */
  check(): void;
  /** Reopen this source; any pending drain then rejects instead of certifying. */
  release(): void;
};
export type LegacyReminderCooperatingSourceLease = {
  /** Revalidate the live lock, source identity and local admission barrier. */
  check(): Promise<{ schemaVersion: 1; ledgerKey: string; localCoordinatorDrained: true;
    cooperatingMutexHeld: true; priorOutcomes: "unknown"; unmanagedSenders: "unknown"; readyForCutover: false }>;
  /** Explicitly release the mutex and reopen this coordinator's admission. */
  release(): Promise<void>;
};

/** Trusted main only. Its global guard must exclude every writer of both old
 * logs and this index, including other cooperating Electron processes, for
 * its entire hold. check() must also reject uncontrolled old senders/writers.
 * Python receives inventory RPC while Electron owns the guard; Python MUST NOT
 * acquire this same mutex. Paths and source identities never come from IPC. */
export type LegacyReminderEvidenceAuthority = {
  indexDirectory: string;
  oldIntentDirectory: string;
  tryAcquireGlobal(): { check(): void; release(): void } | null;
  inventoryReceipts(): Promise<unknown>;
  /** Independently prove all prior sends for this ledger have stopped. */
  verifyRecovery(ledgerKey: string): void;
};

const channels = new Set(["assistant_window", "system_notification", "attention_fallback"]);
const sourcePattern = /^[a-f0-9]{64}$/;
const eventPattern = /^affair-reminder:[A-Za-z0-9._:-]{1,103}:[0-9]{8}$/;
const tokenPattern = /^[a-f0-9]{64}$/;
const pending = { delivered: "attempt_pending" } as const;

/** One bounded fsynced intent namespace per UTC day; old days are retained. */
export class LegacyReminderDailyIntentStores {
  private current?: { day: string; store: AssistantProjectLifecycleRequestStore };
  constructor(private readonly directory: string) {}

  forDay(day: string): Pick<AssistantProjectLifecycleRequestStore, "reserve"> {
    if (!/^[0-9]{8}$/.test(day)) throw new Error("LEGACY_REMINDER_DAY_INVALID");
    if (this.current?.day !== day) this.current = { day,
      store: new AssistantProjectLifecycleRequestStore({ directory: join(this.directory, day), maxRequests: 4096 }) };
    return this.current.store;
  }
}

/** Main calls grant only after authenticating and binding this document. */
export class LegacyReminderNegotiatedDocuments {
  private readonly documents = new WeakMap<object, "pending" | "committed">();
  private readonly legacyIngress = new WeakMap<object, Set<Promise<void>>>();

  /** Enroll synchronously before any source lookup; null means admission is closed. */
  enterLegacy(documentToken: object): (() => void) | null {
    if (this.documents.has(documentToken)) return null;
    let finish!: () => void;
    const completion = new Promise<void>(resolve => { finish = resolve; });
    let active = this.legacyIngress.get(documentToken);
    if (!active) { active = new Set(); this.legacyIngress.set(documentToken, active); }
    active.add(completion);
    let released = false;
    return () => {
      if (released) return;
      released = true;
      active!.delete(completion);
      finish();
    };
  }

  /** begin closes admission, so this waits for the complete pre-grant set. */
  async drainLegacy(documentToken: object): Promise<void> {
    if (this.documents.get(documentToken) !== "pending") throw new Error("LEGACY_REMINDER_NEGOTIATION_INVALID");
    await Promise.all([...(this.legacyIngress.get(documentToken) ?? [])]);
  }

  /** Begin synchronously before committing authority; pending is sticky on failure. */
  begin(documentToken: object): boolean {
    if (this.documents.has(documentToken)) return false;
    this.documents.set(documentToken, "pending");
    return true;
  }
  commit(documentToken: object): void {
    if (this.documents.get(documentToken) !== "pending" || this.legacyIngress.get(documentToken)?.size)
      throw new Error("LEGACY_REMINDER_NEGOTIATION_INVALID");
    this.documents.set(documentToken, "committed");
  }
  has(documentToken: object): boolean { return this.documents.has(documentToken); }
  isCommitted(documentToken: object): boolean { return this.documents.get(documentToken) === "committed"; }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function exact(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length && actual.every((key, i) => key === [...keys].sort()[i]);
}
function eventKey(sourceKey: string, eventId: string): string {
  return "legacy:" + createHash("sha256").update(JSON.stringify([sourceKey, eventId]), "ascii").digest("hex");
}
function synchronousProof(proof: () => void): void {
  if ((proof as () => unknown)() !== undefined) throw new Error("LEGACY_REMINDER_PROOF_INVALID");
}

/**
 * Use a dedicated request-store directory with one Electron-main writer.
 * Persist an intent before the private host RPC: an unknown RPC outcome or
 * a crash before the Python reservation can never become an automatic retry.
 * Existing intents intentionally return pending; they never authorize a send.
 * No source discovery, authorization, retirement or cutover is performed here.
 */
export class LegacyReminderCoordinator {
  private accepting = true;
  private readonly active = new Set<Promise<void>>();
  private readonly activeSources = new Map<string, Set<Promise<void>>>();
  private readonly sealedSources = new Set<string>();
  // Keep uncertain guards alive and admission sealed if a remote release fails.
  private readonly uncertainGuards: object[] = [];
  private readonly uncertainSources = new Set<string>();
  private async releaseGuards(sourceKey: string, permit: ReminderSourcePermit | null,
    global: ReturnType<LegacyReminderEvidenceAuthority["tryAcquireGlobal"]>, mutex: ReminderSourceMutexLease | null): Promise<void> {
    try { await permit?.release(); global?.release(); mutex?.release(); }
    catch {
      this.uncertainSources.add(sourceKey);
      this.uncertainGuards.push({ permit, global, mutex });
    }
  }
  constructor(
    private readonly intents: Pick<LegacyReminderDailyIntentStores, "forDay">,
    private readonly attempts: LegacyReminderAttemptApi,
    private readonly clock: () => Date = () => new Date(),
    /** Main-only resolver; absent preserves the legacy unnegotiated path. */
    private readonly resolveLedger?: (sourceKey: string) => VerifiedReminderLedger | null,
    private readonly evidence?: LegacyReminderEvidenceAuthority,
  ) {}

  /** Explicit trusted-main recovery. Unknown old attempts are acknowledged as
   * unknown, never declared delivered and never eligible for automatic replay. */
  async recoverSource(sourceKey: string, isCurrent: () => boolean): Promise<"recovered" | "unknown"> {
    if (!this.accepting || typeof sourceKey !== "string" || !sourcePattern.test(sourceKey)
        || this.sealedSources.has(sourceKey) || this.uncertainSources.has(sourceKey) || !this.resolveLedger || !this.evidence) return "unknown";
    let finish!: () => void;
    const completion = new Promise<void>(resolve => { finish = resolve; });
    this.active.add(completion);
    const group = this.activeSources.get(sourceKey) ?? new Set<Promise<void>>();
    group.add(completion);
    this.activeSources.set(sourceKey, group);
    try { return await this.recoverSourceAdmitted(sourceKey, isCurrent); }
    finally {
      this.active.delete(completion);
      group.delete(completion);
      if (!group.size) this.activeSources.delete(sourceKey);
      finish();
    }
  }

  private async recoverSourceAdmitted(sourceKey: string, isCurrent: () => boolean): Promise<"recovered" | "unknown"> {
    let mutex: ReminderSourceMutexLease | null = null;
    let permit: ReminderSourcePermit | null = null;
    let global: ReturnType<LegacyReminderEvidenceAuthority["tryAcquireGlobal"]> = null;
    try {
      if (isCurrent() !== true) return "unknown";
      const ledger = this.resolveLedger!(sourceKey);
      if (!ledger) return "unknown";
      if (ledger.acquirePermit) {
        permit = await ledger.acquirePermit();
        if (!permit) return "unknown";
        await permit.check();
      }
      mutex = tryAcquireReminderSourceMutex(ledger);
      if (!mutex) return "unknown";
      global = this.evidence!.tryAcquireGlobal();
      if (!global) return "unknown";
      const check = () => { mutex!.check(); synchronousProof(() => global!.check()); if (isCurrent() !== true) throw new Error("SOURCE_CHANGED"); };
      check(); await permit?.check(); check();
      const index = new LegacyReminderEvidenceIndex(this.evidence!.indexDirectory, check);
      // This marker remains unresolved if recovery aborts at any point.
      const recoveryMarker = await index.markUncertain(ledger.ledgerKey);
      await permit?.check();
      const audit = await this.auditEvidence(index, check);
      await permit?.check();
      synchronousProof(() => this.evidence!.verifyRecovery(ledger.ledgerKey));
      check();
      for (const item of audit.pending.filter(item => item.ledgerKey === ledger.ledgerKey)) {
        await permit?.check(); await index.acknowledge(item.ledgerKey, item.sourceKey, item.eventId); await permit?.check();
      }
      for (const marker of index.uncertain().filter(item => item.ledgerKey === ledger.ledgerKey && item.requestId !== recoveryMarker)) {
        await permit?.check(); await index.resolveUncertain(marker.ledgerKey, marker.requestId); await permit?.check();
      }
      synchronousProof(() => this.evidence!.verifyRecovery(ledger.ledgerKey));
      check();
      await permit?.check(); await index.resolveUncertain(ledger.ledgerKey, recoveryMarker); await permit?.check();
      return "recovered";
    } catch { return "unknown"; }
    finally { await this.releaseGuards(sourceKey, permit, global, mutex); }
  }

  private async auditEvidence(index: LegacyReminderEvidenceIndex, check: () => void) {
    const indexed = index.inventory();
    const old = inventoryLegacyReminderIntents(this.evidence!.oldIntentDirectory, check);
    const receipts = await this.evidence!.inventoryReceipts();
    check();
    return reconcileLegacyReminderEvidence(indexed, old, receipts);
  }

  /** Permanently close admission synchronously, then drain reservation, send and settlement. */
  async stopAndDrain(): Promise<void> {
    this.accepting = false;
    await Promise.all([...this.active]);
    if (this.uncertainGuards.length) throw new Error("LEGACY_REMINDER_DRAIN_UNKNOWN");
  }

  /**
   * Main-only, reversible admission barrier for an already authenticated
   * sourceKey from the same trusted adapter that calls dispatch. The caller
   * must never accept this key from a renderer or model. Enrollment and close
   * are synchronous, so an admitted dispatch is included through settlement.
   *
   * This coordinator covers neither unbound/lookup-stage ingress nor another
   * coordinator, executable, or process. A drained seal is not proof of
   * source quiescence, a delivery watermark, or permission for cutover.
   */
  sealSource(sourceKey: string): LegacyReminderSourceSeal {
    if (!this.accepting || typeof sourceKey !== "string" || !sourcePattern.test(sourceKey)
        || this.sealedSources.has(sourceKey) || this.uncertainSources.has(sourceKey) || this.sealedSources.size >= 1024)
      throw new Error("LEGACY_REMINDER_SEAL_UNAVAILABLE");
    this.sealedSources.add(sourceKey);
    let held = true;
    return {
      drain: async () => {
        if (!held) throw new Error("LEGACY_REMINDER_SEAL_RELEASED");
        await Promise.all([...(this.activeSources.get(sourceKey) ?? [])]);
        if (!held || this.uncertainSources.has(sourceKey)) throw new Error("LEGACY_REMINDER_SEAL_RELEASED");
      },
      check: () => {
        if (!held || this.uncertainSources.has(sourceKey) || !this.sealedSources.has(sourceKey)) throw new Error("LEGACY_REMINDER_SEAL_RELEASED");
      },
      release: () => {
        if (held) { held = false; this.sealedSources.delete(sourceKey); }
      },
    };
  }

  /**
   * Main-only live exclusion for one already bound source. The resolver must
   * represent the same physical ledger used by the upgraded sender and Python
   * affairs writer. The caller must separately fence lookup-stage ingress and
   * all other coordinator instances. This lease is not a global sender census,
   * receipt reconciliation, or permission to start a new reminder owner.
   *
   * It remains held until explicit release. The same mutex cannot concurrently
   * be handed to an offline Python worker: that requires a separate admission
   * barrier covering every cooperating cross-process writer across the gap.
   */
  async acquireCooperatingSourceLease(sourceKey: string): Promise<LegacyReminderCooperatingSourceLease | null> {
    if (!this.resolveLedger || !this.evidence) throw new Error("LEGACY_REMINDER_LEASE_UNAVAILABLE");
    const seal = this.sealSource(sourceKey);
    let mutex: ReminderSourceMutexLease | null = null, permit: ReminderSourcePermit | null = null;
    let transferred = false;
    try {
      await seal.drain();
      seal.check();
      const binding = this.resolveLedger(sourceKey);
      if (!binding) throw new Error("LEGACY_REMINDER_SOURCE_UNAVAILABLE");
      if (binding.acquirePermit) {
        permit = await binding.acquirePermit();
        if (!permit) throw new Error("LEGACY_REMINDER_SOURCE_UNAVAILABLE");
        await permit.check(); seal.check();
      }
      mutex = tryAcquireReminderSourceMutex(binding);
      if (!mutex) return null;
      if (mutex.abandoned) throw new Error("LEGACY_REMINDER_RECOVERY_REQUIRED");
      let held = true, releasing = false;
      const check = async () => {
        if (!held || releasing) throw new Error("LEGACY_REMINDER_LEASE_RELEASED");
        seal.check(); mutex!.check();
        await permit?.check();
        if (!held || releasing) throw new Error("LEGACY_REMINDER_LEASE_RELEASED");
        const current = this.resolveLedger!(sourceKey);
        if (!current || current.ledgerKey !== binding.ledgerKey) throw new Error("LEGACY_REMINDER_SOURCE_CHANGED");
        synchronousProof(() => current.verify());
        mutex!.check(); seal.check();
        return { schemaVersion: 1, ledgerKey: binding.ledgerKey, localCoordinatorDrained: true,
          cooperatingMutexHeld: true, priorOutcomes: "unknown", unmanagedSenders: "unknown", readyForCutover: false } as const;
      };
      await check();
      const acquired = mutex, acquiredPermit = permit;
      transferred = true;
      return Object.freeze({ check, release: async () => {
        if (!held || releasing) throw new Error("LEGACY_REMINDER_LEASE_RELEASED");
        releasing = true;
        // Preserve the seal and mutex if the remote permit release is uncertain.
        try { await acquiredPermit?.release(); acquired.release(); }
        catch (error) { this.uncertainSources.add(sourceKey); this.uncertainGuards.push({ permit: acquiredPermit, mutex: acquired, seal }); throw error; }
        held = false;
        seal.release();
      } });
    } finally {
      if (!transferred) {
        // A failed remote release cannot be treated as a drained source.
        try { await permit?.release(); mutex?.release(); seal.release(); }
        catch (error) { this.uncertainSources.add(sourceKey); this.uncertainGuards.push({ permit, mutex, seal }); throw error; }
      }
    }
  }

  async dispatch(input: LegacyReminderCoordinatorInput): Promise<DesktopHumanAttentionNotifyResult> {
    if (!this.accepting) return pending;
    // This request has not entered the durable intent or delivery path.
    if (this.sealedSources.has(input.sourceKey) || this.uncertainSources.has(input.sourceKey)) return { delivered: "source_busy" };
    let finish!: () => void;
    const completion = new Promise<void>(resolve => { finish = resolve; });
    this.active.add(completion);
    const source = input.sourceKey;
    const group = this.activeSources.get(source) ?? new Set<Promise<void>>();
    group.add(completion);
    this.activeSources.set(source, group);
    try { return await this.dispatchAdmitted(input); }
    finally {
      this.active.delete(completion);
      group.delete(completion);
      if (!group.size) this.activeSources.delete(source);
      finish();
    }
  }

  private async dispatchAdmitted(input: LegacyReminderCoordinatorInput): Promise<DesktopHumanAttentionNotifyResult> {
    const { sourceKey, eventId } = input;
    if (typeof sourceKey !== "string" || !sourcePattern.test(sourceKey) || typeof eventId !== "string"
        || eventId.length > 128 || !eventPattern.test(eventId)) return pending;
    const key = eventKey(sourceKey, eventId);
    let attemptToken: string | undefined;
    let settled = false;
    let mutex: ReminderSourceMutexLease | null = null;
    let permit: ReminderSourcePermit | null = null;
    let global: ReturnType<LegacyReminderEvidenceAuthority["tryAcquireGlobal"]> = null;
    let evidenceIndex: LegacyReminderEvidenceIndex | null = null;
    let checkEvidence: (() => void) | undefined;
    let ledgerKey: string | undefined;
    let intentStarted = false;
    try {
      const day = eventId.slice(-8);
      const now = this.clock();
      if (!(now instanceof Date) || !Number.isFinite(now.getTime())
          || now.toISOString().slice(0, 10).replaceAll("-", "") !== day) return pending;
      if (!input.isCurrent()) return this.resolveLedger ? { delivered: "source_unavailable" } : pending;
      if (this.resolveLedger) {
        if (!this.evidence) return { delivered: "source_unavailable" };
        let ledger: VerifiedReminderLedger | null;
        try {
          ledger = this.resolveLedger(sourceKey);
          if (!ledger) return { delivered: "source_unavailable" };
          if (ledger.acquirePermit) {
            permit = await ledger.acquirePermit();
            if (!permit) return { delivered: "source_unavailable" };
            await permit.check();
          }
          mutex = tryAcquireReminderSourceMutex(ledger);
          if (!mutex) return { delivered: "source_busy" };
          ledgerKey = ledger.ledgerKey;
          global = this.evidence.tryAcquireGlobal();
          if (!global) return { delivered: "source_busy" };
          const check = () => { mutex!.check(); synchronousProof(() => global!.check()); if (input.isCurrent() !== true) throw new Error("SOURCE_CHANGED"); };
          checkEvidence = check;
          check();
          evidenceIndex = new LegacyReminderEvidenceIndex(this.evidence.indexDirectory, check);
          if (mutex.abandoned) {
            await evidenceIndex.markUncertain(ledgerKey);
            return { delivered: "source_recovery_required" };
          }
          await permit?.check();
          const audit = await this.auditEvidence(evidenceIndex, check);
          await permit?.check();
          if (audit.pending.some(item => item.ledgerKey === ledgerKey)
              || evidenceIndex.uncertain().some(item => item.ledgerKey === ledgerKey)) return { delivered: "source_recovery_required" };
          // Different trusted window/source IDs can resolve to one physical
          // ledger. The original affair event must still have only one attempt.
          if (evidenceIndex.inventory().some(item => item.ledgerKey === ledgerKey && item.eventId === eventId)) return pending;
          await permit?.check();
          // Publication can succeed even when its acknowledgement is lost.
          intentStarted = true;
          if (!await evidenceIndex.begin(ledgerKey, sourceKey, eventId)) return pending;
          await permit?.check();
        } catch { return intentStarted ? pending : { delivered: "source_unavailable" }; }
        mutex.check();
        if (!input.isCurrent()) return { delivered: "source_unavailable" };
      }
      // The lifecycle request store is reused solely as a durable intent log;
      // this private namespace does not execute or authorize a project start.
      await permit?.check(); checkEvidence?.();
      intentStarted = true;
      const intent = await this.intents.forDay(day).reserve({ requestId: "legacy_" + key.slice(7),
        projectId: "legacy-reminder-source", operation: "start" });
      await permit?.check(); mutex?.check();
      checkEvidence?.();
      if (!intent.created || !input.isCurrent()) return pending;
      const reservation = await this.attempts.reserve({ sourceKey, eventId });
      if (!record(reservation) || reservation.schemaVersion !== 1 || reservation.eventKey !== key
          || reservation.state !== "reserved" || !exact(reservation, ["schemaVersion", "eventKey", "state", "attemptToken"])
          || typeof reservation.attemptToken !== "string" || !tokenPattern.test(reservation.attemptToken)) return pending;
      attemptToken = reservation.attemptToken;
      await permit?.check(); checkEvidence?.();
      mutex?.check();
      checkEvidence?.();
      if (!input.isCurrent()) return pending;
      const delivery = await input.send();
      await permit?.check(); checkEvidence?.();
      if (!record(delivery) || !channels.has(String(delivery.delivered))) return pending;
      const channel = delivery.delivered as HumanAttentionDelivery;
      const receipt = await this.attempts.settle({ sourceKey, eventId, attemptToken, channel });
      await permit?.check(); checkEvidence?.();
      if (!record(receipt) || !exact(receipt, ["schemaVersion", "eventKey", "state", "channel"])
          || receipt.schemaVersion !== 1 || receipt.eventKey !== key || receipt.state !== "submitted"
          || receipt.channel !== channel) return pending;
      settled = true;
      if (evidenceIndex && ledgerKey) { await permit?.check(); await evidenceIndex.settle(ledgerKey, sourceKey, eventId); await permit?.check(); }
      return { delivered: channel };
    } catch {
      // A failed or unknown step may have committed or submitted. Never replay.
      return this.resolveLedger && !intentStarted ? { delivered: "source_unavailable" } : pending;
    } finally {
      if (attemptToken && !settled && this.attempts.abandon) {
        // Release only this live capability; the durable uncertain attempt
        // remains and does not authorize another notification.
        try { await this.attempts.abandon({ sourceKey, eventId, attemptToken }); } catch { /* Preserve pending. */ }
      }
      await this.releaseGuards(sourceKey, permit, global, mutex);
    }
  }
}
