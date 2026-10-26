import { randomUUID } from "node:crypto";
import { lstatSync, readFileSync, realpathSync, statSync } from "node:fs";
import { posix, win32 } from "node:path";

import { writeLauncherStateFile } from "../process/workbenchBackend.js";

export type AssistantProjectCandidate = { projectId: string; root: string; checkedOut: boolean };
export type AssistantProjectRegistrySnapshot = {
  schemaVersion: 1;
  revision: number;
  projects: Record<string, string>;
};
export type AssistantProjectRegistration = {
  integrationRoot: string;
  baseProjectId: string;
  root: string;
  registrationUuid: string;
  active: boolean;
};
type StoredRegistry = { schemaVersion: 1; revision: number; registrations: AssistantProjectRegistration[] };
export type AssistantProjectRegistryOptions = {
  filePath: string;
  /** Trusted filesystem seams for tests; none are renderer capabilities. */
  platform?: NodeJS.Platform;
  isDirectory?: (path: string) => boolean;
  realPath?: (path: string) => string;
  /** Same atomic JSON contract/format as writeLauncherStateFile. */
  writeFile?: (path: string, payload: Record<string, unknown>) => Promise<void>;
};

export class AssistantProjectRegistryError extends Error {
  constructor(readonly code: string) { super(code); }
}

export const MAX_ASSISTANT_PROJECTS = 128;
const MAX_BYTES = 4 * 1024 * 1024;
const BASE_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const fail = (code: string): never => { throw new AssistantProjectRegistryError(code); };
function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function keys(value: Record<string, unknown>, expected: string[]): boolean {
  return Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key));
}
function absolutePath(value: unknown, platform: NodeJS.Platform): string {
  if (typeof value !== "string" || !value || value !== value.trim() || value.includes("\0")) {
    return fail("PROJECT_REGISTRY_INVALID");
  }
  const api = platform === "win32" ? win32 : posix;
  let path = value;
  if (platform === "win32") {
    path = path.replaceAll("/", "\\");
    if (path.toLowerCase().startsWith("\\\\?\\unc\\")) path = `\\\\${path.slice(8)}`;
    else if (path.startsWith("\\\\?\\")) path = path.slice(4);
    if (path.startsWith("\\\\.\\") || !/^(?:[A-Za-z]:\\|\\\\[^\\]+\\[^\\]+(?:\\|$))/.test(path)) return fail("PROJECT_REGISTRY_INVALID");
  }
  if (!api.isAbsolute(path)) return fail("PROJECT_REGISTRY_INVALID");
  path = api.resolve(path);
  if (path.length > api.parse(path).root.length) path = path.replace(/[\\/]+$/, "");
  return platform === "win32" ? path.toLowerCase() : path;
}
function directoryExists(path: string): boolean {
  try { return statSync(path).isDirectory(); }
  catch (error: unknown) {
    if (["ENOENT", "ENOTDIR"].includes((error as NodeJS.ErrnoException)?.code ?? "")) return false;
    throw error;
  }
}

/** One Electron-main writer. Git/native inventory supplies candidates, never a model or renderer. */
export class AssistantProjectRegistry {
  private readonly filePath: string;
  private readonly platform: NodeJS.Platform;
  private readonly isDirectory: (path: string) => boolean;
  private readonly realPath: (path: string) => string;
  private readonly writeFile: NonNullable<AssistantProjectRegistryOptions["writeFile"]>;
  private stored: StoredRegistry;
  private raw: string | null;
  private serial: Promise<void> = Promise.resolve();

  constructor(options: AssistantProjectRegistryOptions) {
    this.filePath = absolutePath(options.filePath, process.platform);
    this.platform = options.platform ?? process.platform;
    this.isDirectory = options.isDirectory ?? directoryExists;
    this.realPath = options.realPath ?? (path => realpathSync.native(path));
    this.writeFile = options.writeFile ?? writeLauncherStateFile;
    this.raw = this.readRaw();
    this.stored = this.raw === null ? { schemaVersion: 1, revision: 0, registrations: [] } : this.parse(this.raw);
  }

  snapshot(): AssistantProjectRegistrySnapshot {
    this.assertDiskUnchanged();
    return this.project(this.stored);
  }

  /** Main-only lifecycle metadata. Roots and epochs remain one registry authority. */
  registration(projectId: string): AssistantProjectRegistration | null {
    const snapshot = this.snapshot();
    if (!Object.hasOwn(snapshot.projects, projectId)) return null;
    const row = this.stored.registrations.find(item => item.active && `${item.baseProjectId}:${item.registrationUuid}` === projectId);
    return row ? { ...row } : null;
  }

  async reconcile(integrationRoot: string, candidates: readonly AssistantProjectCandidate[]): Promise<AssistantProjectRegistrySnapshot> {
    if (!Array.isArray(candidates)) return fail("PROJECT_REGISTRY_INVALID");
    // Capture caller-owned arrays before waiting behind another persistence.
    const input = candidates.map(candidate => ({ ...candidate }));
    const operation = this.serial.then(() => this.reconcileNow(integrationRoot, input));
    this.serial = operation.then(() => undefined, () => undefined);
    return operation;
  }

  private async reconcileNow(integrationRoot: string, candidates: AssistantProjectCandidate[]): Promise<AssistantProjectRegistrySnapshot> {
    this.assertDiskUnchanged();
    const group = absolutePath(integrationRoot, this.platform);
    const desired = new Map<string, { baseProjectId: string; root: string }>();
    const bases = new Set<string>(), roots = new Set<string>();
    for (const candidate of candidates) {
      if (!record(candidate) || !keys(candidate, ["projectId", "root", "checkedOut"])
        || typeof candidate.checkedOut !== "boolean") return fail("PROJECT_REGISTRY_INVALID");
      if (!candidate.checkedOut) continue;
      if (typeof candidate.projectId !== "string" || !BASE_ID.test(candidate.projectId)) return fail("PROJECT_REGISTRY_INVALID");
      const normalized = absolutePath(candidate.root, this.platform);
      const root = this.directory(normalized) ? this.physicalPath(normalized) : normalized;
      if (bases.has(candidate.projectId) || roots.has(root)) return fail("PROJECT_REGISTRY_CONFLICT");
      bases.add(candidate.projectId);
      roots.add(root);
      if (!this.directory(root)) continue;
      desired.set(JSON.stringify([candidate.projectId, root]), { baseProjectId: candidate.projectId, root });
    }

    const registrations = this.stored.registrations.map(row => {
      if (!row.active || row.integrationRoot !== group) return { ...row };
      const identity = JSON.stringify([row.baseProjectId, row.root]);
      const active = desired.delete(identity);
      return { ...row, active };
    });
    const uuids = new Set(registrations.map(row => row.registrationUuid));
    for (const item of [...desired.values()].sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))) {
      const registrationUuid = randomUUID();
      if (uuids.has(registrationUuid)) return fail("PROJECT_REGISTRY_CONFLICT");
      uuids.add(registrationUuid);
      registrations.push({ integrationRoot: group, ...item, registrationUuid, active: true });
    }
    this.validateActive(registrations, "PROJECT_REGISTRY_CONFLICT");
    if (JSON.stringify(registrations) === JSON.stringify(this.stored.registrations)) return this.project(this.stored);
    const revision = this.stored.revision + 1;
    if (!Number.isSafeInteger(revision)) return fail("PROJECT_REGISTRY_INVALID");
    const next: StoredRegistry = { schemaVersion: 1, revision, registrations };
    // Validate the entire resulting permission table before publication. A
    // missing root in another group needs that group's explicit reconcile.
    const snapshot = this.project(next);
    const raw = `${JSON.stringify(next, null, 2)}\n`;
    if (Buffer.byteLength(raw, "utf8") > MAX_BYTES) return fail("PROJECT_REGISTRY_INVALID");
    try { await this.writeFile(this.filePath, next); }
    catch { return fail("PROJECT_REGISTRY_WRITE_FAILED"); }
    this.stored = next;
    this.raw = raw;
    return snapshot;
  }

  private readRaw(): string | null {
    try {
      const info = lstatSync(this.filePath);
      if (!info.isFile() || info.isSymbolicLink() || info.size > MAX_BYTES) return fail("PROJECT_REGISTRY_INVALID");
      return readFileSync(this.filePath, "utf8");
    } catch (error: unknown) {
      if ((error as NodeJS.ErrnoException)?.code === "ENOENT") return null;
      if (error instanceof AssistantProjectRegistryError) throw error;
      return fail("PROJECT_REGISTRY_READ_FAILED");
    }
  }

  private assertDiskUnchanged(): void {
    if (this.readRaw() !== this.raw) fail("PROJECT_REGISTRY_CHANGED");
  }

  private parse(raw: string): StoredRegistry {
    let value: unknown;
    try { value = JSON.parse(raw); } catch { return fail("PROJECT_REGISTRY_INVALID"); }
    if (!record(value) || !keys(value, ["schemaVersion", "revision", "registrations"])
      || value.schemaVersion !== 1 || !Number.isSafeInteger(value.revision) || Number(value.revision) < 0
      || !Array.isArray(value.registrations) || (value.revision === 0 && value.registrations.length)) return fail("PROJECT_REGISTRY_INVALID");
    const uuids = new Set<string>();
    const registrations: AssistantProjectRegistration[] = [];
    for (const row of value.registrations) {
      if (!record(row) || !keys(row, ["integrationRoot", "baseProjectId", "root", "registrationUuid", "active"])
        || typeof row.baseProjectId !== "string" || !BASE_ID.test(row.baseProjectId)
        || typeof row.registrationUuid !== "string" || !UUID.test(row.registrationUuid)
        || uuids.has(row.registrationUuid) || typeof row.active !== "boolean") return fail("PROJECT_REGISTRY_INVALID");
      const integrationRoot = absolutePath(row.integrationRoot, this.platform), root = absolutePath(row.root, this.platform);
      if (integrationRoot !== row.integrationRoot || root !== row.root) return fail("PROJECT_REGISTRY_INVALID");
      uuids.add(row.registrationUuid);
      registrations.push({ integrationRoot, baseProjectId: row.baseProjectId, root,
        registrationUuid: row.registrationUuid, active: row.active });
    }
    this.validateActive(registrations, "PROJECT_REGISTRY_INVALID");
    return { schemaVersion: 1, revision: Number(value.revision), registrations };
  }

  private validateActive(registrations: AssistantProjectRegistration[], code: string): void {
    const active = registrations.filter(row => row.active);
    if (active.length > MAX_ASSISTANT_PROJECTS) fail("PROJECT_REGISTRY_LIMIT_EXCEEDED");
    const roots = new Set<string>(), bases = new Set<string>();
    for (const row of active) {
      if (roots.has(row.root) || bases.has(row.baseProjectId)) fail(code);
      roots.add(row.root);
      bases.add(row.baseProjectId);
    }
  }

  private directory(path: string): boolean {
    try { return this.isDirectory(path); } catch { return fail("PROJECT_REGISTRY_FILESYSTEM_FAILED"); }
  }

  private physicalPath(path: string): string {
    try { return absolutePath(this.realPath(path), this.platform); }
    catch { return fail("PROJECT_REGISTRY_FILESYSTEM_FAILED"); }
  }

  private project(stored: StoredRegistry): AssistantProjectRegistrySnapshot {
    const entries: Array<[string, string]> = [];
    for (const row of stored.registrations.filter(row => row.active)) {
      if (!this.directory(row.root) || this.physicalPath(row.root) !== row.root) fail("PROJECT_REGISTRY_RECONCILE_REQUIRED");
      entries.push([`${row.baseProjectId}:${row.registrationUuid}`, row.root]);
    }
    return { schemaVersion: 1, revision: stored.revision,
      projects: Object.fromEntries(entries.sort(([a], [b]) => a.localeCompare(b))) };
  }
}
