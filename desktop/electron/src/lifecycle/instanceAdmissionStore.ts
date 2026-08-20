import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";

import { withInstanceLock, type InstanceLockOptions } from "./instanceLock.js";
import {
  AdmissionDeniedError,
  decideAdmission,
  emptyAdmissionRecord,
  isStartLikeOperation,
  recordAdmittedStart,
  recordAdmissionFailure as applyFailure,
  recordAdmissionSuccess as applySuccess,
  type AdmissionDecision,
  type AdmissionRecord
} from "./instanceAdmissionControl.js";

export const ADMISSION_SCHEMA_VERSION = 1;
export const ADMISSION_FILE_NAME = "instance-admission.json";

export type AdmissionPayload = {
  schemaVersion: number;
  updatedAt?: string;
  instances: Record<string, AdmissionRecord>;
};

export type AdmissionStoreOptions = InstanceLockOptions & {
  storePath?: string;
  nowMs?: number;
};

const cache = new Map<string, AdmissionRecord>();
let cacheStorePath = "";
let cacheHydrated = false;

export function instanceAdmissionPath(env: NodeJS.Dict<string> = process.env): string {
  const local = String(env.LOCALAPPDATA || "").trim();
  const root = local || join(String(env.USERPROFILE || env.HOME || ""), "AppData", "Local");
  return join(root, "Vibelution", ADMISSION_FILE_NAME);
}

export function emptyAdmissionPayload(): AdmissionPayload {
  return { schemaVersion: ADMISSION_SCHEMA_VERSION, instances: {} };
}

export function resetAdmissionCacheForTests(): void {
  cache.clear();
  cacheStorePath = "";
  cacheHydrated = false;
}

export function peekAdmissionDecision(
  instanceId: string,
  nowMs = Date.now(),
  operation = "start"
): AdmissionDecision {
  const record = cache.get(normalizeInstanceId(instanceId)) || emptyAdmissionRecord();
  return decideAdmission(record, nowMs, operation);
}

export async function ensureAdmissionLoaded(storePath = instanceAdmissionPath()): Promise<void> {
  if (cacheHydrated && cacheStorePath === storePath) {
    return;
  }
  const payload = await readAdmission(storePath);
  hydrateCache(storePath, payload);
}

export async function admitLifecycleCommand(input: {
  instanceId: string;
  operation: string;
  storePath?: string;
  nowMs?: number;
  storeOptions?: AdmissionStoreOptions;
}): Promise<AdmissionDecision> {
  const instanceId = normalizeInstanceId(input.instanceId);
  const operation = String(input.operation || "").trim().toLowerCase();
  const nowMs = input.nowMs ?? Date.now();
  if (!instanceId || !isStartLikeOperation(operation)) {
    return { admitted: true, code: "", retryAfterMs: 0, message: "" };
  }
  return mutateAdmission(
    input.storePath || instanceAdmissionPath(),
    (payload) => {
      const current = payload.instances[instanceId] || emptyAdmissionRecord();
      const decision = decideAdmission(current, nowMs, operation);
      if (!decision.admitted) {
        return decision;
      }
      payload.instances[instanceId] = recordAdmittedStart(current, nowMs);
      return decision;
    },
    input.storeOptions
  );
}

export async function assertLifecycleAdmitted(input: {
  instanceId: string;
  operation: string;
  storePath?: string;
  nowMs?: number;
  storeOptions?: AdmissionStoreOptions;
}): Promise<void> {
  const decision = await admitLifecycleCommand(input);
  if (decision.admitted || decision.code === "") {
    return;
  }
  throw new AdmissionDeniedError({
    instanceId: normalizeInstanceId(input.instanceId),
    code: decision.code,
    retryAfterMs: decision.retryAfterMs,
    message: decision.message,
    eventName: decision.eventName || "launcher.admission.rate_limited"
  });
}

export async function recordAdmissionOutcome(input: {
  instanceId: string;
  outcome: "success" | "failure";
  storePath?: string;
  nowMs?: number;
  storeOptions?: AdmissionStoreOptions;
}): Promise<AdmissionRecord> {
  const instanceId = normalizeInstanceId(input.instanceId);
  const nowMs = input.nowMs ?? Date.now();
  if (!instanceId) {
    return emptyAdmissionRecord();
  }
  return mutateAdmission(
    input.storePath || instanceAdmissionPath(),
    (payload) => {
      const current = payload.instances[instanceId] || emptyAdmissionRecord();
      const next = input.outcome === "success" ? applySuccess(current) : applyFailure(current, nowMs);
      payload.instances[instanceId] = next;
      return next;
    },
    input.storeOptions
  );
}

function normalizeInstanceId(instanceId: string): string {
  return String(instanceId || "").trim();
}

function hydrateCache(storePath: string, payload: AdmissionPayload): void {
  cache.clear();
  for (const [instanceId, record] of Object.entries(payload.instances || {})) {
    cache.set(instanceId, normalizeRecord(record));
  }
  cacheStorePath = storePath;
  cacheHydrated = true;
}

function normalizeRecord(value: Partial<AdmissionRecord> | undefined): AdmissionRecord {
  const empty = emptyAdmissionRecord();
  if (!value || typeof value !== "object") {
    return empty;
  }
  const stamps = Array.isArray(value.startTimestampsMs)
    ? value.startTimestampsMs.filter((stamp) => Number.isFinite(stamp)).map((stamp) => Math.trunc(stamp))
    : [];
  return {
    startTimestampsMs: stamps,
    consecutiveFailures: Math.max(0, Math.trunc(Number(value.consecutiveFailures) || 0)),
    cooldownUntilMs: Math.max(0, Math.trunc(Number(value.cooldownUntilMs) || 0))
  };
}

function ensurePayload(value: unknown): AdmissionPayload {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return emptyAdmissionPayload();
  }
  const raw = value as AdmissionPayload;
  const instances: Record<string, AdmissionRecord> = {};
  if (raw.instances && typeof raw.instances === "object" && !Array.isArray(raw.instances)) {
    for (const [instanceId, record] of Object.entries(raw.instances)) {
      const key = normalizeInstanceId(instanceId);
      if (key) {
        instances[key] = normalizeRecord(record);
      }
    }
  }
  return {
    schemaVersion: ADMISSION_SCHEMA_VERSION,
    updatedAt: raw.updatedAt,
    instances
  };
}

async function readAdmission(storePath: string): Promise<AdmissionPayload> {
  try {
    return ensurePayload(JSON.parse(await readFile(storePath, "utf8")));
  } catch {
    return emptyAdmissionPayload();
  }
}

async function writeAdmission(storePath: string, payload: AdmissionPayload): Promise<void> {
  payload.schemaVersion = ADMISSION_SCHEMA_VERSION;
  payload.updatedAt = new Date().toISOString();
  await mkdir(dirname(storePath), { recursive: true });
  const tempPath = join(dirname(storePath) || tmpdir(), `.${randomBytes(6).toString("hex")}.instance-admission.json`);
  await writeFile(tempPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await rename(tempPath, storePath);
}

async function mutateAdmission<T>(
  storePath: string,
  mutator: (payload: AdmissionPayload) => T,
  options: AdmissionStoreOptions = {}
): Promise<T> {
  return withInstanceLock(
    storePath,
    async () => {
      const payload = await readAdmission(storePath);
      const result = mutator(payload);
      await writeAdmission(storePath, payload);
      hydrateCache(storePath, payload);
      return result;
    },
    options
  );
}
