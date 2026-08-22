import { randomUUID } from "node:crypto";

import { assertLifecycleAdmitted, recordAdmissionOutcome } from "./instanceAdmissionStore.js";
import {
  clearWorkbenchLauncherRuntimeState,
  readDaemonIdentity,
  readDaemonPid,
  reclaimStaleWorkbenchBackend,
  type WorkbenchRuntimeStateCleanupResult
} from "../process/workbenchBackend.js";
import {
  requestGracefulWorkbenchShutdown
} from "../process/workbenchBackendRetire.js";
import { createPythonOwnedProcessTreeTerminator, type PythonProcessIdentity } from "../process/pythonJsonBridge.js";
import { knownPidIsAlive } from "./mainLine/observation.js";

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
  claimStopIfGeneration,
  completeStop,
  isStaleInFlightStart,
  isolatedStartDeadlineAt,
  instancesRegistryPath,
  readRegistry,
  observeError,
  observeReady,
  renewOwnerLease,
  upsert,
  type ClaimStartResult,
  type ObserveResult,
  type RegistryEntry,
  type RegistryPayload,
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

export type IsolatedStartRetireResult =
  | { ok: true }
  | {
      ok: false;
      code: "instance_busy" | "backend_retire_incomplete" | "lifecycle_intent_superseded";
      generation: number;
      message: string;
    };

export type IsolatedStartPreparationResult =
  | { ok: true; entry: RegistryEntry }
  | {
      ok: false;
      code: "instance_busy" | "backend_retire_incomplete" | "lifecycle_intent_superseded";
      generation: number;
      message: string;
    };

type IsolatedStartRetireDependencies = {
  readRegistry: (registryPath: string) => Promise<RegistryPayload>;
  claimStopIfGeneration: (
    registryPath: string,
    input: {
      instanceId: string;
      expectedGeneration: number;
      expectedCommandId?: string;
      projectRoot?: string;
      nowMs?: number;
      commandId?: string;
    }
  ) => Promise<ObserveResult>;
  reclaimBackend: typeof reclaimStaleWorkbenchBackend;
  completeStop: (
    registryPath: string,
    input: { instanceId: string; expectedGeneration?: number }
  ) => Promise<ObserveResult>;
  clearRuntimeState: (workspaceRoot: string) => WorkbenchRuntimeStateCleanupResult;
  upsert: (
    registryPath: string,
    instanceId: string,
    fields: Record<string, unknown>,
    expectedGeneration: number
  ) => Promise<{ applied: boolean; entry: RegistryEntry }>;
  pidAlive: (pid: number) => boolean;
};

const DEFAULT_ISOLATED_START_RETIRE_DEPENDENCIES: IsolatedStartRetireDependencies = {
  readRegistry,
  claimStopIfGeneration: (registryPath, input) => claimStopIfGeneration(registryPath, input),
  reclaimBackend: reclaimStaleWorkbenchBackend,
  completeStop: (registryPath, input) => completeStop(registryPath, input),
  clearRuntimeState: clearWorkbenchLauncherRuntimeState,
  upsert: (registryPath, instanceId, fields, expectedGeneration) =>
    upsert(registryPath, instanceId, fields, expectedGeneration),
  pidAlive: knownPidIsAlive
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
  return claimResolvedIsolatedStart(input, target, nowMs);
}

async function claimResolvedIsolatedStart(
  input: {
    operation?: "start" | "restart";
    commandId: string;
    ownerPid?: number;
    ownerId?: string;
    registryPath?: string;
    storeOptions?: RegistryStoreOptions;
  },
  target: IsolatedClaimTarget,
  nowMs: number
): Promise<ClaimStartResult> {
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

/** Admission is consumed exactly once and always before retiring an older runtime. */
export async function prepareIsolatedStart(input: {
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
  signal?: AbortSignal;
  pythonPath?: string;
  isCurrent?: () => boolean;
  retireDependencies?: Partial<IsolatedStartRetireDependencies>;
}): Promise<IsolatedStartPreparationResult> {
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
  const retired = await retireIsolatedRuntimeBeforeStart({
    instanceId: target.instanceId,
    workspaceRoot: target.projectRoot,
    registryPath: input.registryPath,
    nowMs,
    signal: input.signal,
    pythonPath: input.pythonPath,
    isCurrent: input.isCurrent,
    dependencies: input.retireDependencies
  });
  if (!retired.ok) {
    return retired;
  }
  if (input.signal?.aborted || !(input.isCurrent?.() ?? true)) {
    return {
      ok: false,
      code: "lifecycle_intent_superseded",
      generation: 0,
      message: "A newer Launcher lifecycle intent superseded this start after retirement."
    };
  }
  const claimed = await claimResolvedIsolatedStart(input, target, nowMs);
  if (!claimed.ok) {
    return {
      ok: false,
      code: "instance_busy",
      generation: claimed.generation,
      message: "该分支实例正在执行生命周期操作。"
    };
  }
  return claimed;
}

function normalizedStatus(entry: RegistryEntry | undefined): string {
  return String(entry?.status || "").trim().toLowerCase();
}

function entryHasRegisteredRuntime(entry: RegistryEntry | undefined): boolean {
  if (!entry) {
    return false;
  }
  const spawnPid = positiveInt(entry.spawnPid);
  const port = positiveInt(entry.port);
  if (spawnPid > 0) {
    return true;
  }
  if (port <= 0) {
    return false;
  }
  const status = normalizedStatus(entry);
  const leaseStatus = String(entry.portLeaseStatus || "").trim().toLowerCase();
  if (["reclaimable", "quarantined"].includes(leaseStatus)) {
    return false;
  }
  return status !== "stopping" || positiveInt(entry.spawnPid) > 0;
}

function isolatedRetireIncompleteMessage(input: {
  staleReclaim: { reclaimed: boolean; reason: string };
  backendConfirmedClosed: boolean;
  registeredSpawnPid: number;
  registeredSpawnPidAlive: boolean;
  port: number;
  runtimeCleanup?: WorkbenchRuntimeStateCleanupResult | null;
}): string {
  const reason = !input.backendConfirmedClosed
    ? input.staleReclaim.reclaimed
      ? input.registeredSpawnPidAlive
        ? `port ${input.port} is released but registered spawn pid ${input.registeredSpawnPid} is still alive and was not health-verified`
        : input.staleReclaim.reason
      : input.staleReclaim.reason
    : "";
  return [
    reason,
    input.runtimeCleanup?.failedCount
      ? "workbench launcher runtime state could not be fully cleared"
      : ""
  ].filter(Boolean).join("; ") || "isolated backend retirement was incomplete";
}

/**
 * Fence and retire a previously registered isolated runtime before a new
 * start/restart claim can overwrite its PID and port. The stop claim keeps
 * the old generation visible while health identity and runtime-state cleanup
 * complete; an incomplete retirement stays failed with its handles intact so
 * a later retry cannot silently create a second backend.
 */
export async function retireIsolatedRuntimeBeforeStart(input: {
  instanceId: string;
  workspaceRoot: string;
  registryPath?: string;
  nowMs?: number;
  signal?: AbortSignal;
  pythonPath?: string;
  isCurrent?: () => boolean;
  dependencies?: Partial<IsolatedStartRetireDependencies>;
}): Promise<IsolatedStartRetireResult> {
  const registryPath = input.registryPath || instancesRegistryPath();
  const dependencies: IsolatedStartRetireDependencies = {
    ...DEFAULT_ISOLATED_START_RETIRE_DEPENDENCIES,
    ...(input.dependencies || {})
  };
  const fenceOpen = (): boolean => !input.signal?.aborted && (input.isCurrent?.() ?? true);
  if (!fenceOpen()) {
    return {
      ok: false,
      code: "lifecycle_intent_superseded",
      generation: 0,
      message: "A newer Launcher lifecycle intent superseded this retirement."
    };
  }
  const current = await dependencies.readRegistry(registryPath);
  const existing = current.instances[input.instanceId];
  if (!entryHasRegisteredRuntime(existing)) {
    return { ok: true };
  }

  const status = normalizedStatus(existing);
  const staleStart = (status === "starting" || status === "restarting")
    && isStaleInFlightStart(existing, { nowMs: input.nowMs });
  if (status === "stopping" || ((status === "starting" || status === "restarting") && !staleStart)) {
    return {
      ok: false,
      code: "instance_busy",
      generation: positiveInt(existing.generation),
      message: "该分支实例正在执行生命周期操作。"
    };
  }

  if (!fenceOpen()) {
    return {
      ok: false,
      code: "lifecycle_intent_superseded",
      generation: positiveInt(existing.generation),
      message: "A newer Launcher lifecycle intent superseded this retirement."
    };
  }
  const claimed = await dependencies.claimStopIfGeneration(registryPath, {
    instanceId: input.instanceId,
    expectedGeneration: positiveInt(existing.generation),
    expectedCommandId: String(existing.commandId || "").trim() || undefined,
    projectRoot: String(existing.projectRoot || input.workspaceRoot || "").trim(),
    commandId: `retire-before-start:${randomUUID()}`,
    nowMs: input.nowMs
  });
  if (!claimed.applied) {
    return {
      ok: false,
      code: "instance_busy",
      generation: positiveInt(claimed.entry.generation),
      message: "该分支实例已被更新，旧运行时未执行回收。"
    };
  }
  const retired = await retireClaimedIsolatedRuntime({
    instanceId: input.instanceId,
    workspaceRoot: input.workspaceRoot,
    entry: claimed.entry,
    registryPath,
    signal: input.signal,
    pythonPath: input.pythonPath,
    isCurrent: input.isCurrent,
    desiredStateOnFailure: "open",
    dependencies
  });
  if (retired.ok && !fenceOpen()) {
    return {
      ok: false,
      code: "lifecycle_intent_superseded",
      generation: positiveInt(claimed.entry.generation),
      message: "A newer Launcher lifecycle intent superseded this retirement after the backend closed."
    };
  }
  return retired;
}

/**
 * Retire the runtime represented by an already-fenced stop claim. Every exit
 * settles that claim to closed or failed, so abort/supersede cannot strand a
 * stopping row and incomplete retirement never clears its registered handles.
 */
export async function retireClaimedIsolatedRuntime(input: {
  instanceId: string;
  workspaceRoot: string;
  entry: RegistryEntry;
  registryPath?: string;
  signal?: AbortSignal;
  pythonPath?: string;
  isCurrent?: () => boolean;
  desiredStateOnFailure: "open" | "closed";
  successFailureMessage?: string;
  dependencies?: Partial<IsolatedStartRetireDependencies>;
}): Promise<IsolatedStartRetireResult> {
  const registryPath = input.registryPath || instancesRegistryPath();
  const dependencies: IsolatedStartRetireDependencies = {
    ...DEFAULT_ISOLATED_START_RETIRE_DEPENDENCIES,
    ...(input.dependencies || {})
  };
  const fenceOpen = (): boolean => !input.signal?.aborted && (input.isCurrent?.() ?? true);
  const entry = input.entry;
  const generation = positiveInt(entry.generation);
  const workspaceRoot = String(entry.projectRoot || input.workspaceRoot || "").trim();
  const port = positiveInt(entry.port);
  const registeredSpawnPid = positiveInt(entry.spawnPid);
  const settleFailed = async (message: string): Promise<IsolatedStartRetireResult> => {
    const failed = await dependencies.upsert(
      registryPath,
      input.instanceId,
      {
        status: "failed",
        phase: "failed",
        desiredState: input.desiredStateOnFailure,
        failureMessage: message
      },
      generation
    );
    return {
      ok: false,
      code: "backend_retire_incomplete",
      generation,
      message: failed.applied
        ? message
        : "isolated backend retirement lost its registry generation while settling failure"
    };
  };
  if (!fenceOpen()) {
    return settleFailed("isolated backend retirement was superseded before health-identity reclaim");
  }
  let staleReclaim: { reclaimed: boolean; reason: string; verifiedPid?: number };
  try {
    const daemonPid = readDaemonPid(workspaceRoot);
    const pythonPath = String(input.pythonPath || "").trim();
    if (!pythonPath) {
      return settleFailed("isolated backend retirement cannot verify process ownership: python path missing; registered handles retained");
    }
    const expectedIdentities: Record<string, PythonProcessIdentity> = {};
    const spawnCreateTime = Number(entry.spawnCreateTime || 0);
    const spawnExecutable = String(entry.spawnExecutable || "").trim();
    if (registeredSpawnPid > 0 && spawnCreateTime > 0 && spawnExecutable) {
      expectedIdentities[String(registeredSpawnPid)] = {
        pid: registeredSpawnPid,
        createTime: spawnCreateTime,
        executable: spawnExecutable
      };
    }
    const daemonIdentity = readDaemonIdentity(workspaceRoot);
    if (daemonIdentity && daemonIdentity.pid === daemonPid) {
      expectedIdentities[String(daemonPid)] = daemonIdentity;
    }
    const terminateProcessTree = createPythonOwnedProcessTreeTerminator({
      pythonPath,
      workspaceRoot,
      allowedKinds: ["managed_workbench_backend", "runtime_manager_daemon"],
      expectedIdentities
    });
    staleReclaim = workspaceRoot && port > 0
      ? await dependencies.reclaimBackend({
          port,
          host: String(entry.host || "127.0.0.1"),
          workspaceRoot,
          registeredPids: [registeredSpawnPid],
          extraPids: [daemonPid],
          expectedIdentities,
          terminateProcessTree,
          gracefulShutdown: requestGracefulWorkbenchShutdown,
          signal: input.signal
        })
      : {
          reclaimed: false,
          reason: "isolated runtime has no verified workspace root or backend port",
          verifiedPid: undefined
        };
  } catch (error: unknown) {
    return settleFailed(
      `isolated backend retirement failed: ${error instanceof Error ? error.message : String(error)}`
    );
  }
  const stillCurrentAfterReclaim = fenceOpen();
  const registeredSpawnPidAlive = registeredSpawnPid > 0 && dependencies.pidAlive(registeredSpawnPid);
  const backendConfirmedClosed = staleReclaim.reclaimed && !registeredSpawnPidAlive;
  const runtimeCleanup = backendConfirmedClosed
    ? dependencies.clearRuntimeState(workspaceRoot)
    : null;
  const message = isolatedRetireIncompleteMessage({
    staleReclaim,
    backendConfirmedClosed,
    registeredSpawnPid,
    registeredSpawnPidAlive,
    port,
    runtimeCleanup
  });
  if (!backendConfirmedClosed || runtimeCleanup?.failedCount) {
    return settleFailed(
      stillCurrentAfterReclaim
        ? message
        : `${message}; lifecycle intent was superseded during retirement`
    );
  }

  const completed = await dependencies.completeStop(registryPath, {
    instanceId: input.instanceId,
    expectedGeneration: generation
  });
  if (!completed.applied) {
    return {
      ok: false,
      code: "backend_retire_incomplete",
      generation,
      message: "isolated backend retirement lost its registry generation before completion"
    };
  }
  if (input.successFailureMessage) {
    const failed = await dependencies.upsert(
      registryPath,
      input.instanceId,
      {
        status: "failed",
        phase: "failed",
        desiredState: "open",
        failureMessage: input.successFailureMessage
      },
      generation
    );
    if (!failed.applied) {
      return {
        ok: false,
        code: "backend_retire_incomplete",
        generation,
        message: "isolated start failure cleanup lost its registry generation"
      };
    }
  }
  return { ok: true };
}

export async function claimIsolatedStop(input: {
  instanceId: string;
  branchInstances?: unknown;
  projectRoot?: string;
  commandId?: string;
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
      projectRoot: input.projectRoot || target?.projectRoot || "",
      commandId: input.commandId
    },
    input.storeOptions
  );
}

export async function completeIsolatedStop(input: {
  instanceId: string;
  expectedGeneration?: number;
  registryPath?: string;
  storeOptions?: RegistryStoreOptions;
}): Promise<ObserveResult> {
  return completeStop(
    input.registryPath || instancesRegistryPath(),
    {
      instanceId: input.instanceId,
      expectedGeneration: input.expectedGeneration
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
