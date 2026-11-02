import { createHash, randomBytes } from "node:crypto";
import type { AssistantRegistryDocumentLease } from "./projectRegistry.js";
import { configurationReferenceResult, type ConfigurationReferenceHostContext, type ConfigurationReferenceRequest,
  type ConfigurationReferenceResult, type ConfigurationReferenceSnapshot } from "./configurationReferenceProtocol.js";

type Hold = { key: string; host: ConfigurationReferenceHostContext; contextId: string; leaseId: string;
  ready: Promise<AssistantRegistryDocumentLease>; document?: AssistantRegistryDocumentLease;
  snapshot?: ConfigurationReferenceSnapshot; revoked: boolean; abort(): void; draining?: Promise<void>; mustDrain?: boolean;
  recovering?: Promise<void>; done: AbortController; releaseRetention(): void;
  deliveries: Map<string, "pending" | "accepted" | "rejected" | "unknown"> };
const digest = (value: unknown) => createHash("sha256").update(JSON.stringify(value)).digest("hex");
const copy = (snapshot: ConfigurationReferenceSnapshot): ConfigurationReferenceSnapshot => ({ ...snapshot, projects: snapshot.projects.map(row => ({ ...row })) });
const delay = (ms: number, signal: AbortSignal) => new Promise<void>(resolve => {
  if (signal.aborted) { resolve(); return; }
  const finish = () => { clearTimeout(timer); signal.removeEventListener("abort", finish); resolve(); };
  const timer = setTimeout(finish, ms); timer.unref?.();
  signal.addEventListener("abort", finish, { once: true });
});

/** One private reference scan at a time, under the actual registry document owner.
 * Revocation invalidates immediately; a live captured Job keeps the write fence.
 */
export class ConfigurationReferenceLeaseBroker {
  private active: Hold | null = null;
  private readonly released = new Map<string, { leaseId: string; snapshotDigest: string }>();
  constructor(private readonly registry: { acquireRegistryDocumentAdmission(): Promise<AssistantRegistryDocumentLease> }) {}

  private key(host: ConfigurationReferenceHostContext, contextId: string): string {
    return digest([host.generationId, host.agentId, host.sessionId, host.nativeAssistantRoot, contextId]);
  }
  private finish(hold: Hold): void {
    if (hold.done.signal.aborted) return;
    hold.document?.release();
    hold.done.abort(); hold.releaseRetention();
    hold.host.signal.removeEventListener("abort", hold.abort);
    if (this.active === hold) this.active = null;
    if (hold.snapshot) {
      this.released.set(hold.key, { leaseId: hold.leaseId, snapshotDigest: hold.snapshot.snapshotDigest });
      if (this.released.size > 1024) this.released.delete(this.released.keys().next().value!);
    }
    void this.acknowledge(hold);
  }
  private async acknowledge(hold: Hold): Promise<void> {
    let retry = 100;
    while (!hold.host.signal.aborted) {
      try {
        hold.host.check();
        // Best-effort metadata cleanup cannot retain an already ended scope.
        // Missing/evicted ACK tombstones never re-freeze the registry or Job.
        await hold.host.ackWorkComplete(hold.contextId); return;
      }
      catch {
        try { hold.host.check(); } catch { return; }
      }
      await delay(retry, hold.host.signal); retry = Math.min(1000, retry * 2);
    }
  }
  private async complete(hold: Hold): Promise<boolean> {
    if (this.active !== hold || hold.done.signal.aborted || hold.host.signal.aborted) return false;
    hold.host.check();
    if (!await hold.host.readWorkComplete(hold.contextId)) return false;
    hold.host.check();
    try { hold.document = await hold.ready; }
    catch { /* Failed acquisition owns no document, but its scope still ended. */ }
    hold.host.check();
    if (this.active !== hold || hold.done.signal.aborted || hold.host.signal.aborted) return false;
    this.finish(hold);
    return true;
  }
  private recover(hold: Hold): void {
    hold.revoked = true; hold.mustDrain = true;
    this.drain(hold);
    hold.recovering ??= (async () => {
      let retry = 100;
      while (this.active === hold && !hold.done.signal.aborted && !hold.host.signal.aborted) {
        try { if (await this.complete(hold)) return; }
        catch { /* A missing or malformed native proof keeps the reservation. */ }
        await delay(retry, hold.done.signal); retry = Math.min(1000, retry * 2);
      }
    })();
  }
  private drain(hold: Hold): void {
    hold.revoked = true;
    hold.draining ??= (async () => {
      try {
        await hold.host.drain(hold.done.signal);
        try { hold.document = await hold.ready; }
        catch { this.finish(hold); return; } // Failed acquisition already released its document admission.
        this.finish(hold);
      } catch { /* An unknown Job or writer drain retains its exact fence. */ }
    })();
  }
  /** Called only with the private broker's acknowledgement for this delivery.
   * A known rejection proves this snapshot was not delivered. A transport loss
   * proves nothing about whether the native writer started using its lease.
   */
  settled(request: ConfigurationReferenceRequest, value: unknown, accepted: boolean | undefined,
    host?: ConfigurationReferenceHostContext): void {
    if (request.action !== "configuration_reference_acquire" || !host) return;
    const hold = this.active;
    const result = configurationReferenceResult(request, value);
    if (!hold || hold.key !== this.key(host, request.contextId) || !("complete" in result) || result.complete !== true
        || result.leaseId !== hold.leaseId || result.snapshotDigest !== hold.snapshot?.snapshotDigest) return;
    hold.deliveries.set(request.deliveryId, accepted === undefined ? "unknown" : accepted ? "accepted" : "rejected");
    if (accepted === undefined) {
      this.recover(hold);
    } else if (accepted === false && [...hold.deliveries.values()].every(state => state === "rejected")) {
      this.finish(hold);
    }
  }
  async handle(request: ConfigurationReferenceRequest, host?: ConfigurationReferenceHostContext): Promise<ConfigurationReferenceResult> {
    const unavailable = () => configurationReferenceResult(request, undefined);
    if (!host) return unavailable();
    const key = this.key(host, request.contextId);
    if (request.action === "configuration_reference_release") {
      const previous = this.released.get(key), hold = this.active;
      if (previous?.leaseId === request.leaseId && previous.snapshotDigest === request.snapshotDigest)
        return { schemaVersion: 1, leaseId: request.leaseId, released: true };
      if (!hold || hold.key !== key || hold.leaseId !== request.leaseId || hold.snapshot?.snapshotDigest !== request.snapshotDigest)
        return unavailable();
      if (host.signal.aborted) { this.drain(hold); return unavailable(); }
      if (hold.mustDrain) {
        try { if (await this.complete(hold)) return { schemaVersion: 1, leaseId: request.leaseId, released: true }; }
        catch { /* Only the original native scope can prove completion. */ }
        this.recover(hold); return unavailable();
      }
      // Explicit release closes this native operation's reference scope; it may
      // release an invalidated document too, without authorizing another write.
      try { host.check(); this.finish(hold); return { schemaVersion: 1, leaseId: request.leaseId, released: true }; }
      catch { this.drain(hold); return unavailable(); }
    }
    try { host.check(); if (host.signal.aborted) return unavailable(); } catch { return unavailable(); }
    if (request.action === "configuration_reference_validate") {
      const hold = this.active;
      if (!hold || hold.key !== key || hold.revoked || hold.leaseId !== request.leaseId
          || hold.snapshot?.snapshotDigest !== request.snapshotDigest || !hold.document) return unavailable();
      try {
        hold.document.check(); host.check();
        return { schemaVersion: 1, leaseId: request.leaseId, valid: true, revision: hold.snapshot.revision,
          snapshotDigest: request.snapshotDigest };
      } catch { hold.revoked = true; return unavailable(); }
    }
    if (this.active?.key !== undefined && this.active.key !== key) return { schemaVersion: 1, complete: false, code: "busy" };
    if (this.active?.revoked) return unavailable();
    if (!this.active) {
      let releaseRetention: () => void;
      try { releaseRetention = host.retainLease(); } catch { return unavailable(); }
      const hold: Hold = { key, host, contextId: request.contextId, leaseId: randomBytes(32).toString("hex"),
        ready: Promise.resolve().then(() => this.registry.acquireRegistryDocumentAdmission()), revoked: false,
        abort: () => this.drain(hold), deliveries: new Map(), done: new AbortController(), releaseRetention };
      this.active = hold;
      host.signal.addEventListener("abort", hold.abort, { once: true });
    }
    const hold = this.active;
    hold.deliveries.set(request.deliveryId, "pending");
    try {
      const document = await hold.ready;
      hold.document = document;
      host.check(); document.check();
      if (hold.revoked || host.signal.aborted || this.active !== hold) return unavailable();
      if (!hold.snapshot) {
        const content = { ...document.snapshot, nativeAssistantRoot: host.nativeAssistantRoot };
        const snapshot = { ...content, leaseId: hold.leaseId, snapshotDigest: digest(content) };
        const checked = configurationReferenceResult(request, snapshot);
        if (!("complete" in checked) || checked.complete !== true) throw new Error("REFERENCE_SNAPSHOT_UNAVAILABLE");
        hold.snapshot = checked;
      }
      return copy(hold.snapshot);
    } catch {
      if (!host.signal.aborted && !hold.revoked) {
        // Even a pending ACK may already have delivered an earlier snapshot.
        // Failure of a duplicate acquire is no proof that its old writer ended.
        if (hold.snapshot) this.recover(hold); else this.finish(hold);
      }
      return unavailable();
    }
  }
}
