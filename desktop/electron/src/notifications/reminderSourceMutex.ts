import { isMainThread } from "node:worker_threads";
import { loadWorkbenchJobNative } from "../process/workbenchJob.js";

/** Supplied only by the trusted main/host source-binding adapter, never IPC payloads. */
export type ReminderSourcePermit = Readonly<{ check(): Promise<void>; release(): Promise<void> }>;
export type VerifiedReminderLedger = Readonly<{
  ledgerKey: string;
  /** Synchronous local identity and revocation check. */
  verify(): void;
  /** Host-owned route/source pin, held across every effect until explicit release. */
  acquirePermit?(): Promise<ReminderSourcePermit | null>;
}>;
export type ReminderSourceMutexLease = Readonly<{ abandoned: boolean; check(): void; release(): void }>;
type MutexNative = {
  tryAcquireReminderMutex(key: string): null | { handle: object; abandoned: boolean };
  releaseReminderMutex(handle: object): void;
};

/**
 * Nonblocking source serialization, held until explicit same-thread release.
 * An abandoned acquisition requires independent recovery of every uncertain
 * attempt. Absence of an abandoned flag is not proof of a clean prior exit:
 * Windows can destroy the named object when its last handle closes. A mutex
 * does not establish that legacy or external senders obey it.
 * All participants must verify and pin the same source for the entire hold.
 */
export function tryAcquireReminderSourceMutex(binding: VerifiedReminderLedger): ReminderSourceMutexLease | null {
  if (!isMainThread || !binding || typeof binding.ledgerKey !== "string"
      || !/^[a-f0-9]{64}$/.test(binding.ledgerKey) || typeof binding.verify !== "function")
    throw new Error("REMINDER_MUTEX_INVALID");
  const native = loadWorkbenchJobNative() as unknown as Partial<MutexNative>;
  if (typeof native.tryAcquireReminderMutex !== "function" || typeof native.releaseReminderMutex !== "function")
    throw new Error("REMINDER_MUTEX_UNAVAILABLE");
  const key = binding.ledgerKey;
  const verify = () => {
    if ((binding.verify as () => unknown)() !== undefined || binding.ledgerKey !== key)
      throw new Error("REMINDER_MUTEX_BINDING_CHANGED");
  };
  verify();
  const acquired = native.tryAcquireReminderMutex(key);
  if (acquired === null) return null;
  if (!acquired || typeof acquired.handle !== "object" || acquired.handle === null
      || typeof acquired.abandoned !== "boolean") throw new Error("REMINDER_MUTEX_UNAVAILABLE");
  const releaseNative = native.releaseReminderMutex;
  let held = true;
  const check = () => {
    if (!held || !isMainThread) throw new Error("REMINDER_MUTEX_RELEASED");
    verify();
  };
  try { check(); }
  catch (error) { releaseNative(acquired.handle); held = false; throw error; }
  return Object.freeze({
    abandoned: acquired.abandoned,
    check,
    release: () => {
      if (!held || !isMainThread) throw new Error("REMINDER_MUTEX_RELEASED");
      releaseNative(acquired.handle);
      held = false;
    },
  });
}
