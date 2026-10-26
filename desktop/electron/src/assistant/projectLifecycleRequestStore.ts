import { createHash, randomBytes } from "node:crypto";
import {
  closeSync, constants, fstatSync, fsyncSync, lstatSync, mkdirSync, openSync,
  readSync, readdirSync, realpathSync, renameSync, unlinkSync, writeFileSync,
  type Stats,
} from "node:fs";
import { isAbsolute, join, parse, resolve } from "node:path";

export type LifecycleWriteOperation = "start" | "stop" | "restart";
export type LifecycleRequestIdentity = { requestId: string; projectId: string; operation: LifecycleWriteOperation };
export type LifecycleRequestBinding = { workspaceRoot: string; runtimeManagerDir: string; registryFingerprint: string };
export type LifecycleNativeCommand = { commandId: string; type: "open" | "close" | "restart"; operation: LifecycleWriteOperation };
export type LifecycleRequestRecord = {
  schemaVersion: 1;
  request: LifecycleRequestIdentity;
  binding: LifecycleRequestBinding | null;
  command: LifecycleNativeCommand | null;
};
type StoredRecord = LifecycleRequestRecord & { reservationToken: string };
type FileIdentity = { dev: number; ino: number };

export class AssistantProjectLifecycleRequestStoreError extends Error {
  constructor(readonly code: string) { super(code); this.name = "AssistantProjectLifecycleRequestStoreError"; }
}

const MAX_RECORD_BYTES = 16 * 1024;
const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/;
const COMMAND_ID = /^cmd_[A-Za-z0-9][A-Za-z0-9_-]{0,159}$/;
const HEX = /^[a-f0-9]{64}$/;
const OPERATIONS = new Set(["start", "stop", "restart"]);
const TYPES = { start: "open", stop: "close", restart: "restart" } as const;
const fail = (code: string): never => { throw new AssistantProjectLifecycleRequestStoreError(code); };
const errorCode = (error: unknown) => (error as NodeJS.ErrnoException | null)?.code;
const sameFile = (a: FileIdentity, b: FileIdentity) => a.dev === b.dev && a.ino === b.ino;
const pathKey = (path: string) => process.platform === "win32" ? path.toLowerCase() : path;
const fileName = (requestId: string) => `${createHash("sha256").update(requestId, "utf8").digest("hex")}.json`;

/** Inspect descriptors before reading fields: no accessors, symbols, or inherited input. */
function closed(value: unknown, expected: readonly string[], code = "request_invalid"): Record<string, unknown> {
  try {
    if (value === null || typeof value !== "object" || Array.isArray(value)
      || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return fail(code);
    const keys = Reflect.ownKeys(value);
    if (keys.length !== expected.length || !expected.every(key => keys.includes(key))) return fail(code);
    const result: Record<string, unknown> = {};
    for (const key of expected) {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (!descriptor || !Object.hasOwn(descriptor, "value") || !descriptor.enumerable) return fail(code);
      result[key] = descriptor.value;
    }
    return result;
  } catch { return fail(code); }
}
function opaque(value: unknown, code = "request_invalid"): string {
  if (typeof value !== "string" || !OPAQUE_ID.test(value)
    || /^(?:https?|file|data|javascript|mailto|ftp|wss?):/i.test(value)) return fail(code);
  return value;
}
function identity(value: unknown, code = "request_invalid"): LifecycleRequestIdentity {
  const input = closed(value, ["requestId", "projectId", "operation"], code);
  if (typeof input.operation !== "string" || !OPERATIONS.has(input.operation)) return fail(code);
  return { requestId: opaque(input.requestId, code), projectId: opaque(input.projectId, code),
    operation: input.operation as LifecycleWriteOperation };
}
/** Shared closed input validation for admission and read-only receipt lookup. */
export function normalizeLifecycleRequest(value: unknown): LifecycleRequestIdentity { return identity(value); }
function absolute(value: unknown, code: string): string {
  if (typeof value !== "string" || !value || value !== value.trim() || value.includes("\0")
    || !isAbsolute(value) || (process.platform === "win32" && /^(?:\\\\[?.]\\|\\(?!\\))/.test(value))) return fail(code);
  return value;
}
function bindingValue(value: unknown, code = "request_invalid"): LifecycleRequestBinding {
  const input = closed(value, ["workspaceRoot", "runtimeManagerDir", "registryFingerprint"], code);
  if (typeof input.registryFingerprint !== "string" || !/^[a-fA-F0-9]{64}$/.test(input.registryFingerprint)) return fail(code);
  return { workspaceRoot: absolute(input.workspaceRoot, code), runtimeManagerDir: absolute(input.runtimeManagerDir, code),
    registryFingerprint: input.registryFingerprint };
}
function commandValue(value: unknown, request: LifecycleRequestIdentity, code = "request_invalid"): LifecycleNativeCommand {
  const input = closed(value, ["commandId", "type", "operation"], code);
  if (typeof input.commandId !== "string" || !COMMAND_ID.test(input.commandId)
    || typeof input.operation !== "string" || !OPERATIONS.has(input.operation)
    || input.type !== TYPES[input.operation as LifecycleWriteOperation]
    || (input.operation !== request.operation && !(request.operation === "start" && input.operation === "restart"))) return fail(code);
  return { commandId: input.commandId, type: input.type as LifecycleNativeCommand["type"],
    operation: input.operation as LifecycleWriteOperation };
}
function publicRecord(row: StoredRecord): LifecycleRequestRecord {
  return { schemaVersion: 1, request: { ...row.request }, binding: row.binding && { ...row.binding }, command: row.command && { ...row.command } };
}

/** References only. Native queue/results remain the execution and receipt authorities.
 * Synchronous filesystem transactions do not yield between capacity check, wx creation,
 * and fsync in the single Electron-main writer. wx also arbitrates duplicate IDs.
 */
export class AssistantProjectLifecycleRequestStore {
  private readonly directory: string;
  private readonly maxRequests: number;
  private readonly rootIdentity: FileIdentity;
  private readonly ancestors = new Map<string, { identity: FileIdentity; physicalPath: string }>();
  private readonly ownedReservations = new Map<string, string>();

  constructor(options: { directory: string; maxRequests?: number }) {
    let hasMaximum = false;
    try { hasMaximum = Object.hasOwn(options, "maxRequests"); } catch { fail("request_invalid"); }
    const input = closed(options, hasMaximum ? ["directory", "maxRequests"] : ["directory"]);
    this.directory = resolve(absolute(input.directory, "request_invalid"));
    if (input.maxRequests !== undefined && typeof input.maxRequests !== "number") fail("request_invalid");
    this.maxRequests = input.maxRequests === undefined ? 1024 : input.maxRequests as number;
    if (!Number.isSafeInteger(this.maxRequests) || this.maxRequests < 1) fail("request_invalid");
    try {
      this.checkAncestors(true);
      mkdirSync(this.directory, { recursive: true });
      this.checkAncestors();
      this.rootIdentity = lstatSync(this.directory);
      this.inventory();
    } catch (error) { this.rethrow(error, "request_store_read_failed"); }
  }

  async reserve(request: LifecycleRequestIdentity): Promise<{ created: boolean; record: LifecycleRequestRecord; reservationToken?: string }> {
    const captured = identity(request);
    try {
      const rows = this.inventory();
      const name = fileName(captured.requestId);
      const existing = rows.get(name);
      if (existing) {
        this.assertRequest(existing, captured);
        return { created: false, record: publicRecord(existing) };
      }
      if (rows.size >= this.maxRequests) return fail("request_limit_exceeded");
      const reservationToken = randomBytes(32).toString("hex");
      const row: StoredRecord = { schemaVersion: 1, request: captured, binding: null, command: null, reservationToken };
      let descriptor: number;
      try { descriptor = openSync(join(this.directory, name), "wx", 0o600); }
      catch (error) {
        if (errorCode(error) !== "EEXIST") throw error;
        const winner = this.readRecord(name);
        this.assertRequest(winner, captured);
        return { created: false, record: publicRecord(winner) };
      }
      // A failed/truncated reservation is deliberately retained. No retry may
      // treat an uncertain native dispatch as a new request.
      try { writeFileSync(descriptor, this.serialize(row), "utf8"); fsyncSync(descriptor); }
      finally { closeSync(descriptor); }
      this.syncDirectory();
      this.assertDirectory();
      const persisted = this.readRecord(name);
      if (JSON.stringify(persisted) !== JSON.stringify(row)) fail("request_store_invalid");
      this.ownedReservations.set(captured.requestId, reservationToken);
      return { created: true, record: publicRecord(row), reservationToken };
    } catch (error) { return this.rethrow(error, "request_store_write_failed"); }
  }

  async bind(request: LifecycleRequestIdentity, reservationToken: string, binding: LifecycleRequestBinding,
    command: LifecycleNativeCommand): Promise<LifecycleRequestRecord> {
    const captured = identity(request), capturedBinding = bindingValue(binding), capturedCommand = commandValue(command, captured);
    if (typeof reservationToken !== "string" || !HEX.test(reservationToken)
      || this.ownedReservations.get(captured.requestId) !== reservationToken) return fail("reservation_invalid");
    try {
      const name = fileName(captured.requestId), row = this.inventory().get(name);
      if (!row || row.reservationToken !== reservationToken) return fail("reservation_invalid");
      this.assertRequest(row, captured);
      if (row.binding || row.command) {
        if (JSON.stringify(row.binding) !== JSON.stringify(capturedBinding) || JSON.stringify(row.command) !== JSON.stringify(capturedCommand)) {
          return fail("binding_conflict");
        }
        return publicRecord(row);
      }
      const next: StoredRecord = { ...row, binding: capturedBinding, command: capturedCommand };
      this.atomicBind(name, row, next);
      return publicRecord(next);
    } catch (error) { return this.rethrow(error, "request_store_write_failed"); }
  }

  async get(requestId: string): Promise<LifecycleRequestRecord | null> {
    const name = fileName(opaque(requestId));
    try { const row = this.inventory().get(name); return row ? publicRecord(row) : null; }
    catch (error) { return this.rethrow(error, "request_store_read_failed"); }
  }

  private assertRequest(row: StoredRecord, request: LifecycleRequestIdentity): void {
    if (JSON.stringify(row.request) !== JSON.stringify(request)) fail("request_conflict");
  }

  private checkAncestors(allowMissing = false): void {
    let current = parse(this.directory).root;
    const parts = this.directory.slice(current.length).split(/[\\/]/).filter(Boolean);
    for (const part of ["", ...parts]) {
      if (part) current = join(current, part);
      let info: Stats;
      try { info = lstatSync(current); }
      catch (error) { if (allowMissing && errorCode(error) === "ENOENT") return; throw error; }
      if (!info.isDirectory() || info.isSymbolicLink()) fail("request_store_invalid");
      const physicalPath = pathKey(realpathSync.native(current)), previous = this.ancestors.get(current);
      if (previous && (!sameFile(previous.identity, info) || previous.physicalPath !== physicalPath)) fail("request_store_invalid");
      if (!previous) this.ancestors.set(current, { identity: info, physicalPath });
    }
  }

  private assertDirectory(): void {
    this.checkAncestors();
    if (!sameFile(this.rootIdentity, lstatSync(this.directory))) fail("request_store_invalid");
  }

  private inventory(): Map<string, StoredRecord> {
    this.assertDirectory();
    const names = readdirSync(this.directory);
    if (names.length > this.maxRequests) fail("request_limit_exceeded");
    const rows = new Map<string, StoredRecord>();
    for (const name of names) {
      if (!/^[a-f0-9]{64}\.json$/.test(name)) fail("request_store_invalid");
      rows.set(name, this.readRecord(name));
    }
    return rows;
  }

  private readRecord(name: string): StoredRecord {
    this.assertDirectory();
    const path = join(this.directory, name), info = lstatSync(path);
    if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || info.size < 1 || info.size > MAX_RECORD_BYTES) fail("request_store_invalid");
    const descriptor = openSync(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0));
    let raw: string;
    try {
      const opened = fstatSync(descriptor);
      if (!sameFile(info, opened) || opened.nlink !== 1 || opened.size !== info.size) fail("request_store_invalid");
      const bytes = Buffer.alloc(MAX_RECORD_BYTES + 1);
      let length = 0, count: number;
      do { count = readSync(descriptor, bytes, length, bytes.length - length, null); length += count; }
      while (count > 0 && length < bytes.length);
      const after = fstatSync(descriptor);
      if (length !== info.size || length > MAX_RECORD_BYTES || !sameFile(opened, after)
        || after.nlink !== 1 || after.size !== info.size || after.mtimeMs !== opened.mtimeMs || after.ctimeMs !== opened.ctimeMs) fail("request_store_invalid");
      raw = bytes.subarray(0, length).toString("utf8");
      if (!bytes.subarray(0, length).equals(Buffer.from(raw, "utf8"))) fail("request_store_invalid");
    } finally { closeSync(descriptor); }
    this.assertDirectory();
    const after = lstatSync(path);
    if (!sameFile(info, after) || after.isSymbolicLink() || after.nlink !== 1) fail("request_store_invalid");
    let parsed: unknown;
    try { parsed = JSON.parse(raw); } catch { return fail("request_store_invalid"); }
    const row = closed(parsed, ["schemaVersion", "request", "binding", "command", "reservationToken"], "request_store_invalid");
    if (row.schemaVersion !== 1 || typeof row.reservationToken !== "string" || !HEX.test(row.reservationToken)
      || (row.binding === null) !== (row.command === null)) return fail("request_store_invalid");
    const request = identity(row.request, "request_store_invalid");
    if (fileName(request.requestId) !== name) fail("request_store_invalid");
    return { schemaVersion: 1, request,
      binding: row.binding === null ? null : bindingValue(row.binding, "request_store_invalid"),
      command: row.command === null ? null : commandValue(row.command, request, "request_store_invalid"),
      reservationToken: row.reservationToken };
  }

  private serialize(row: StoredRecord): string {
    const raw = `${JSON.stringify(row)}\n`;
    if (Buffer.byteLength(raw, "utf8") > MAX_RECORD_BYTES) fail("request_invalid");
    return raw;
  }

  private atomicBind(name: string, previous: StoredRecord, next: StoredRecord): void {
    const path = join(this.directory, name), temp = join(this.directory, `${name}.${randomBytes(16).toString("hex")}.tmp`);
    const raw = this.serialize(next);
    const descriptor = openSync(temp, "wx", 0o600);
    try {
      try { writeFileSync(descriptor, raw, "utf8"); fsyncSync(descriptor); }
      finally { closeSync(descriptor); }
      this.assertDirectory();
      if (JSON.stringify(this.readRecord(name)) !== JSON.stringify(previous)) fail("binding_conflict");
      renameSync(temp, path);
      this.syncDirectory();
      if (JSON.stringify(this.readRecord(name)) !== JSON.stringify(next)) fail("request_store_invalid");
    } finally {
      // Only our unpublished temp is disposable; never repair/delete a record.
      try { unlinkSync(temp); } catch (error) { if (errorCode(error) !== "ENOENT") this.rethrow(error, "request_store_write_failed"); }
    }
  }

  private syncDirectory(): void {
    // Windows does not expose directory fsync through Node. File fsync above
    // is mandatory on every platform; POSIX also flushes directory entries.
    if (process.platform === "win32") return;
    const descriptor = openSync(this.directory, "r");
    try { fsyncSync(descriptor); } finally { closeSync(descriptor); }
  }

  private rethrow(error: unknown, fallback: string): never {
    if (error instanceof AssistantProjectLifecycleRequestStoreError) throw error;
    return fail(fallback);
  }
}
