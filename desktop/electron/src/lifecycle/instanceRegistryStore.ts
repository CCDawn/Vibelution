import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";
import { createServer } from "node:net";

import { withInstanceLock, type InstanceLockOptions } from "./instanceLock.js";

export const REGISTRY_SCHEMA_VERSION = 3;
export const DEFAULT_BACKEND_PORT = 8000;
export const DEFAULT_CONTROL_PORT = 8765;
export const PORT_SCAN_LIMIT = 64;
export const IN_FLIGHT_STATUSES = new Set(["starting", "restarting", "stopping"]);
export const PORT_LEASE_RECLAIMABLE = new Set(["quarantined", "reclaimable"]);
export const ISOLATED_START_TIMEOUT_SECONDS = 180;
export const OWNER_LEASE_TTL_MS = 15_000;
export const OWNER_LEASE_HEARTBEAT_MS = 5_000;
export const START_SUPERVISOR_LOST_MESSAGE = "启动监督进程已退出且超过启动期限，启动未完成。";

export type RegistryPayload = {
  schemaVersion: number;
  updatedAt?: string;
  instances: Record<string, RegistryEntry>;
};

export type RegistryEntry = {
  schemaVersion?: number;
  updatedAt?: string;
  projectRoot?: string;
  branch?: string;
  port?: number;
  controlPort?: number;
  host?: string;
  url?: string;
  status?: string;
  desiredState?: string;
  phase?: string;
  generation?: number;
  commandId?: string;
  deadlineAt?: string;
  inFlightDeadlineAt?: string;
  failureMessage?: string;
  spawnPid?: number;
  spawnCreateTime?: number;
  spawnExecutable?: string;
  windowPid?: number;
  ownerPid?: number;
  ownerLease?: OwnerLease | Record<string, unknown>;
  startedAt?: string;
  portLeaseStatus?: string;
  slotKey?: string;
  slotId?: string;
  cleanupInProgress?: boolean;
  dataHome?: string;
  [key: string]: unknown;
};

export type OwnerLease = {
  ownerId: string;
  expiresAt: string;
};

export type PortIsFree = (port: number, host: string) => boolean | Promise<boolean>;

export type ClaimStartInput = {
  instanceId: string;
  projectRoot: string;
  branch?: string;
  operation?: "start" | "restart";
  commandId: string;
  deadlineAt: string;
  startedAt?: string;
  ownerPid: number;
  ownerId?: string;
  nowMs?: number;
  alive?: boolean;
  preferredBackend?: number;
  preferredControl?: number;
  extraUsed?: number[];
  host?: string;
  slotFields?: Record<string, unknown>;
  portIsFree?: PortIsFree;
};

export type ClaimStartOk = {
  ok: true;
  entry: RegistryEntry;
};

export type ClaimStartBusy = {
  ok: false;
  code: "instance_busy";
  instanceId: string;
  status: string;
  generation: number;
};

export type ClaimStartResult = ClaimStartOk | ClaimStartBusy;

export type ObserveResult = {
  applied: boolean;
  entry: RegistryEntry;
};

export type UpsertResult = {
  applied: boolean;
  entry: RegistryEntry;
};

export class InstanceBusyError extends Error {
  readonly code = "instance_busy";
  readonly instanceId: string;
  readonly status: string;
  readonly generation: number;

  constructor(instanceId: string, status: string, generation: number) {
    super(`instance ${instanceId} is busy (${status || "in-flight"} generation=${generation})`);
    this.name = "InstanceBusyError";
    this.instanceId = instanceId;
    this.status = status;
    this.generation = generation;
  }
}

export function emptyRegistry(): RegistryPayload {
  return { schemaVersion: REGISTRY_SCHEMA_VERSION, instances: {} };
}

export function instancesRegistryPath(env: NodeJS.Dict<string> = process.env): string {
  const local = String(env.LOCALAPPDATA || "").trim();
  const root = local || join(String(env.USERPROFILE || env.HOME || ""), "AppData", "Local");
  return join(root, "Vibelution", "instances.json");
}

export function loopbackUrl(port: number): string {
  return `http://127.0.0.1:${Math.trunc(port)}`;
}

export function toIsoUtc(nowMs: number): string {
  return new Date(nowMs).toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function isolatedStartDeadlineAt(nowMs = Date.now()): string {
  return toIsoUtc(nowMs + ISOLATED_START_TIMEOUT_SECONDS * 1000);
}

export function parseTimestampMs(value: unknown): number | null {
  const text = String(value || "").trim();
  if (!text) {
    return null;
  }
  const parsed = Date.parse(text);
  return Number.isFinite(parsed) ? parsed : null;
}

export function remainingDeadlineMs(deadlineAt: string | undefined, nowMs = Date.now()): number {
  const deadline = parseTimestampMs(deadlineAt);
  if (deadline === null) {
    return ISOLATED_START_TIMEOUT_SECONDS * 1000;
  }
  return Math.max(0, deadline - nowMs);
}

export function ownerLeaseOf(entry: RegistryEntry | undefined): OwnerLease | null {
  const raw = entry?.ownerLease;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return null;
  }
  const ownerId = String((raw as { ownerId?: unknown }).ownerId || "").trim();
  const expiresAt = String((raw as { expiresAt?: unknown }).expiresAt || "").trim();
  if (!ownerId && !expiresAt) {
    return null;
  }
  return { ownerId, expiresAt };
}

export function ownerLeaseExpired(entry: RegistryEntry | undefined, nowMs = Date.now()): boolean {
  const lease = ownerLeaseOf(entry);
  if (!lease?.expiresAt) {
    return true;
  }
  const expires = parseTimestampMs(lease.expiresAt);
  if (expires === null) {
    return true;
  }
  return nowMs >= expires;
}

export function deadlineExpired(entry: RegistryEntry | undefined, nowMs = Date.now()): boolean {
  const deadline = parseTimestampMs(entry?.inFlightDeadlineAt || entry?.deadlineAt);
  if (deadline === null) {
    return false;
  }
  return nowMs >= deadline;
}

export function isStaleInFlightStart(
  entry: RegistryEntry | undefined,
  input: {
    nowMs?: number;
    backendAlive?: boolean;
    backendListening?: boolean;
    windowOpen?: boolean;
  } = {}
): boolean {
  if (!entry) {
    return false;
  }
  const status = statusOf(entry);
  if (status !== "starting" && status !== "restarting") {
    return false;
  }
  if (String(entry.desiredState || "").trim().toLowerCase() !== "open") {
    return false;
  }
  if (input.backendAlive || input.backendListening || input.windowOpen) {
    return false;
  }
  const nowMs = input.nowMs ?? Date.now();
  return deadlineExpired(entry, nowMs) && ownerLeaseExpired(entry, nowMs);
}

export function isStaleInFlightStop(
  entry: RegistryEntry | undefined,
  input: { nowMs?: number } = {}
): boolean {
  if (!entry || statusOf(entry) !== "stopping") {
    return false;
  }
  if (String(entry.desiredState || "").trim().toLowerCase() !== "closed") {
    return false;
  }
  const nowMs = input.nowMs ?? Date.now();
  return deadlineExpired(entry, nowMs) && ownerLeaseExpired(entry, nowMs);
}

export function buildOwnerLease(input: { ownerId?: string; ownerPid?: number; nowMs?: number }): OwnerLease {
  const ownerId =
    String(input.ownerId || "").trim() ||
    (positiveInt(input.ownerPid) > 0 ? `pid:${positiveInt(input.ownerPid)}` : "");
  const nowMs = input.nowMs ?? Date.now();
  return {
    ownerId,
    expiresAt: toIsoUtc(nowMs + OWNER_LEASE_TTL_MS)
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function positiveInt(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : 0;
}

function statusOf(entry: RegistryEntry | undefined): string {
  return String(entry?.status || "").trim().toLowerCase();
}

function ensurePayload(raw: unknown): RegistryPayload {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new Error("instances registry is corrupt: root must be an object");
  }
  const record = raw as Record<string, unknown>;
  const instancesRaw = record.instances;
  if (typeof instancesRaw !== "object" || instancesRaw === null || Array.isArray(instancesRaw)) {
    throw new Error("instances registry is corrupt: instances must be an object");
  }
  const instances: Record<string, RegistryEntry> = {};
  for (const [key, value] of Object.entries(instancesRaw)) {
    if (!key.trim() || typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new Error("instances registry is corrupt: invalid instance entry");
    }
    instances[key] = { ...(value as RegistryEntry) };
  }
  return {
    schemaVersion: REGISTRY_SCHEMA_VERSION,
    ...(typeof record.updatedAt === "string" ? { updatedAt: record.updatedAt } : {}),
    instances
  };
}

function ensureEntry(payload: RegistryPayload, instanceId: string): RegistryEntry {
  const existing = payload.instances[instanceId];
  if (existing) {
    return existing;
  }
  const created: RegistryEntry = {};
  payload.instances[instanceId] = created;
  return created;
}

function entryPorts(entry: RegistryEntry | undefined): Set<number> {
  const used = new Set<number>();
  if (!entry) {
    return used;
  }
  for (const key of ["port", "controlPort"] as const) {
    const port = positiveInt(entry[key]);
    if (port > 0 && port < 65536) {
      used.add(port);
    }
  }
  return used;
}

function holdsPortLease(entry: RegistryEntry): boolean {
  return !PORT_LEASE_RECLAIMABLE.has(String(entry.portLeaseStatus || "").trim().toLowerCase());
}

function registeredPorts(payload: RegistryPayload, excludeId: string): Set<number> {
  const used = new Set<number>();
  for (const [instanceId, entry] of Object.entries(payload.instances)) {
    if (excludeId && instanceId === excludeId) {
      continue;
    }
    if (holdsPortLease(entry)) {
      for (const port of entryPorts(entry)) {
        used.add(port);
      }
    }
  }
  return used;
}

export async function defaultPortIsFree(port: number, host = "127.0.0.1"): Promise<boolean> {
  const candidate = Math.trunc(port);
  if (candidate <= 0 || candidate >= 65536) {
    return false;
  }
  return new Promise((resolve) => {
    const server = createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.listen(candidate, host, () => {
      server.close(() => resolve(true));
    });
  });
}

async function pickPort(
  preferred: number,
  used: Set<number>,
  defaultBase: number,
  host: string,
  portIsFree: PortIsFree
): Promise<number> {
  let base = Math.trunc(preferred || defaultBase);
  if (base <= 0 || base >= 65536) {
    base = defaultBase;
  }
  for (let offset = 0; offset < Math.max(1, PORT_SCAN_LIMIT); offset += 1) {
    let candidate = base + offset;
    if (candidate >= 65536) {
      candidate = defaultBase + (offset % 1000);
    }
    if (candidate <= 0 || candidate >= 65536 || used.has(candidate)) {
      continue;
    }
    if (!(await Promise.resolve(portIsFree(candidate, host)))) {
      continue;
    }
    return candidate;
  }
  throw new Error(`No free port found near ${base} (scanned ${PORT_SCAN_LIMIT} candidates).`);
}

async function existingReusablePort(
  entry: RegistryEntry | undefined,
  key: "port" | "controlPort",
  used: Set<number>,
  host: string,
  portIsFree: PortIsFree
): Promise<number> {
  const existing = positiveInt(entry?.[key]);
  if (existing > 0 && !used.has(existing) && (await Promise.resolve(portIsFree(existing, host)))) {
    return existing;
  }
  return 0;
}

async function allocateBackend(
  payload: RegistryPayload,
  instanceId: string,
  preferred: number,
  host: string,
  extraUsed: Set<number>,
  portIsFree: PortIsFree
): Promise<number> {
  const used = new Set([...registeredPorts(payload, instanceId), ...extraUsed]);
  const entry = payload.instances[instanceId];
  const preferredPort =
    (await existingReusablePort(entry, "port", used, host, portIsFree)) || preferred;
  const chosen = await pickPort(preferredPort, used, DEFAULT_BACKEND_PORT, host, portIsFree);
  const stored = ensureEntry(payload, instanceId);
  stored.port = chosen;
  stored.host = host;
  return chosen;
}

async function allocateControl(
  payload: RegistryPayload,
  instanceId: string,
  preferred: number,
  host: string,
  extraUsed: Set<number>,
  portIsFree: PortIsFree
): Promise<number> {
  const used = new Set([...registeredPorts(payload, instanceId), ...extraUsed]);
  const entry = payload.instances[instanceId];
  const preferredPort =
    (await existingReusablePort(entry, "controlPort", used, host, portIsFree)) || preferred;
  const chosen = await pickPort(preferredPort, used, DEFAULT_CONTROL_PORT, host, portIsFree);
  const stored = ensureEntry(payload, instanceId);
  stored.controlPort = chosen;
  stored.host = host;
  return chosen;
}

export async function applyClaimStart(
  payload: RegistryPayload,
  input: ClaimStartInput
): Promise<ClaimStartResult> {
  const instanceId = String(input.instanceId || "").trim();
  if (!instanceId) {
    throw new Error("instance_id must not be empty");
  }
  const entry = ensureEntry(payload, instanceId);
  const currentStatus = statusOf(entry);
  if (Boolean(entry.cleanupInProgress)) {
    return {
      ok: false,
      code: "instance_busy",
      instanceId,
      status: "cleanup",
      generation: positiveInt(entry.generation)
    };
  }
  if (IN_FLIGHT_STATUSES.has(currentStatus)) {
    return {
      ok: false,
      code: "instance_busy",
      instanceId,
      status: currentStatus,
      generation: positiveInt(entry.generation)
    };
  }
  const host = input.host || "127.0.0.1";
  const extraUsed = new Set(
    (input.extraUsed || []).map((port) => Math.trunc(port)).filter((port) => port > 0)
  );
  const portIsFree = input.portIsFree || defaultPortIsFree;
  const backend = await allocateBackend(
    payload,
    instanceId,
    input.preferredBackend || DEFAULT_BACKEND_PORT,
    host,
    extraUsed,
    portIsFree
  );
  const control = await allocateControl(
    payload,
    instanceId,
    input.preferredControl || DEFAULT_CONTROL_PORT,
    host,
    new Set([...extraUsed, backend]),
    portIsFree
  );
  const status = input.operation === "restart" ? "restarting" : "starting";
  const generation = positiveInt(entry.generation) + 1;
  const nowMs = input.nowMs ?? Date.now();
  Object.assign(entry, input.slotFields || {}, {
    projectRoot: String(input.projectRoot || ""),
    branch: String(input.branch || ""),
    port: backend,
    controlPort: control,
    host,
    url: loopbackUrl(backend),
    status,
    desiredState: "open",
    phase: status,
    generation,
    commandId: String(input.commandId || ""),
    deadlineAt: input.deadlineAt,
    inFlightDeadlineAt: input.deadlineAt,
    failureMessage: "",
    portLeaseStatus: "held",
    spawnPid: 0,
    windowPid: 0,
    ownerPid: Math.trunc(input.ownerPid),
    ownerLease: buildOwnerLease({ ownerId: input.ownerId, ownerPid: input.ownerPid, nowMs }),
    startedAt: input.startedAt || input.deadlineAt
  });
  delete entry.spawnCreateTime;
  delete entry.spawnExecutable;
  return { ok: true, entry: { ...entry } };
}

export function applyClaimStop(
  payload: RegistryPayload,
  input: { instanceId: string; projectRoot?: string; nowMs?: number; commandId?: string }
): { ok: true; entry: RegistryEntry } {
  const instanceId = String(input.instanceId || "").trim();
  if (!instanceId) {
    throw new Error("instance_id must not be empty");
  }
  const entry = ensureEntry(payload, instanceId);
  const generation = positiveInt(entry.generation) + 1;
  // A stop claim must not inherit an already elapsed start deadline. Without
  // a fresh deadline, the stale-stop reconciler would release a live stop as
  // soon as the next start request acquired the lock.
  const stopDeadlineAt = toIsoUtc(
    (input.nowMs ?? Date.now()) + ISOLATED_START_TIMEOUT_SECONDS * 1000
  );
  entry.status = "stopping";
  entry.phase = "stopping";
  entry.desiredState = "closed";
  entry.generation = generation;
  entry.deadlineAt = stopDeadlineAt;
  entry.inFlightDeadlineAt = stopDeadlineAt;
  // A stop claim owns the registered handles until retirement is confirmed.
  // This also repairs legacy/partial rows that incorrectly exposed a live
  // runtime with a reclaimable port lease.
  entry.portLeaseStatus = "held";
  const commandId = String(input.commandId || "").trim();
  if (commandId) {
    entry.commandId = commandId;
  }
  entry.failureMessage = "";
  delete entry.ownerLease;
  const projectRoot = String(input.projectRoot || "").trim();
  if (projectRoot && projectRoot !== ".") {
    entry.projectRoot = projectRoot;
  }
  return { ok: true, entry: { ...entry } };
}

/**
 * Claim stop only while the caller still owns the observed generation (and,
 * when supplied, command id). The comparison and generation increment happen
 * under the same registry lock in claimStopIfGeneration, so a stale reader
 * cannot overwrite a newer lifecycle row before killing its backend.
 */
export function applyClaimStopIfGeneration(
  payload: RegistryPayload,
  input: {
    instanceId: string;
    expectedGeneration: number;
    expectedCommandId?: string;
    projectRoot?: string;
    nowMs?: number;
    commandId?: string;
  }
): ObserveResult {
  const instanceId = String(input.instanceId || "").trim();
  if (!instanceId) {
    throw new Error("instance_id must not be empty");
  }
  const entry = payload.instances[instanceId];
  if (!entry || positiveInt(entry.generation) !== positiveInt(input.expectedGeneration)) {
    return { applied: false, entry: entry ? { ...entry } : {} };
  }
  const expectedCommandId = String(input.expectedCommandId || "").trim();
  if (expectedCommandId && String(entry.commandId || "").trim() !== expectedCommandId) {
    return { applied: false, entry: { ...entry } };
  }
  const claimed = applyClaimStop(payload, input);
  return { applied: true, entry: claimed.entry };
}

/**
 * Commit a successful stop after the registered process handles have been
 * retired. The generation check keeps an older stop from closing a newer
 * start that raced with the retirement path.
 */
export function applyCompleteStop(
  payload: RegistryPayload,
  input: { instanceId: string; expectedGeneration?: number; retainWindowPid?: number }
): ObserveResult {
  const instanceId = String(input.instanceId || "").trim();
  const entry = payload.instances[instanceId];
  if (!entry) {
    return { applied: false, entry: {} };
  }
  const expected = positiveInt(input.expectedGeneration);
  const generation = positiveInt(entry.generation);
  if (expected > 0 && generation !== expected) {
    return { applied: false, entry: { ...entry } };
  }
  if (
    statusOf(entry) !== "stopping"
    || String(entry.desiredState || "").trim().toLowerCase() !== "closed"
  ) {
    return { applied: false, entry: { ...entry } };
  }
  entry.status = "closed";
  entry.phase = "steady";
  entry.desiredState = "closed";
  entry.failureMessage = "";
  entry.spawnPid = 0;
  delete entry.spawnCreateTime;
  delete entry.spawnExecutable;
  const retainedWindowPid = positiveInt(input.retainWindowPid);
  entry.windowPid = retainedWindowPid;
  if (retainedWindowPid > 0) {
    entry.lifecycleWarning = `unverified browser/window handle retained: ${retainedWindowPid}`;
  } else {
    delete entry.lifecycleWarning;
  }
  entry.portLeaseStatus = "reclaimable";
  delete entry.ownerLease;
  return { applied: true, entry: { ...entry } };
}

export function applyObserve(
  payload: RegistryPayload,
  input: {
    instanceId: string;
    operation: "observe-ready" | "observe-error";
    expectedGeneration?: number;
    message?: string;
  }
): ObserveResult {
  const instanceId = String(input.instanceId || "").trim();
  const entry = payload.instances[instanceId];
  if (!entry) {
    return { applied: false, entry: {} };
  }
  const expected = positiveInt(input.expectedGeneration);
  const currentGeneration = positiveInt(entry.generation);
  const status = statusOf(entry);
  if (expected > 0 && currentGeneration !== expected) {
    return { applied: false, entry: { ...entry } };
  }
  if (status !== "starting" && status !== "restarting") {
    return { applied: false, entry: { ...entry } };
  }
  if (input.operation === "observe-error") {
    entry.status = "failed";
    entry.phase = "failed";
    entry.desiredState = String(entry.desiredState || "open");
    entry.failureMessage = String(input.message || "隔离实例启动超时或 HTTP 未就绪。");
  } else {
    entry.status = "steady";
    entry.phase = "steady";
    entry.desiredState = "open";
    entry.failureMessage = "";
  }
  delete entry.ownerLease;
  return { applied: true, entry: { ...entry } };
}

export function applyRenewOwnerLease(
  payload: RegistryPayload,
  input: {
    instanceId: string;
    ownerId: string;
    expectedGeneration?: number;
    nowMs?: number;
  }
): ObserveResult {
  const instanceId = String(input.instanceId || "").trim();
  const entry = payload.instances[instanceId];
  if (!entry) {
    return { applied: false, entry: {} };
  }
  const expected = positiveInt(input.expectedGeneration);
  if (expected > 0 && positiveInt(entry.generation) !== expected) {
    return { applied: false, entry: { ...entry } };
  }
  const status = statusOf(entry);
  if (status !== "starting" && status !== "restarting") {
    return { applied: false, entry: { ...entry } };
  }
  const ownerId = String(input.ownerId || "").trim();
  const current = ownerLeaseOf(entry);
  if (current?.ownerId && ownerId && current.ownerId !== ownerId) {
    return { applied: false, entry: { ...entry } };
  }
  entry.ownerLease = buildOwnerLease({
    ownerId: ownerId || current?.ownerId || "",
    nowMs: input.nowMs
  });
  return { applied: true, entry: { ...entry } };
}

export function applyReclaimStaleInFlightStart(
  payload: RegistryPayload,
  input: {
    instanceId: string;
    nowMs?: number;
    expectedGeneration?: number;
    backendAlive?: boolean;
    backendListening?: boolean;
    windowOpen?: boolean;
  }
): ObserveResult {
  const instanceId = String(input.instanceId || "").trim();
  const entry = payload.instances[instanceId];
  if (!entry) {
    return { applied: false, entry: {} };
  }
  const expected = positiveInt(input.expectedGeneration);
  if (expected > 0 && positiveInt(entry.generation) !== expected) {
    return { applied: false, entry: { ...entry } };
  }
  // Stopping rows require an actual retirement proof from the Electron host.
  // This pure CAS helper has no process identity or port-health context, so it
  // must never clear their handles merely because the deadline elapsed.
  if (isStaleInFlightStop(entry, { nowMs: input.nowMs })) {
    return { applied: false, entry: { ...entry } };
  }
  if (
    !isStaleInFlightStart(entry, {
      nowMs: input.nowMs,
      backendAlive: input.backendAlive,
      backendListening: input.backendListening,
      windowOpen: input.windowOpen
    })
  ) {
    return { applied: false, entry: { ...entry } };
  }
  // A stale start with a registered process/window handle must go through the
  // health-identity retirement path before the handle or port can be reused.
  // The store can safely mark only handle-free rows as failed.
  if (positiveInt(entry.spawnPid) > 0 || positiveInt(entry.windowPid) > 0) {
    return { applied: false, entry: { ...entry } };
  }
  entry.status = "failed";
  entry.phase = "failed";
  entry.failureMessage = START_SUPERVISOR_LOST_MESSAGE;
  delete entry.ownerLease;
  return { applied: true, entry: { ...entry } };
}

export function applyUpsert(
  payload: RegistryPayload,
  instanceId: string,
  fields: Record<string, unknown>,
  expectedGeneration?: number
): UpsertResult {
  const wanted = String(instanceId || "").trim();
  if (!wanted) {
    throw new Error("instance_id must not be empty");
  }
  const entry = ensureEntry(payload, wanted);
  if (expectedGeneration !== undefined && positiveInt(entry.generation) !== positiveInt(expectedGeneration)) {
    return { applied: false, entry: { ...entry } };
  }
  Object.assign(entry, fields);
  if ("deadlineAt" in fields && !("inFlightDeadlineAt" in fields)) {
    entry.inFlightDeadlineAt = String(fields.deadlineAt || "");
  } else if ("inFlightDeadlineAt" in fields && !("deadlineAt" in fields)) {
    entry.deadlineAt = String(fields.inFlightDeadlineAt || "");
  }
  return { applied: true, entry: { ...entry } };
}

export function applyRecordSpawnPid(
  payload: RegistryPayload,
  input: {
    instanceId: string;
    spawnPid: number;
    expectedGeneration: number;
    spawnCreateTime?: number;
    spawnExecutable?: string;
  }
): UpsertResult {
  const fields: Record<string, unknown> = { spawnPid: Math.trunc(input.spawnPid) };
  const createTime = Number(input.spawnCreateTime || 0);
  const executable = String(input.spawnExecutable || "").trim();
  if (Number.isFinite(createTime) && createTime > 0 && executable) {
    fields.spawnCreateTime = createTime;
    fields.spawnExecutable = executable;
  }
  return applyUpsert(
    payload,
    input.instanceId,
    fields,
    input.expectedGeneration
  );
}

export async function readRegistry(registryPath: string): Promise<RegistryPayload> {
  try {
    return ensurePayload(JSON.parse(await readFile(registryPath, "utf8")));
  } catch (error: unknown) {
    if (typeof error === "object" && error !== null && (error as { code?: unknown }).code === "ENOENT") {
      return emptyRegistry();
    }
    if (error instanceof Error && error.message.startsWith("instances registry is corrupt:")) {
      throw error;
    }
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`instances registry is corrupt: ${detail}`);
  }
}

async function writeRegistry(registryPath: string, payload: RegistryPayload): Promise<void> {
  payload.schemaVersion = REGISTRY_SCHEMA_VERSION;
  payload.updatedAt = new Date().toISOString();
  await mkdir(dirname(registryPath), { recursive: true });
  const tempPath = join(dirname(registryPath) || tmpdir(), `.${randomBytes(6).toString("hex")}.instances.json`);
  const body = `${JSON.stringify(payload, null, 2)}\n`;
  await writeFile(tempPath, body, "utf8");
  await rename(tempPath, registryPath);
}

export type RegistryStoreOptions = InstanceLockOptions & {
  portIsFree?: PortIsFree;
};

async function mutateRegistry<T>(
  registryPath: string,
  mutator: (payload: RegistryPayload) => Promise<T> | T,
  options: RegistryStoreOptions = {}
): Promise<T> {
  return withInstanceLock(
    registryPath,
    async () => {
      const payload = await readRegistry(registryPath);
      const result = await mutator(payload);
      await writeRegistry(registryPath, payload);
      return result;
    },
    options
  );
}

export async function claimStart(
  registryPath: string,
  input: ClaimStartInput,
  options: RegistryStoreOptions = {}
): Promise<ClaimStartResult> {
  return mutateRegistry(
    registryPath,
    async (payload) => {
      applyReclaimStaleInFlightStart(payload, {
        instanceId: input.instanceId,
        nowMs: input.nowMs,
        backendAlive: input.alive,
        backendListening: false,
        windowOpen: false
      });
      return applyClaimStart(payload, {
        ...input,
        portIsFree: input.portIsFree || options.portIsFree || defaultPortIsFree
      });
    },
    options
  );
}

export async function claimStop(
  registryPath: string,
  input: { instanceId: string; projectRoot?: string; nowMs?: number; commandId?: string },
  options: RegistryStoreOptions = {}
): Promise<{ ok: true; entry: RegistryEntry }> {
  return mutateRegistry(registryPath, (payload) => applyClaimStop(payload, input), options);
}

export async function claimStopIfGeneration(
  registryPath: string,
  input: {
    instanceId: string;
    expectedGeneration: number;
    expectedCommandId?: string;
    projectRoot?: string;
    nowMs?: number;
    commandId?: string;
  },
  options: RegistryStoreOptions = {}
): Promise<ObserveResult> {
  return mutateRegistry(registryPath, (payload) => applyClaimStopIfGeneration(payload, input), options);
}

export async function completeStop(
  registryPath: string,
  input: { instanceId: string; expectedGeneration?: number; retainWindowPid?: number },
  options: RegistryStoreOptions = {}
): Promise<ObserveResult> {
  return mutateRegistry(registryPath, (payload) => applyCompleteStop(payload, input), options);
}

export async function observeReady(
  registryPath: string,
  input: { instanceId: string; expectedGeneration?: number },
  options: RegistryStoreOptions = {}
): Promise<ObserveResult> {
  return mutateRegistry(
    registryPath,
    (payload) => applyObserve(payload, { ...input, operation: "observe-ready" }),
    options
  );
}

export async function observeError(
  registryPath: string,
  input: { instanceId: string; expectedGeneration?: number; message?: string },
  options: RegistryStoreOptions = {}
): Promise<ObserveResult> {
  return mutateRegistry(
    registryPath,
    (payload) => applyObserve(payload, { ...input, operation: "observe-error" }),
    options
  );
}

export async function renewOwnerLease(
  registryPath: string,
  input: { instanceId: string; ownerId: string; expectedGeneration?: number; nowMs?: number },
  options: RegistryStoreOptions = {}
): Promise<ObserveResult> {
  return mutateRegistry(registryPath, (payload) => applyRenewOwnerLease(payload, input), options);
}

export async function reclaimStaleInFlightStart(
  registryPath: string,
  input: {
    instanceId: string;
    nowMs?: number;
    expectedGeneration?: number;
    backendAlive?: boolean;
    backendListening?: boolean;
    windowOpen?: boolean;
  },
  options: RegistryStoreOptions = {}
): Promise<ObserveResult> {
  return mutateRegistry(registryPath, (payload) => applyReclaimStaleInFlightStart(payload, input), options);
}

export type ReclaimStaleInFlightStopsResult = {
  applied: boolean;
  instanceIds: string[];
};

export type StaleStopCompletionProof = (
  instanceId: string,
  entry: RegistryEntry
) => boolean;

/**
 * Complete expired stop claims only when the caller supplies an independent
 * retirement proof for each row. A deadline alone is not process-exit
 * evidence, so the default path deliberately leaves stale rows visible and
 * keeps their handles/port lease held.
 */
export async function reclaimStaleInFlightStops(
  registryPath: string,
  input: { nowMs?: number; completionProof?: StaleStopCompletionProof } | number = {},
  options: RegistryStoreOptions = {}
): Promise<ReclaimStaleInFlightStopsResult> {
  return mutateRegistry(
    registryPath,
    (payload) => {
      const instanceIds: string[] = [];
      const nowMs = typeof input === "number" ? input : input.nowMs;
      const completionProof = typeof input === "number" ? undefined : input.completionProof;
      for (const instanceId of Object.keys(payload.instances)) {
        const entry = payload.instances[instanceId];
        if (!isStaleInFlightStop(entry, { nowMs })) {
          continue;
        }
        // A stale deadline is only a liveness signal for the supervisor. It is
        // not evidence that the registered backend/window has exited. Keep the
        // row and its port lease until the caller supplies an independently
        // verified retirement proof (the Electron host performs health-identity
        // reclaim before calling completeStop).
        if (!completionProof || !completionProof(instanceId, { ...entry })) {
          continue;
        }
        const result = applyCompleteStop(payload, { instanceId });
        if (result.applied) {
          instanceIds.push(instanceId);
        }
      }
      return { applied: instanceIds.length > 0, instanceIds };
    },
    options
  );
}

export async function upsert(
  registryPath: string,
  instanceId: string,
  fields: Record<string, unknown>,
  expectedGeneration: number,
  options: RegistryStoreOptions = {}
): Promise<UpsertResult> {
  return mutateRegistry(
    registryPath,
    (payload) => applyUpsert(payload, instanceId, fields, expectedGeneration),
    options
  );
}

export async function recordSpawnPid(
  registryPath: string,
  input: {
    instanceId: string;
    spawnPid: number;
    expectedGeneration: number;
    spawnCreateTime?: number;
    spawnExecutable?: string;
  },
  options: RegistryStoreOptions = {}
): Promise<UpsertResult> {
  return mutateRegistry(registryPath, (payload) => applyRecordSpawnPid(payload, input), options);
}

// ============================================================================
// State-refresh driven SSOT repair: adopt / close-dead / sweep.
//
// The registry is the single source of truth for instance state, and Electron
// is its only product writer. Terminal rows (closed/failed, spawnPid=0,
// reclaimable lease) previously had no mechanism to re-bind a live backend
// that re-appeared on the same instance, and dead keys whose worktree is gone
// were never removed. The mutations below close that gap; they are driven by
// instanceRegistryReconciler.ts on every successful state refresh.
// ============================================================================

/** Registry statuses that describe a finished lifecycle ("error" is legacy). */
export const TERMINAL_REGISTRY_STATUSES = new Set(["closed", "failed", "error"]);
/** Mirrors the Python orphan grace (_CLEANUP_OBSERVATION_GRACE_SECONDS = 10s). */
export const REGISTRY_OBSERVATION_GRACE_MS = 10_000;

export type AdoptedProcessIdentity = {
  createTime: number;
  executable: string;
};

export type AdoptLiveInstanceInput = {
  instanceId: string;
  projectRoot: string;
  branch?: string;
  observedPid: number;
  observedPort: number;
  observedControlPort?: number;
  identity?: AdoptedProcessIdentity;
  commandId?: string;
  host?: string;
  nowMs?: number;
  /** Evidence that a differing registered spawn pid is still alive. */
  registeredSpawnPidAlive?: boolean;
};

/**
 * Re-bind a live backend onto the instance row it belongs to.
 *
 * Adopt applies when the row is missing, terminal, handle-free (spawnPid=0),
 * or carries a reclaimable/quarantined lease while the observation proves a
 * live backend for the same instance. In-flight rows (starting/restarting/
 * stopping) always belong to a live supervisor and are never adopted; a row
 * whose differing registered spawn pid is verified alive is left to the
 * retirement path. Applying the adopt is idempotent: a row that already
 * matches the observation is returned untouched.
 */
export function applyAdoptLiveInstance(
  payload: RegistryPayload,
  input: AdoptLiveInstanceInput
): ObserveResult {
  const instanceId = String(input.instanceId || "").trim();
  if (!instanceId) {
    throw new Error("instance_id must not be empty");
  }
  const observedPid = positiveInt(input.observedPid);
  const observedPort = positiveInt(input.observedPort);
  if (observedPid <= 0 || observedPort <= 0) {
    throw new Error("adopt requires an observed live pid and backend port");
  }
  const entry = payload.instances[instanceId];
  if (entry) {
    if (Boolean(entry.cleanupInProgress)) {
      return { applied: false, entry: { ...entry } };
    }
    const status = statusOf(entry);
    if (IN_FLIGHT_STATUSES.has(status)) {
      return { applied: false, entry: { ...entry } };
    }
    const registeredPid = positiveInt(entry.spawnPid);
    if (registeredPid > 0 && registeredPid !== observedPid && input.registeredSpawnPidAlive === true) {
      // A different, still-live registered handle belongs to the health-identity
      // retirement path; overwriting it could orphan that process.
      return { applied: false, entry: { ...entry } };
    }
    if (
      status === "steady"
      && String(entry.desiredState || "").trim().toLowerCase() === "open"
      && registeredPid === observedPid
      && positiveInt(entry.port) === observedPort
      && holdsPortLease(entry)
    ) {
      return { applied: false, entry: { ...entry } };
    }
  }
  const target = ensureEntry(payload, instanceId);
  const nowMs = input.nowMs ?? Date.now();
  const createTime = Number(input.identity?.createTime || 0);
  const executable = String(input.identity?.executable || "").trim();
  const identity = createTime > 0 && executable ? { createTime, executable } : null;
  const controlPort = positiveInt(target.controlPort) || positiveInt(input.observedControlPort);
  Object.assign(target, {
    ...(String(input.projectRoot || "").trim() ? { projectRoot: String(input.projectRoot).trim() } : {}),
    ...(String(input.branch || "").trim() ? { branch: String(input.branch).trim() } : {}),
    port: observedPort,
    host: String(target.host || input.host || "127.0.0.1").trim() || "127.0.0.1",
    url: loopbackUrl(observedPort),
    status: "steady",
    phase: "steady",
    desiredState: "open",
    generation: positiveInt(target.generation) + 1,
    failureMessage: "",
    spawnPid: observedPid,
    portLeaseStatus: "held",
    startedAt: String(target.startedAt || "").trim() || toIsoUtc(nowMs)
  });
  if (controlPort > 0) {
    target.controlPort = controlPort;
  }
  if (String(input.commandId || "").trim()) {
    target.commandId = String(input.commandId).trim();
  }
  if (identity) {
    target.spawnCreateTime = identity.createTime;
    target.spawnExecutable = identity.executable;
  } else {
    delete target.spawnCreateTime;
    delete target.spawnExecutable;
  }
  // Stale in-flight bookkeeping from a dead generation must not survive.
  delete target.deadlineAt;
  delete target.inFlightDeadlineAt;
  delete target.ownerLease;
  delete target.portLease;
  delete target.cleanupObservation;
  return { applied: true, entry: { ...target } };
}

export type CloseConfirmedDeadInstanceInput = {
  instanceId: string;
  expectedGeneration?: number;
  /** "failed" settles a stale in-flight start; "closed" settles a dead steady row. */
  outcome: "closed" | "failed";
  failureMessage?: string;
  nowMs?: number;
};

/**
 * Symmetric half of adopt: the row claims a live runtime (steady, or a stale
 * in-flight start) with a registered spawn pid, but observation proved that
 * identity dead. Clears the handles and reclaims the port lease. The caller
 * must have verified the registered pid is dead and waited out the
 * observation grace; the generation CAS fences concurrent lifecycle owners.
 */
export function applyCloseConfirmedDeadInstance(
  payload: RegistryPayload,
  input: CloseConfirmedDeadInstanceInput
): ObserveResult {
  const instanceId = String(input.instanceId || "").trim();
  if (!instanceId) {
    throw new Error("instance_id must not be empty");
  }
  const entry = payload.instances[instanceId];
  if (!entry) {
    return { applied: false, entry: {} };
  }
  const expected = positiveInt(input.expectedGeneration);
  if (expected > 0 && positiveInt(entry.generation) !== expected) {
    return { applied: false, entry: { ...entry } };
  }
  if (positiveInt(entry.spawnPid) <= 0) {
    return { applied: false, entry: { ...entry } };
  }
  const status = statusOf(entry);
  if (input.outcome === "failed") {
    if (status !== "starting" && status !== "restarting") {
      return { applied: false, entry: { ...entry } };
    }
  } else if (status !== "steady") {
    return { applied: false, entry: { ...entry } };
  }
  const outcome = input.outcome === "failed" ? "failed" : "closed";
  entry.status = outcome;
  entry.phase = outcome === "failed" ? "failed" : "steady";
  entry.desiredState = outcome === "failed" ? "open" : "closed";
  entry.failureMessage = String(input.failureMessage || "");
  entry.spawnPid = 0;
  delete entry.spawnCreateTime;
  delete entry.spawnExecutable;
  entry.portLeaseStatus = "reclaimable";
  delete entry.ownerLease;
  return { applied: true, entry: { ...entry } };
}

/** Grace tracker shared across passes; keyed by instance id. */
export type SweepGraceTracker = Map<string, { since: number; fingerprint: string }>;

export type SweepTerminatedRowsInput = {
  nowMs?: number;
  graceMs?: number;
  pidAlive: (pid: number) => boolean;
  pathExists: (path: string) => boolean;
  /** Instance ids whose scan observation shows a live backend or open window. */
  protectedInstanceIds?: Iterable<string>;
  graceTracker?: SweepGraceTracker;
};

export type SweepTerminatedRowsResult = {
  applied: boolean;
  removedInstanceIds: string[];
  eligibleInstanceIds: string[];
};

/**
 * Delete dead keys: terminal rows with no live registered identity whose
 * worktree path no longer exists. The 10s grace (tracked via the injected
 * tracker, mirroring the Python orphan grace) keeps a single jittery
 * observation from deleting a key; a fingerprint change resets the grace.
 */
export function applySweepTerminatedRows(
  payload: RegistryPayload,
  input: SweepTerminatedRowsInput
): SweepTerminatedRowsResult {
  const nowMs = input.nowMs ?? Date.now();
  const graceMs = Math.max(0, Math.trunc(input.graceMs ?? REGISTRY_OBSERVATION_GRACE_MS));
  const tracker = input.graceTracker;
  const protectedIds = new Set(
    Array.from(input.protectedInstanceIds || [], (id) => String(id))
  );
  const removed: string[] = [];
  const eligible: string[] = [];
  for (const [instanceId, entry] of Object.entries(payload.instances)) {
    if (!TERMINAL_REGISTRY_STATUSES.has(statusOf(entry))) {
      continue;
    }
    if (Boolean(entry.cleanupInProgress)) {
      continue;
    }
    if (!ownerLeaseExpired(entry, nowMs)) {
      continue;
    }
    if (protectedIds.has(instanceId)) {
      continue;
    }
    const spawnPid = positiveInt(entry.spawnPid);
    if (spawnPid > 0 && input.pidAlive(spawnPid)) {
      continue;
    }
    const windowPid = positiveInt(entry.windowPid);
    if (windowPid > 0 && input.pidAlive(windowPid)) {
      continue;
    }
    const projectRoot = String(entry.projectRoot || "").trim();
    if (!projectRoot || input.pathExists(projectRoot)) {
      continue;
    }
    const fingerprint = `${projectRoot}|${positiveInt(entry.generation)}|${positiveInt(entry.port)}`;
    if (tracker) {
      const prev = tracker.get(instanceId);
      if (!prev || prev.fingerprint !== fingerprint) {
        tracker.set(instanceId, { since: nowMs, fingerprint });
        eligible.push(instanceId);
        continue;
      }
      if (nowMs - prev.since < graceMs) {
        eligible.push(instanceId);
        continue;
      }
      tracker.delete(instanceId);
    }
    delete payload.instances[instanceId];
    removed.push(instanceId);
  }
  return { applied: removed.length > 0, removedInstanceIds: removed, eligibleInstanceIds: eligible };
}

export async function adoptLiveInstance(
  registryPath: string,
  input: AdoptLiveInstanceInput,
  options: RegistryStoreOptions = {}
): Promise<ObserveResult> {
  return mutateRegistry(registryPath, (payload) => applyAdoptLiveInstance(payload, input), options);
}

export async function closeConfirmedDeadInstance(
  registryPath: string,
  input: CloseConfirmedDeadInstanceInput,
  options: RegistryStoreOptions = {}
): Promise<ObserveResult> {
  return mutateRegistry(registryPath, (payload) => applyCloseConfirmedDeadInstance(payload, input), options);
}

export async function sweepTerminatedRows(
  registryPath: string,
  input: SweepTerminatedRowsInput,
  options: RegistryStoreOptions = {}
): Promise<SweepTerminatedRowsResult> {
  return mutateRegistry(registryPath, (payload) => applySweepTerminatedRows(payload, input), options);
}

export function throwIfBusy(result: ClaimStartResult): RegistryEntry {
  if (!result.ok) {
    throw new InstanceBusyError(result.instanceId, result.status, result.generation);
  }
  return result.entry;
}
