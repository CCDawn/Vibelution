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
  windowPid?: number;
  ownerPid?: number;
  ownerLease?: OwnerLease | Record<string, unknown>;
  startedAt?: string;
  portLeaseStatus?: string;
  slotKey?: string;
  slotId?: string;
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
  const record = asRecord(raw);
  const instancesRaw = record.instances;
  const instances: Record<string, RegistryEntry> = {};
  if (typeof instancesRaw === "object" && instancesRaw !== null && !Array.isArray(instancesRaw)) {
    for (const [key, value] of Object.entries(instancesRaw)) {
      if (typeof value === "object" && value !== null && !Array.isArray(value)) {
        instances[key] = { ...(value as RegistryEntry) };
      }
    }
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
    spawnPid: 0,
    windowPid: 0,
    ownerPid: Math.trunc(input.ownerPid),
    ownerLease: buildOwnerLease({ ownerId: input.ownerId, ownerPid: input.ownerPid, nowMs }),
    startedAt: input.startedAt || input.deadlineAt
  });
  return { ok: true, entry: { ...entry } };
}

export function applyClaimStop(
  payload: RegistryPayload,
  input: { instanceId: string; projectRoot?: string }
): { ok: true; entry: RegistryEntry } {
  const instanceId = String(input.instanceId || "").trim();
  if (!instanceId) {
    throw new Error("instance_id must not be empty");
  }
  const entry = ensureEntry(payload, instanceId);
  const generation = positiveInt(entry.generation) + 1;
  entry.status = "stopping";
  entry.phase = "stopping";
  entry.desiredState = "closed";
  entry.generation = generation;
  entry.failureMessage = "";
  delete entry.ownerLease;
  const projectRoot = String(input.projectRoot || "").trim();
  if (projectRoot && projectRoot !== ".") {
    entry.projectRoot = projectRoot;
  }
  return { ok: true, entry: { ...entry } };
}

/**
 * Commit a successful stop after the registered process handles have been
 * retired. The generation check keeps an older stop from closing a newer
 * start that raced with the retirement path.
 */
export function applyCompleteStop(
  payload: RegistryPayload,
  input: { instanceId: string; expectedGeneration?: number }
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
  entry.windowPid = 0;
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
  input: { instanceId: string; spawnPid: number; expectedGeneration: number }
): UpsertResult {
  return applyUpsert(
    payload,
    input.instanceId,
    { spawnPid: Math.trunc(input.spawnPid) },
    input.expectedGeneration
  );
}

export async function readRegistry(registryPath: string): Promise<RegistryPayload> {
  try {
    return ensurePayload(JSON.parse(await readFile(registryPath, "utf8")));
  } catch {
    return emptyRegistry();
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
  input: { instanceId: string; projectRoot?: string },
  options: RegistryStoreOptions = {}
): Promise<{ ok: true; entry: RegistryEntry }> {
  return mutateRegistry(registryPath, (payload) => applyClaimStop(payload, input), options);
}

export async function completeStop(
  registryPath: string,
  input: { instanceId: string; expectedGeneration?: number },
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
    backendAlive?: boolean;
    backendListening?: boolean;
    windowOpen?: boolean;
  },
  options: RegistryStoreOptions = {}
): Promise<ObserveResult> {
  return mutateRegistry(registryPath, (payload) => applyReclaimStaleInFlightStart(payload, input), options);
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
  input: { instanceId: string; spawnPid: number; expectedGeneration: number },
  options: RegistryStoreOptions = {}
): Promise<UpsertResult> {
  return mutateRegistry(registryPath, (payload) => applyRecordSpawnPid(payload, input), options);
}

export function throwIfBusy(result: ClaimStartResult): RegistryEntry {
  if (!result.ok) {
    throw new InstanceBusyError(result.instanceId, result.status, result.generation);
  }
  return result.entry;
}
