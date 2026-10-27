import { createHash } from "node:crypto";
import { realpathSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";

import { readProjectId } from "../lifecycle/projectStoragePaths.js";
import { AssistantProjectRegistry, type AssistantProjectRegistrySnapshot, type AssistantProjectRegistration } from "./projectRegistry.js";

type ProjectHost = {
  start(): Promise<unknown>;
  stop(): Promise<unknown>;
  updateProjects(snapshot: AssistantProjectRegistrySnapshot): Promise<void>;
  suspendProjects?(): Promise<void>;
};
type Inventory = { integrationRoot: string; items: Array<{ id: string; path: string; checkedOut: boolean }> };
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

/** Electron-main connection only. No renderer input, instance history, or directory discovery. */
export class AssistantProjectRegistryConnection {
  private readonly registry: AssistantProjectRegistry;
  private serial: Promise<unknown> = Promise.resolve();
  private host: ProjectHost | null = null;
  private acknowledgedRevision = -1;
  private projectsSuspended = false;
  private closed = false;

  constructor(filePath: string) {
    this.registry = new AssistantProjectRegistry({ filePath });
  }

  /** Trusted main callers only; both reads retain disk/physical-root validation. */
  snapshot(): AssistantProjectRegistrySnapshot { this.assertOpen(); return this.registry.snapshot(); }
  registration(projectId: string): AssistantProjectRegistration | null { this.assertOpen(); return this.registry.registration(projectId); }

  /** Main-only lease: reconciliation and retirement wait until import settles. */
  withHistoryImport<T>(projectId: string, operation: (revision: number) => Promise<T>): Promise<T> {
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

  start<T extends ProjectHost>(createHost: (snapshot: AssistantProjectRegistrySnapshot, projectsSuspended: boolean) => T): Promise<T> {
    return this.enqueue(async () => {
      this.assertOpen();
      if (this.host) throw new Error("ASSISTANT_ALREADY_STARTED");
      const { snapshot, projectsSuspended } = this.registry.startupState();
      const host = createHost(snapshot, projectsSuspended);
      this.host = host;
      await host.start();
      this.acknowledgedRevision = snapshot.revision;
      this.projectsSuspended = projectsSuspended;
      return host;
    });
  }

  reconcile(payload: unknown): Promise<void> {
    // Capture and validate every row before queuing: a dropped malformed row
    // must never turn an incomplete observation into an authoritative revoke.
    let input: Inventory;
    try { input = inventory(payload); }
    catch (error) { return Promise.reject(error); }
    return this.enqueue(async () => {
      this.assertOpen();
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
      if (this.host && (snapshot.revision > this.acknowledgedRevision || this.projectsSuspended)) {
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
    });
  }

  stop(): Promise<void> {
    this.closed = true;
    return this.enqueue(() => this.retire());
  }

  private assertOpen(): void { if (this.closed) throw new Error("ASSISTANT_REGISTRY_CLOSED"); }
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
