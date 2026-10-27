import { createHash } from "node:crypto";
import { realpathSync, statSync } from "node:fs";
import { isAbsolute } from "node:path";
import { AssistantProjectLifecycleRequestStore } from "../assistant/projectLifecycleRequestStore.js";

/** Resolved by Electron main from its own registry, never from a renderer payload. */
export type LegacyReminderSourceBinding = {
  projectId: string;
  instanceId: string;
  physicalRoot: string;
  physicalIdentity: { device: string; inode: string };
};

type StopResult = {
  boundCallsDrained: true;
  preFenceIngressDrained: true;
  ingressDrainedAtReturn: true;
  unboundSourcesMayStillSend: true;
  readyForCutover: false;
};
type FenceState = {
  closing: Set<string>;
  unconfirmed: Set<string>;
  active: Map<string, Set<Promise<unknown>>>;
  ingress: Set<Promise<void>>;
  stopping: Map<string, Promise<StopResult>>;
};

function sourceKey(source: LegacyReminderSourceBinding): string {
  if (!source || typeof source.projectId !== "string" || !source.projectId.trim()
      || typeof source.instanceId !== "string" || !source.instanceId.trim()
      || source.instanceId.length > 512 || source.instanceId.includes("\0")
      || typeof source.physicalRoot !== "string" || !isAbsolute(source.physicalRoot)
      || !source.physicalIdentity || !/^[0-9]+$/.test(source.physicalIdentity.device)
      || !/^[0-9]+$/.test(source.physicalIdentity.inode)) throw new Error("LEGACY_REMINDER_SOURCE_INVALID");
  const physical = realpathSync.native(source.physicalRoot);
  const info = statSync(physical, { bigint: true });
  if (!info.isDirectory() || info.dev === 0n || info.ino === 0n
      || info.dev.toString() !== source.physicalIdentity.device
      || info.ino.toString() !== source.physicalIdentity.inode) throw new Error("LEGACY_REMINDER_SOURCE_CHANGED");
  const root = process.platform === "win32" ? physical.toLowerCase() : physical;
  // Deliberately independent of project registry epoch and URL, so those
  // changing cannot reopen a stopped physical instance.
  return "reminder_" + createHash("sha256").update(JSON.stringify([
    root, info.dev.toString(), info.ino.toString(), source.instanceId,
  ])).digest("hex");
}

/**
 * Current Electron-main sender only. Persistent stop intent uses the existing
 * validated, fsynced single-writer request store. This does not fence older
 * executables, discover all sources, or prove a delivery watermark.
 */
export class LegacyReminderSourceFence {
  private static readonly states = new Map<string, FenceState>();
  private readonly store: AssistantProjectLifecycleRequestStore;
  private readonly state: FenceState;

  constructor(directory: string) {
    this.store = new AssistantProjectLifecycleRequestStore({ directory });
    const physical = realpathSync.native(directory);
    const key = process.platform === "win32" ? physical.toLowerCase() : physical;
    let state = LegacyReminderSourceFence.states.get(key);
    if (!state) {
      state = { closing: new Set(), unconfirmed: new Set(), active: new Map(), ingress: new Set(), stopping: new Map() };
      LegacyReminderSourceFence.states.set(key, state);
    }
    this.state = state;
  }

  /** Enroll before any asynchronous source lookup; completion includes delivery. */
  async trackIngress<T>(work: () => Promise<T>): Promise<T> {
    let finish!: () => void;
    const complete = new Promise<void>(resolve => { finish = resolve; });
    this.state.ingress.add(complete);
    try { return await work(); }
    finally { this.state.ingress.delete(complete); finish(); }
  }

  async submit<T>(source: LegacyReminderSourceBinding | null, send: () => Promise<T>): Promise<T | { delivered: "source_retired" }> {
    return await this.trackIngress(() => this.submitEnrolled(source, send));
  }

  private async submitEnrolled<T>(source: LegacyReminderSourceBinding | null, send: () => Promise<T>): Promise<T | { delivered: "source_retired" }> {
    // Missing trusted binding preserves the old sender, and is never proof for
    // enabling a new sender. Only Electron main supplies this binding.
    if (source === null) return await send();
    const key = sourceKey(source);
    if (this.state.closing.has(key)) return { delivered: "source_retired" };
    const record = await this.store.get(key);
    if (sourceKey(source) !== key) throw new Error("LEGACY_REMINDER_SOURCE_CHANGED");
    if (record || this.state.closing.has(key)) return { delivered: "source_retired" };
    const pending = Promise.resolve().then(() => {
      if (sourceKey(source) !== key) throw new Error("LEGACY_REMINDER_SOURCE_CHANGED");
      return send();
    });
    const group = this.state.active.get(key) ?? new Set<Promise<unknown>>();
    group.add(pending);
    this.state.active.set(key, group);
    try { return await pending; }
    finally { group.delete(pending); if (!group.size) this.state.active.delete(key); }
  }

  async stop(source: LegacyReminderSourceBinding): Promise<StopResult> {
    const key = sourceKey(source);
    const existing = this.state.stopping.get(key);
    if (existing) return await existing;
    // Synchronous admission close precedes both persistence and any wait.
    this.state.closing.add(key);
    const preFenceIngress = [...this.state.ingress];
    if (this.state.unconfirmed.has(key)) throw new Error("LEGACY_REMINDER_FENCE_UNCONFIRMED");
    const operation = (async () => {
      try {
        await this.store.reserve({ requestId: key, projectId: "legacy-reminder-source", operation: "stop" });
        if (sourceKey(source) !== key) throw new Error("LEGACY_REMINDER_SOURCE_CHANGED");
        await Promise.all(preFenceIngress);
        await Promise.allSettled([...(this.state.active.get(key) ?? [])]);
        // Requests can arrive while the first barrier drains. Wait for every
        // enrolled request currently outstanding, including unbound requests.
        while (this.state.ingress.size) await Promise.all([...this.state.ingress]);
        if (sourceKey(source) !== key) throw new Error("LEGACY_REMINDER_SOURCE_CHANGED");
        return { boundCallsDrained: true, preFenceIngressDrained: true, ingressDrainedAtReturn: true,
          unboundSourcesMayStillSend: true, readyForCutover: false } as const;
      } catch (error) { this.state.unconfirmed.add(key); throw error; }
    })();
    this.state.stopping.set(key, operation);
    try { return await operation; }
    finally { if (this.state.stopping.get(key) === operation) this.state.stopping.delete(key); }
  }

  /** A surviving marker is only an admission fence, not a cross-process drain proof. */
  async isStopped(source: LegacyReminderSourceBinding): Promise<boolean> {
    const key = sourceKey(source);
    const record = await this.store.get(key);
    if (sourceKey(source) !== key) throw new Error("LEGACY_REMINDER_SOURCE_CHANGED");
    if (this.state.unconfirmed.has(key) || (this.state.closing.has(key) && !record)) throw new Error("LEGACY_REMINDER_FENCE_UNCONFIRMED");
    return Boolean(record);
  }
}
