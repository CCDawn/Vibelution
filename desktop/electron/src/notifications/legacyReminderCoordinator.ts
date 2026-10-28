import { createHash } from "node:crypto";
import { join } from "node:path";
import { AssistantProjectLifecycleRequestStore } from "../assistant/projectLifecycleRequestStore.js";
import type { DesktopHumanAttentionNotifyResult, HumanAttentionDelivery } from "./humanAttentionNotifications.js";

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
  constructor(
    private readonly intents: Pick<LegacyReminderDailyIntentStores, "forDay">,
    private readonly attempts: LegacyReminderAttemptApi,
    private readonly clock: () => Date = () => new Date(),
  ) {}

  /** Permanently close admission synchronously, then drain reservation, send and settlement. */
  async stopAndDrain(): Promise<void> {
    this.accepting = false;
    await Promise.all([...this.active]);
  }

  async dispatch(input: LegacyReminderCoordinatorInput): Promise<DesktopHumanAttentionNotifyResult> {
    if (!this.accepting) return pending;
    let finish!: () => void;
    const completion = new Promise<void>(resolve => { finish = resolve; });
    this.active.add(completion);
    try { return await this.dispatchAdmitted(input); }
    finally { this.active.delete(completion); finish(); }
  }

  private async dispatchAdmitted(input: LegacyReminderCoordinatorInput): Promise<DesktopHumanAttentionNotifyResult> {
    const { sourceKey, eventId } = input;
    if (typeof sourceKey !== "string" || !sourcePattern.test(sourceKey) || typeof eventId !== "string"
        || eventId.length > 128 || !eventPattern.test(eventId)) return pending;
    const key = eventKey(sourceKey, eventId);
    let attemptToken: string | undefined;
    let settled = false;
    try {
      const day = eventId.slice(-8);
      const now = this.clock();
      if (!(now instanceof Date) || !Number.isFinite(now.getTime())
          || now.toISOString().slice(0, 10).replaceAll("-", "") !== day) return pending;
      if (!input.isCurrent()) return pending;
      // The lifecycle request store is reused solely as a durable intent log;
      // this private namespace does not execute or authorize a project start.
      const intent = await this.intents.forDay(day).reserve({ requestId: "legacy_" + key.slice(7),
        projectId: "legacy-reminder-source", operation: "start" });
      if (!intent.created || !input.isCurrent()) return pending;
      const reservation = await this.attempts.reserve({ sourceKey, eventId });
      if (!record(reservation) || reservation.schemaVersion !== 1 || reservation.eventKey !== key
          || reservation.state !== "reserved" || !exact(reservation, ["schemaVersion", "eventKey", "state", "attemptToken"])
          || typeof reservation.attemptToken !== "string" || !tokenPattern.test(reservation.attemptToken)) return pending;
      attemptToken = reservation.attemptToken;
      if (!input.isCurrent()) return pending;
      const delivery = await input.send();
      if (!record(delivery) || !channels.has(String(delivery.delivered))) return pending;
      const channel = delivery.delivered as HumanAttentionDelivery;
      const receipt = await this.attempts.settle({ sourceKey, eventId, attemptToken, channel });
      if (!record(receipt) || !exact(receipt, ["schemaVersion", "eventKey", "state", "channel"])
          || receipt.schemaVersion !== 1 || receipt.eventKey !== key || receipt.state !== "submitted"
          || receipt.channel !== channel) return pending;
      settled = true;
      return { delivered: channel };
    } catch {
      // A failed or unknown step may have committed or submitted. Never replay.
      return pending;
    } finally {
      if (attemptToken && !settled && this.attempts.abandon) {
        // Release only this live capability; the durable uncertain attempt
        // remains and does not authorize another notification.
        try { await this.attempts.abandon({ sourceKey, eventId, attemptToken }); } catch { /* Preserve pending. */ }
      }
    }
  }
}
