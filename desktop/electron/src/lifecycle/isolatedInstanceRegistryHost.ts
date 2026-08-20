import { assertLifecycleAdmitted, recordAdmissionOutcome } from "./instanceAdmissionStore.js";

/** Isolated-instance lifecycle operations Electron main owns end to end. */
export type BranchInstanceOperation =
  | "start"
  | "stop"
  | "force-stop"
  | "restart"
  | "observe-error"
  | "observe-ready";

import {
  claimStart,
  claimStop,
  isolatedStartDeadlineAt,
  instancesRegistryPath,
  observeError,
  observeReady,
  renewOwnerLease,
  type ClaimStartResult,
  type ObserveResult,
  type RegistryEntry,
  type RegistryStoreOptions
} from "./instanceRegistryStore.js";

export type IsolatedClaimTarget = {
  instanceId: string;
  projectRoot: string;
  branch: string;
  preferredBackend: number;
  preferredControl: number;
  extraUsed: number[];
  alive: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function positiveInt(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : 0;
}

function itemsFrom(payload: unknown): Record<string, unknown>[] {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    return [];
  }
  return payload.items.filter(isRecord);
}

export function collectExtraUsedPorts(payload: unknown, excludeId = ""): number[] {
  const used = new Set<number>();
  for (const item of itemsFrom(payload)) {
    if (excludeId && String(item.id || "").trim() === excludeId) {
      continue;
    }
    const port = positiveInt(item.port);
    const control = positiveInt(item.controlPort);
    if (port > 0) {
      used.add(port);
    }
    if (control > 0) {
      used.add(control);
    }
  }
  return [...used];
}

export function resolveIsolatedClaimTarget(
  payload: unknown,
  instanceId: string
): IsolatedClaimTarget | null {
  const wanted = String(instanceId || "").trim();
  if (!wanted) {
    return null;
  }
  const item = itemsFrom(payload).find((candidate) => String(candidate.id || "").trim() === wanted);
  if (!item) {
    return null;
  }
  const projectRoot = String(item.path || item.projectRoot || "").trim();
  if (!projectRoot) {
    return null;
  }
  return {
    instanceId: wanted,
    projectRoot,
    branch: String(item.branch || "").trim(),
    preferredBackend: positiveInt(item.port),
    preferredControl: positiveInt(item.controlPort),
    extraUsed: collectExtraUsedPorts(payload, wanted),
    alive: item.alive === true
  };
}

export async function claimIsolatedStart(input: {
  instanceId: string;
  branchInstances: unknown;
  operation?: "start" | "restart";
  commandId: string;
  ownerPid?: number;
  ownerId?: string;
  registryPath?: string;
  nowMs?: number;
  storeOptions?: RegistryStoreOptions;
  admissionStorePath?: string;
}): Promise<ClaimStartResult> {
  const target = resolveIsolatedClaimTarget(input.branchInstances, input.instanceId);
  if (!target) {
    throw new Error(`找不到分支实例：${input.instanceId}`);
  }
  const nowMs = input.nowMs ?? Date.now();
  await assertLifecycleAdmitted({
    instanceId: target.instanceId,
    operation: input.operation || "start",
    nowMs,
    storePath: input.admissionStorePath
  });
  const ownerPid = input.ownerPid ?? process.pid;
  return claimStart(
    input.registryPath || instancesRegistryPath(),
    {
      instanceId: target.instanceId,
      projectRoot: target.projectRoot,
      branch: target.branch,
      operation: input.operation || "start",
      commandId: input.commandId,
      deadlineAt: isolatedStartDeadlineAt(nowMs),
      startedAt: new Date(nowMs).toISOString().replace(/\.\d{3}Z$/, "Z"),
      ownerPid,
      ownerId: input.ownerId || `pid:${ownerPid}`,
      nowMs,
      alive: target.alive,
      preferredBackend: target.preferredBackend,
      preferredControl: target.preferredControl,
      extraUsed: target.extraUsed
    },
    input.storeOptions
  );
}

export async function claimIsolatedStop(input: {
  instanceId: string;
  branchInstances?: unknown;
  projectRoot?: string;
  registryPath?: string;
  storeOptions?: RegistryStoreOptions;
}): Promise<{ ok: true; entry: RegistryEntry }> {
  const target = input.branchInstances
    ? resolveIsolatedClaimTarget(input.branchInstances, input.instanceId)
    : null;
  return claimStop(
    input.registryPath || instancesRegistryPath(),
    {
      instanceId: input.instanceId,
      projectRoot: input.projectRoot || target?.projectRoot || ""
    },
    input.storeOptions
  );
}

export async function observeIsolatedReady(input: {
  instanceId: string;
  expectedGeneration?: number;
  registryPath?: string;
  storeOptions?: RegistryStoreOptions;
  admissionStorePath?: string;
}): Promise<ObserveResult> {
  const result = await observeReady(
    input.registryPath || instancesRegistryPath(),
    { instanceId: input.instanceId, expectedGeneration: input.expectedGeneration },
    input.storeOptions
  );
  if (result.applied) {
    await recordAdmissionOutcome({
      instanceId: input.instanceId,
      outcome: "success",
      storePath: input.admissionStorePath
    });
  }
  return result;
}

export async function observeIsolatedError(input: {
  instanceId: string;
  expectedGeneration?: number;
  message?: string;
  registryPath?: string;
  storeOptions?: RegistryStoreOptions;
  admissionStorePath?: string;
}): Promise<ObserveResult> {
  const result = await observeError(
    input.registryPath || instancesRegistryPath(),
    {
      instanceId: input.instanceId,
      expectedGeneration: input.expectedGeneration,
      message: input.message
    },
    input.storeOptions
  );
  if (result.applied) {
    await recordAdmissionOutcome({
      instanceId: input.instanceId,
      outcome: "failure",
      storePath: input.admissionStorePath
    });
  }
  return result;
}

export async function renewIsolatedOwnerLease(input: {
  instanceId: string;
  ownerId: string;
  expectedGeneration?: number;
  nowMs?: number;
  registryPath?: string;
  storeOptions?: RegistryStoreOptions;
}): Promise<ObserveResult> {
  return renewOwnerLease(
    input.registryPath || instancesRegistryPath(),
    {
      instanceId: input.instanceId,
      ownerId: input.ownerId,
      expectedGeneration: input.expectedGeneration,
      nowMs: input.nowMs
    },
    input.storeOptions
  );
}
