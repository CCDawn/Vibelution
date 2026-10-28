import { createHash } from "node:crypto";
import { closeSync, fstatSync, fsyncSync, lstatSync, openSync, readFileSync, realpathSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";

import { tryAcquireReminderSourceMutex, type ReminderSourceMutexLease } from "../notifications/reminderSourceMutex.js";
import { readProjectId } from "../lifecycle/projectStoragePaths.js";
import { writeLauncherStateFile } from "../process/workbenchBackend.js";
import { AssistantProjectRegistry, type AssistantProjectRegistrySnapshot, type AssistantProjectRegistration } from "./projectRegistry.js";
import { PrehostRecoveryDrainedUnknown } from "./prehostRecoveryJob.js";

type ProjectHost = {
  start(): Promise<unknown>;
  startForMigration?(): Promise<unknown>;
  stop(): Promise<unknown>;
  updateProjects(snapshot: AssistantProjectRegistrySnapshot): Promise<void>;
  suspendProjects?(): Promise<void>;
  retireForMigration?(): Promise<boolean>;
};
type Inventory = { integrationRoot: string; items: Array<{ id: string; path: string; checkedOut: boolean }> };
type DirectoryIdentity = { dev: bigint; ino: bigint; birthtimeNs: bigint };
type RecoveryMarker = { schemaVersion: 1; projectId: string; operationId: string; revision: number;
  registration: AssistantProjectRegistration; identity: { dev: string; ino: string; birthtimeNs: string } };
export type PreHostSourceLease = Readonly<{
  revision: number;
  registration: Readonly<AssistantProjectRegistration>;
  signal: AbortSignal;
  check(): void;
  /** One admitted writer holds the lease until its owned Job has fully drained. */
  commit<T>(work: () => Promise<T>): Promise<T>;
}>;
/** Holds the verified source and route locks until release; check must fail on revocation. */
export type PreHostRecoverySourceLease = Readonly<{
  check(): Promise<boolean>;
  /** Verify the original operation receipt under the same held locks. */
  verifyReceipt(): Promise<boolean>;
  commitMarker?(input: { markerPath: string; markerSha256: string; markerIdentity: { device: string; inode: string; birthtimeNs: string };
    commitKey: string; checkAuthority(): void }): Promise<boolean>;
  release(): Promise<void>;
}>;
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function path(value: unknown): value is string {
  return typeof value === "string" && value === value.trim() && !value.includes("\0") && isAbsolute(value)
    && (process.platform !== "win32" || /^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)/.test(value));
}
function inventory(value: unknown): Inventory {
  if (!record(value) || value.schemaVersion !== 1 || !path(value.integrationRoot) || !Array.isArray(value.items)) {
    throw new Error("ASSISTANT_INVENTORY_INVALID");
  }
  const ids = new Set<string>();
  const items = value.items.map(row => {
    if (!record(row) || typeof row.id !== "string" || !row.id.trim() || row.id !== row.id.trim()
      || row.id.length > 512 || row.id.includes("\0") || ids.has(row.id) || typeof row.checkedOut !== "boolean"
      || typeof row.path !== "string" || (row.checkedOut && !path(row.path))) throw new Error("ASSISTANT_INVENTORY_INVALID");
    ids.add(row.id);
    return { id: row.id, path: row.path, checkedOut: row.checkedOut };
  });
  return { integrationRoot: value.integrationRoot, items };
}
const hash = (value: string) => createHash("sha256").update(value).digest("hex").slice(0, 24);
const readable = (value: string) => value.replace(/[^A-Za-z0-9_.:-]/g, "_").slice(0, 28) || "project";
function physical(path: string): string {
  const result = resolve(realpathSync.native(path));
  return process.platform === "win32" ? result.toLowerCase() : result;
}
function directoryIdentity(path: string): DirectoryIdentity {
  const before = lstatSync(path, { bigint: true });
  if (!before.isDirectory() || before.isSymbolicLink() || before.dev <= 0n || before.ino <= 0n || before.birthtimeNs <= 0n) {
    throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
  }
  if (physical(path) !== path) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
  const after = lstatSync(path, { bigint: true });
  if (!after.isDirectory() || after.isSymbolicLink() || before.dev !== after.dev || before.ino !== after.ino
    || before.birthtimeNs !== after.birthtimeNs) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
  return { dev: after.dev, ino: after.ino, birthtimeNs: after.birthtimeNs };
}
function sameDirectory(a: DirectoryIdentity, b: DirectoryIdentity): boolean {
  return a.dev === b.dev && a.ino === b.ino && a.birthtimeNs === b.birthtimeNs;
}

/** Electron-main connection only. No renderer input, instance history, or directory discovery. */
export class AssistantProjectRegistryConnection {
  private readonly registry: AssistantProjectRegistry;
  private serial: Promise<unknown> = Promise.resolve();
  private host: ProjectHost | null = null;
  private acknowledgedRevision = -1;
  private projectsSuspended = false;
  private closed = false;
  private preHostAbort: AbortController | null = null;
  private preHostRoot: { path: string; identity: DirectoryIdentity } | null = null;
  private preHostCommitting = false;
  private preHostRevoked = false;
  private observationEpoch = 0;
  private authorityRequiredAfter = 0;
  private readonly recoveryPath: string;
  private readonly writeRecoveryMarker: typeof writeLauncherStateFile;
  private recovery: { marker: RecoveryMarker | null; raw: string; reconciled: boolean } | null = null;
  private pendingIdentity: { projectId: string; operationId: string } | null = null;
  private recoveryCommit: { revoke(): void } | null = null;
  private readonly acquireRecoveryCommitGate: (key: string) => ReminderSourceMutexLease | null;
  private migrationGate: { released: Promise<void>; release: () => void } | null = null;

  constructor(filePath: string, options?: { writeRecoveryMarker?: typeof writeLauncherStateFile;
    acquireRecoveryCommitGate?: (key: string) => ReminderSourceMutexLease | null }) {
    this.acquireRecoveryCommitGate = options?.acquireRecoveryCommitGate ?? (key => tryAcquireReminderSourceMutex({ ledgerKey: key, verify: () => {} }));
    this.registry = new AssistantProjectRegistry({ filePath });
    this.recoveryPath = `${filePath}.prehost-recovery.json`;
    this.writeRecoveryMarker = options?.writeRecoveryMarker ?? writeLauncherStateFile;
    try {
      const info = lstatSync(this.recoveryPath);
      if (!info.isFile() || info.isSymbolicLink() || info.size > 16384) throw new Error();
      const raw = readFileSync(this.recoveryPath, "utf8");
      const value: unknown = JSON.parse(raw);
      this.recovery = { marker: this.parseRecoveryMarker(value), raw, reconciled: false };
    } catch (error) {
      if ((error as NodeJS.ErrnoException)?.code !== "ENOENT") this.recovery = { marker: null, raw: "", reconciled: false };
    }
    try {
      const name = this.recoveryPath + ".commit-pending", before = lstatSync(name);
      if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1 || before.size < 1 || before.size > 16384) throw new Error();
      const fd = openSync(name, "r");
      try {
        const opened = fstatSync(fd), raw = readFileSync(fd, "utf8"), after = fstatSync(fd), pathAfter = lstatSync(name);
        if (opened.dev !== before.dev || opened.ino !== before.ino || after.dev !== before.dev || after.ino !== before.ino
          || pathAfter.dev !== before.dev || pathAfter.ino !== before.ino || pathAfter.isSymbolicLink()
          || after.size !== before.size || after.mtimeMs !== before.mtimeMs || after.nlink !== 1) throw new Error();
        const value: unknown = JSON.parse(raw);
        if (!record(value) || Object.keys(value).sort().join(",") !== "markerSha256,operationId,projectId,revision,schemaVersion,state"
          || value.schemaVersion !== 1 || value.state !== "pending" || !Number.isSafeInteger(value.revision) || Number(value.revision) < 0
          || typeof value.projectId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value.projectId)
          || typeof value.operationId !== "string" || !/^(?:initial|ksync|krec|affairs)-[a-f0-9]{40}$/.test(value.operationId)
          || typeof value.markerSha256 !== "string" || !/^[a-f0-9]{64}$/.test(value.markerSha256)) throw new Error();
        this.pendingIdentity = { projectId: value.projectId, operationId: value.operationId };
      } finally { closeSync(fd); }
    } catch { /* Missing or damaged pending remains untrusted and blocked below. */ }
    // A verifier can commit marker removal and die before its ACK. Neither a
    // pending-commit record nor a revoke sidecar is safe to ignore on restart.
    for (const suffix of [".commit-pending", ".revoked"]) {
      try { lstatSync(this.recoveryPath + suffix); this.recovery ??= { marker: null, raw: "", reconciled: false }; }
      catch (error) {
        if ((error as NodeJS.ErrnoException)?.code !== "ENOENT") this.recovery ??= { marker: null, raw: "", reconciled: false };
      }
    }
  }

  private parseRecoveryMarker(value: unknown): RecoveryMarker {
    if (!record(value) || Object.keys(value).sort().join(",") !== "identity,operationId,projectId,registration,revision,schemaVersion"
      || value.schemaVersion !== 1 || typeof value.projectId !== "string" || !value.projectId
      || typeof value.operationId !== "string" || !/^(?:initial|ksync|krec|affairs)-[a-f0-9]{40}$/.test(value.operationId)
      || !Number.isSafeInteger(value.revision) || Number(value.revision) < 0 || !record(value.registration)
      || Object.keys(value.registration).sort().join(",") !== "active,baseProjectId,integrationRoot,registrationUuid,root"
      || value.registration.active !== true || !path(value.registration.integrationRoot) || !path(value.registration.root)
      || typeof value.registration.baseProjectId !== "string" || typeof value.registration.registrationUuid !== "string"
      || !record(value.identity) || Object.keys(value.identity).sort().join(",") !== "birthtimeNs,dev,ino"
      || ![value.identity.dev, value.identity.ino, value.identity.birthtimeNs].every(item => typeof item === "string" && /^[1-9][0-9]{0,24}$/.test(item)))
      throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
    return value as RecoveryMarker;
  }

  /** Trusted main callers only; both reads retain disk/physical-root validation. */
  snapshot(): AssistantProjectRegistrySnapshot { this.assertOpen(); return this.registry.snapshot(); }
  registration(projectId: string): AssistantProjectRegistration | null { this.assertOpen(); return this.registry.registration(projectId); }

  /** Serialize registry observers and live-host writers around a migration. */
  beginMigrationTransition(): { drained: Promise<void>; release: () => void } {
    this.assertOpen();
    if (this.migrationGate) throw new Error("ASSISTANT_MIGRATION_BUSY");
    let resolve!: () => void;
    const released = new Promise<void>(done => { resolve = done; });
    const gate = { released, release: () => {
      if (this.migrationGate !== gate) return;
      this.migrationGate = null;
      resolve();
    } };
    this.migrationGate = gate;
    return { drained: this.enqueue(async () => { this.assertOpen(); }), release: gate.release };
  }

  /** Main-only. The callback must not await another operation on this connection.
   * It must await and confirm the drain of every controlled child before returning;
   * abort is a revocation signal, not evidence that a child has stopped. A final
   * check failure may follow a write: preserve the operation ID and report its
   * outcome unknown rather than replaying it as an unexecuted operation.
   */
  withPreHostSource<T>(projectId: string, operation: (lease: PreHostSourceLease) => Promise<T>, options?: {
    operationId: string; receiptConfirmed(result: T): boolean;
  }): Promise<T> {
    return this.enqueue(async () => {
      this.assertOpen();
      if (this.host || this.projectsSuspended) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      const startup = this.registry.startupState();
      if (startup.projectsSuspended) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      const registration = this.registry.registration(projectId);
      if (!registration || startup.snapshot.projects[projectId] !== registration.root) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      const captured = Object.freeze({ ...registration });
      let rootIdentity: DirectoryIdentity;
      try { rootIdentity = directoryIdentity(captured.root); }
      catch { throw new Error("ASSISTANT_PROJECT_UNAVAILABLE"); }
      if (options && (!/^(?:initial|ksync|krec|affairs)-[a-f0-9]{40}$/.test(options.operationId)
        || typeof options.receiptConfirmed !== "function")) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      const abort = new AbortController();
      this.preHostAbort = abort;
      this.preHostRoot = { path: captured.root, identity: rootIdentity };
      this.preHostRevoked = false;
      let ownedMarker: { marker: RecoveryMarker; raw: string } | undefined;
      if (options) {
        const marker: RecoveryMarker = { schemaVersion: 1, projectId, operationId: options.operationId,
          revision: startup.snapshot.revision, registration: { ...captured },
          identity: { dev: rootIdentity.dev.toString(), ino: rootIdentity.ino.toString(), birthtimeNs: rootIdentity.birthtimeNs.toString() } };
        try {
          try { lstatSync(this.recoveryPath); throw new Error("existing marker"); }
          catch (error) { if ((error as NodeJS.ErrnoException)?.code !== "ENOENT") throw error; }
          await this.writeRecoveryMarker(this.recoveryPath, marker);
          const descriptor = openSync(this.recoveryPath, "r+");
          try { fsyncSync(descriptor); } finally { closeSync(descriptor); }
          const raw = readFileSync(this.recoveryPath, "utf8");
          if (JSON.stringify(this.parseRecoveryMarker(JSON.parse(raw))) !== JSON.stringify(marker)) throw new Error("marker changed");
          ownedMarker = { marker, raw };
        } catch {
          abort.abort();
          if (this.preHostAbort === abort) { this.preHostAbort = null; this.preHostRoot = null; }
          this.recovery = { marker: null, raw: "", reconciled: false };
          throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
        }
      }
      const check = () => {
        try {
          this.assertOpen();
          if (abort.signal.aborted || this.preHostRevoked || this.host || this.projectsSuspended) throw new Error();
          const current = this.registry.startupState();
          const row = this.registry.registration(projectId);
          if (current.projectsSuspended || current.snapshot.revision !== startup.snapshot.revision
            || current.snapshot.projects[projectId] !== captured.root || !row
            || JSON.stringify(row) !== JSON.stringify(captured)
            || !sameDirectory(rootIdentity, directoryIdentity(captured.root))) throw new Error();
        } catch {
          if (!this.preHostCommitting) abort.abort();
          throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
        }
      };
      let committed = false;
      const commit = async <R>(work: () => Promise<R>): Promise<R> => {
        if (committed || !ownedMarker || typeof work !== "function") throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
        check();
        // The caller must await its captured Job's exit and output drain in
        // work(). Later stop/reconciliation waits for this admitted writer.
        committed = true;
        this.preHostCommitting = true;
        try { return await work(); }
        finally {
          this.preHostCommitting = false;
          if (this.preHostRevoked) abort.abort();
        }
      };
      const lease = Object.freeze({ revision: startup.snapshot.revision, registration: captured, signal: abort.signal, check, commit });
      try {
        try {
          check();
          const result = await operation(lease);
          check();
          if (ownedMarker) {
            if (!committed || options!.receiptConfirmed(result) === true) this.removeRecoveryMarker(ownedMarker.raw);
            else this.recovery = { ...ownedMarker, reconciled: false };
          }
          return result;
        } catch (error) {
          if (ownedMarker) {
            if (!committed && !this.preHostRevoked) {
              try { this.removeRecoveryMarker(ownedMarker.raw); }
              catch { this.recovery = { ...ownedMarker, reconciled: false }; }
            } else this.recovery = { ...ownedMarker, reconciled: false };
          }
          check();
          throw error;
        }
      } finally {
        abort.abort();
        if (this.preHostAbort === abort) { this.preHostAbort = null; this.preHostRoot = null; this.preHostRevoked = false; }
      }
    });
  }

  private removeRecoveryMarker(expected: string): void {
    const before = lstatSync(this.recoveryPath, { bigint: true });
    if (!before.isFile() || before.isSymbolicLink() || before.nlink !== 1n || readFileSync(this.recoveryPath, "utf8") !== expected)
      throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
    const after = lstatSync(this.recoveryPath, { bigint: true });
    if (before.dev !== after.dev || before.ino !== after.ino || before.birthtimeNs !== after.birthtimeNs)
      throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
    unlinkSync(this.recoveryPath);
  }

  private revokePreHost(): void {
    this.preHostRevoked = true;
    if (!this.preHostCommitting) this.preHostAbort?.abort();
  }

  /** True only when this whole integration group exactly matches the validated registry. */
  private observationUnchanged(input: Inventory): boolean {
    try {
      if (!this.preHostRoot || !sameDirectory(this.preHostRoot.identity, directoryIdentity(this.preHostRoot.path))) return false;
      const integrationRoot = physical(input.integrationRoot);
      const realm = hash(integrationRoot);
      const snapshot = this.registry.snapshot();
      const existing: string[] = [];
      for (const id of Object.keys(snapshot.projects)) {
        const row = this.registry.registration(id);
        if (!row) return false;
        if (row.integrationRoot === integrationRoot) existing.push(JSON.stringify([row.baseProjectId, row.root]));
      }
      const desired: string[] = [];
      const roots = new Set<string>(), bases = new Set<string>();
      for (const row of input.items) {
        if (!row.checkedOut) continue;
        if (!statSync(row.path).isDirectory()) return false;
        const root = physical(row.path);
        const base = `${readable(readProjectId(row.path) || "project")}:${readable(row.id)}:${hash(row.id).slice(0, 12)}:${realm}`;
        if (roots.has(root) || bases.has(base)) return false;
        roots.add(root); bases.add(base);
        desired.push(JSON.stringify([base, root]));
      }
      return JSON.stringify(existing.sort()) === JSON.stringify(desired.sort());
    } catch { return false; }
  }

  /** Main-only lease: reconciliation and retirement wait until import settles. */
  withHistoryImport<T>(projectId: string, operation: (revision: number) => Promise<T>): Promise<T> {
    if (this.migrationGate) return this.migrationGate.released.then(() => this.withHistoryImport(projectId, operation));
    return this.enqueue(async () => {
      this.assertOpen();
      const snapshot = this.registry.snapshot();
      if (!this.host || this.projectsSuspended || snapshot.revision !== this.acknowledgedRevision
        || !Object.hasOwn(snapshot.projects, projectId) || !this.registry.registration(projectId)) {
        throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      }
      try {
        const result = await operation(snapshot.revision);
        this.assertOpen();
        const current = this.registry.snapshot();
        if (current.revision !== snapshot.revision || current.projects[projectId] !== snapshot.projects[projectId]
          || !this.registry.registration(projectId)) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
        return result;
      } catch (error) {
        // An unconfirmed host cancellation cannot coexist with a later grant.
        this.closed = true;
        await this.retire();
        throw error;
      }
    });
  }

  start<T extends ProjectHost>(createHost: (snapshot: AssistantProjectRegistrySnapshot, projectsSuspended: boolean) => T,
    options?: { migration?: boolean; recovery?: boolean }): Promise<T> {
    if (this.migrationGate && !options?.migration) return this.migrationGate.released.then(() => this.start(createHost, options));
    return this.enqueue(async () => {
      this.assertNotClosed();
      if (options?.recovery && (!options.migration || !this.migrationGate || !this.recovery))
        throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      if ((this.recovery || this.authorityRequiredAfter) && options?.migration && !options.recovery)
        throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      if (this.host && !options?.migration) throw new Error("ASSISTANT_ALREADY_STARTED");
      const startup = this.registry.startupState();
      const { snapshot } = startup;
      const projectsSuspended = startup.projectsSuspended || Boolean(this.recovery || this.authorityRequiredAfter);
      const host = createHost(snapshot, projectsSuspended);
      if (this.host && this.host !== host) throw new Error("ASSISTANT_ALREADY_STARTED");
      this.host = host;
      if (options?.migration) {
        if (!host.startForMigration) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
        await host.startForMigration();
      } else await host.start();
      this.acknowledgedRevision = snapshot.revision;
      this.projectsSuspended = projectsSuspended;
      return host;
    });
  }

  /** Main-only, after the caller has fenced and drained every host producer.
   * A pending or ambiguous retirement retains the original host registration;
   * pre-host writers cannot acquire a lease until the original Job has drained.
   */
  retireHostForMigration(): Promise<boolean> {
    return this.enqueue(async () => {
      this.assertOpen();
      const host = this.host;
      if (!host?.retireForMigration) return false;
      if (!await host.retireForMigration()) return false;
      if (this.host !== host) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      this.host = null;
      this.acknowledgedRevision = -1;
      return true;
    });
  }

  reconcile(payload: unknown): Promise<void> {
    // Capture and validate every row before queuing: a dropped malformed row
    // must never turn an incomplete observation into an authoritative revoke.
    const epoch = ++this.observationEpoch;
    if (this.recoveryCommit) {
      this.authorityRequiredAfter = epoch;
      if (this.recovery) this.recovery.reconciled = false;
      this.recoveryCommit.revoke();
    }
    let input: Inventory;
    try { input = inventory(payload); }
    catch (error) {
      if (this.preHostAbort || this.recovery) { this.authorityRequiredAfter = epoch; if (this.recovery) this.recovery.reconciled = false; }
      this.revokePreHost();
      return Promise.reject(error);
    }
    if (this.preHostAbort && !this.observationUnchanged(input)) {
      this.authorityRequiredAfter = epoch;
      this.revokePreHost();
    }
    const apply = () => this.enqueue(async () => {
      this.assertNotClosed();
      if (this.authorityRequiredAfter && epoch < this.authorityRequiredAfter) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      let snapshot: AssistantProjectRegistrySnapshot;
      try {
        const integrationRoot = physical(input.integrationRoot);
        const realm = hash(integrationRoot);
        const candidates = input.items.filter(row => row.checkedOut).map(row => ({
          projectId: `${readable(readProjectId(row.path) || "project")}:${readable(row.id)}:${hash(row.id).slice(0, 12)}:${realm}`,
          root: row.path, checkedOut: true,
        }));
        snapshot = await this.registry.reconcile(integrationRoot, candidates);
      } catch (error) {
        await this.suspendOrRetire();
        throw error;
      }
      if (this.authorityRequiredAfter && epoch < this.authorityRequiredAfter) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      if (this.host && !this.recovery && (snapshot.revision > this.acknowledgedRevision || this.projectsSuspended)) {
        try {
          await this.host.updateProjects(snapshot);
          this.acknowledgedRevision = snapshot.revision;
          this.projectsSuspended = false;
        }
        catch (error) {
          // A failed/unknown acknowledgement is terminal for this connection;
          // later inventory events cannot replay updates or restart its host.
          await this.retire();
          throw error;
        }
      }
      if (this.authorityRequiredAfter && epoch >= this.authorityRequiredAfter) this.authorityRequiredAfter = 0;
      if (this.recovery?.marker && epoch >= this.authorityRequiredAfter) {
        const marker = this.recovery.marker;
        try {
          const row = this.registry.registration(marker.projectId), ident = directoryIdentity(marker.registration.root);
          if (physical(input.integrationRoot) === marker.registration.integrationRoot
            && JSON.stringify(row) === JSON.stringify(marker.registration)
            && ident.dev.toString() === marker.identity.dev && ident.ino.toString() === marker.identity.ino
            && ident.birthtimeNs.toString() === marker.identity.birthtimeNs) this.recovery.reconciled = true;
        } catch { this.recovery.reconciled = false; }
      }
    });
    return this.migrationGate ? this.migrationGate.released.then(apply) : apply();
  }

  /** Admission revocation must be ordered against the same verifier commit gate. */
  revokePreHostRecovery(): void {
    if (!this.recovery) return;
    this.authorityRequiredAfter = ++this.observationEpoch;
    this.recovery.reconciled = false;
    this.recoveryCommit?.revoke();
  }

  /** Main-only recovery; verifier checks the original durable operation receipt. */
  hasPendingPreHostRecovery(): boolean { return this.recovery !== null; }

  pendingPreHostRecovery(): { projectId: string; operationId: string } | null {
    const marker = this.recovery?.marker;
    return marker ? { projectId: marker.projectId, operationId: marker.operationId } : this.pendingIdentity;
  }

  recoverPreHostSource(operationId: string,
    acquireSource: (marker: Readonly<RecoveryMarker>) => Promise<PreHostRecoverySourceLease | null>): Promise<boolean> {
    return this.enqueue(async () => {
      this.assertNotClosed();
      const recovery = this.recovery, marker = recovery?.marker;
      if (!recovery || !marker || !recovery.reconciled || marker.operationId !== operationId
        || typeof acquireSource !== "function" || this.authorityRequiredAfter || this.host) return false;
      for (const suffix of [".commit-pending", ".revoked"]) {
        try { lstatSync(this.recoveryPath + suffix); return false; }
        catch (error) { if ((error as NodeJS.ErrnoException)?.code !== "ENOENT") return false; }
      }
      const epoch = this.observationEpoch;
      const proof = Object.freeze({ ...marker, registration: Object.freeze({ ...marker.registration }), identity: Object.freeze({ ...marker.identity }) });
      let source: PreHostRecoverySourceLease | null = null, revoked = false, revokeDurable = false;
      const markerSha256 = createHash("sha256").update(recovery.raw, "utf8").digest("hex");
      const commitKey = createHash("sha256").update(`Vibelution.PrehostCommit.v1\0${markerSha256}`, "utf8").digest("hex");
      const writeRevoke = (): boolean => {
        let gate: ReminderSourceMutexLease | null = null;
        try {
          gate = this.acquireRecoveryCommitGate(commitKey);
          if (!gate) return false;
          gate.check();
          const sidecar = this.recoveryPath + ".revoked";
          try {
            const fd = openSync(sidecar, "wx", 0o600);
            try { writeFileSync(fd, JSON.stringify({ schemaVersion: 1, markerSha256, reason: "revoked" })); fsyncSync(fd); }
            finally { closeSync(fd); }
          } catch (error) { if ((error as NodeJS.ErrnoException)?.code !== "EEXIST") throw error; }
          gate.check(); revokeDurable = true;
          return true;
        } catch { return false; }
        finally { try { gate?.release(); } catch { revokeDurable = false; } }
      };
      const commit = { revoke: () => { revoked = true; writeRevoke(); } };
      const checkAuthority = () => {
        const current = this.registry.registration(marker.projectId), id = directoryIdentity(marker.registration.root);
        if (revoked || this.closed || this.host || this.recovery !== recovery || !recovery.reconciled || this.authorityRequiredAfter
          || this.observationEpoch !== epoch || JSON.stringify(current) !== JSON.stringify(marker.registration)
          || id.dev.toString() !== marker.identity.dev || id.ino.toString() !== marker.identity.ino
          || id.birthtimeNs.toString() !== marker.identity.birthtimeNs) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
      };
      try {
        source = await acquireSource(proof);
        if (!source || typeof source.check !== "function" || typeof source.verifyReceipt !== "function"
          || typeof source.commitMarker !== "function" || typeof source.release !== "function"
          || await source.check() !== true || await source.verifyReceipt() !== true || await source.check() !== true) return false;
        checkAuthority();
        const info = lstatSync(this.recoveryPath, { bigint: true });
        if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1n || readFileSync(this.recoveryPath, "utf8") !== recovery.raw)
          return false;
        const pendingPath = this.recoveryPath + ".commit-pending";
        const fd = openSync(pendingPath, "wx", 0o600);
        try { writeFileSync(fd, JSON.stringify({ schemaVersion: 1, projectId: marker.projectId, revision: marker.revision,
          operationId: marker.operationId, markerSha256, state: "pending" })); fsyncSync(fd); }
        finally { closeSync(fd); }
        this.pendingIdentity = { projectId: marker.projectId, operationId: marker.operationId };
        this.recoveryCommit = commit;
        checkAuthority();
        await source.commitMarker({ markerPath: this.recoveryPath, markerSha256,
          markerIdentity: { device: info.dev.toString(), inode: info.ino.toString(), birthtimeNs: info.birthtimeNs.toString() },
          commitKey, checkAuthority });
        // Even a confirmed commit remains suspended: pending is retained until
        // a crash-safe original receipt recovery protocol is independently proven.
        return false;
      } catch { return false; }
      finally {
        if (source) {
          while (true) {
            try { await source.release(); break; }
            catch (error) {
              revoked = true;
              if (error instanceof PrehostRecoveryDrainedUnknown) break;
              await new Promise<void>(resolveDelay => setTimeout(resolveDelay, 250));
            }
          }
        }
        if (revoked && !revokeDurable) {
          // Keep the serialized registry closed while the exact commit gate is
          // still owned elsewhere. No force or Job termination is permitted.
          while (!revokeDurable && !this.closed) {
            writeRevoke();
            if (!revokeDurable) await new Promise<void>(resolveDelay => setTimeout(resolveDelay, 250));
          }
        }
        if (this.recoveryCommit === commit) this.recoveryCommit = null;
      }
    });
  }

  stop(): Promise<void> {
    this.closed = true;
    this.recoveryCommit?.revoke();
    this.revokePreHost();
    return this.enqueue(() => this.retire());
  }

  private assertNotClosed(): void { if (this.closed) throw new Error("ASSISTANT_REGISTRY_CLOSED"); }
  private assertOpen(): void {
    this.assertNotClosed();
    if (this.authorityRequiredAfter || this.recovery) throw new Error("ASSISTANT_PROJECT_UNAVAILABLE");
  }
  private async suspendOrRetire(): Promise<void> {
    // A failed inventory is never an authoritative revoke. Close this channel
    // permanently, preserving local chat only after confirmed project suspension.
    this.closed = true;
    const host = this.host;
    if (host?.suspendProjects) {
      try { await host.suspendProjects(); return; }
      catch { /* Unknown suspension cannot retain the old project authority. */ }
    }
    await this.retire();
  }
  private async retire(): Promise<void> {
    this.closed = true;
    const host = this.host;
    await host?.stop();
    if (this.host === host) this.host = null;
  }
  private enqueue<T>(operation: () => Promise<T>): Promise<T> {
    const result = this.serial.then(operation);
    this.serial = result.catch(() => undefined);
    return result;
  }
}
