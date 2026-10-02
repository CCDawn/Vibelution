import { statSync } from "node:fs";
import { randomUUID } from "node:crypto";

import {
  IN_FLIGHT_STATUSES,
  PORT_LEASE_RECLAIMABLE,
  REGISTRY_OBSERVATION_GRACE_MS,
  START_SUPERVISOR_LOST_MESSAGE,
  adoptLiveInstance,
  closeConfirmedDeadInstance,
  isStaleInFlightStart,
  instancesRegistryPath,
  readRegistry,
  sweepTerminatedRows,
  type RegistryEntry,
  type RegistryStoreOptions,
  type SweepGraceTracker
} from "./instanceRegistryStore.js";
import { knownPidIsAlive } from "./mainLine/observation.js";
import { capturePythonProcessIdentity } from "../process/pythonJsonBridge.js";

/**
 * State-refresh driven registry reconciliation (SSOT repair).
 *
 * After every successful state refresh Electron compares the Python runtime
 * observation (worktree state.json live pids + port listening) against the
 * registry:
 * - adopt: a live backend sitting on a missing/terminal/handle-free row is
 *   re-bound to that row (steady, held lease, observed pid and port);
 * - close-dead: a row claiming a live runtime whose registered spawn identity
 *   is confirmed dead settles to closed (steady) or failed (stale in-flight
 *   start);
 * - sweep: terminal rows with no live identity whose worktree path is gone are
 *   deleted after the 10s observation grace.
 *
 * Electron is the only product writer of the registry, so this pass is the
 * single place where observation truth flows back into the SSOT without a
 * user-driven lifecycle command. Python's preview reconcile stays read-only.
 */

export const RECONCILE_ATTEMPT_COOLDOWN_MS = 15_000;

type LiveBackendObservation = {
  projectRoot: string;
  branch: string;
  pid: number;
  port: number;
  controlPort: number;
};

type ObservationSummary = {
  liveBackends: Map<string, LiveBackendObservation>;
  openWindowIds: Set<string>;
};

export type ReconcileRegistryWithObservationInput = {
  branchInstances: unknown;
  registryPath?: string;
  nowMs?: number;
  pythonPath?: string;
  storeOptions?: RegistryStoreOptions;
};

export type ReconcileWithObservationResult = {
  adopted: string[];
  closed: string[];
  failed: string[];
  swept: string[];
};

export type ReconcilerDependencies = {
  readRegistry: typeof readRegistry;
  adoptLiveInstance: typeof adoptLiveInstance;
  closeConfirmedDeadInstance: typeof closeConfirmedDeadInstance;
  sweepTerminatedRows: typeof sweepTerminatedRows;
  captureIdentity: typeof capturePythonProcessIdentity;
  pidAlive: (pid: number) => boolean;
  pathExists: (path: string) => boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function positiveInt(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : 0;
}

function normalizedStatus(entry: RegistryEntry): string {
  return String(entry.status || "").trim().toLowerCase();
}

function holdsLease(entry: RegistryEntry): boolean {
  return !PORT_LEASE_RECLAIMABLE.has(String(entry.portLeaseStatus || "").trim().toLowerCase());
}

/** Raw runtime signals from the state-refresh payload (never UI terminal states). */
export function observeBranchInstanceRuntimes(branchInstances: unknown): ObservationSummary {
  const items = isRecord(branchInstances) && Array.isArray(branchInstances.items)
    ? branchInstances.items.filter(isRecord)
    : [];
  const liveBackends = new Map<string, LiveBackendObservation>();
  const openWindowIds = new Set<string>();
  for (const item of items) {
    const instanceId = text(item.id);
    if (!instanceId || item.current === true) {
      // The current item is the main-line workbench; its lifecycle is owned by
      // the Electron main backend machinery, not the isolated registry.
      continue;
    }
    const runtime = isRecord(item.runtime) ? item.runtime : {};
    const backend = isRecord(runtime.backend) ? runtime.backend : {};
    const window = isRecord(runtime.window) ? runtime.window : {};
    if (window.open === true) {
      openWindowIds.add(instanceId);
    }
    const pid = positiveInt(backend.pid);
    const port = positiveInt(backend.port);
    if (
      backend.alive === true
      && pid > 0
      && port > 0
      && backend.listening === true
      && backend.portConflict !== true
    ) {
      liveBackends.set(instanceId, {
        projectRoot: text(item.path) || text(item.projectRoot),
        branch: text(item.branch),
        pid,
        port,
        controlPort: positiveInt(item.controlPort)
      });
    }
  }
  return { liveBackends, openWindowIds };
}

/** True when the row no longer matches the live observation and needs adopt. */
function needsAdopt(entry: RegistryEntry | undefined, live: LiveBackendObservation): boolean {
  if (!entry) {
    return true;
  }
  if (IN_FLIGHT_STATUSES.has(normalizedStatus(entry)) || Boolean(entry.cleanupInProgress)) {
    return false;
  }
  return !(
    normalizedStatus(entry) === "steady"
    && String(entry.desiredState || "").trim().toLowerCase() === "open"
    && positiveInt(entry.spawnPid) === live.pid
    && positiveInt(entry.port) === live.port
    && holdsLease(entry)
  );
}

export type InstanceRegistryReconciler = {
  reconcile: (
    input: ReconcileRegistryWithObservationInput
  ) => Promise<ReconcileWithObservationResult>;
};

export function createInstanceRegistryReconciler(overrides: {
  dependencies?: Partial<ReconcilerDependencies>;
  cooldownMs?: number;
  graceMs?: number;
} = {}): InstanceRegistryReconciler {
  const dependencies: ReconcilerDependencies = {
    readRegistry,
    adoptLiveInstance: (registryPath, input, options) => adoptLiveInstance(registryPath, input, options),
    closeConfirmedDeadInstance: (registryPath, input, options) =>
      closeConfirmedDeadInstance(registryPath, input, options),
    sweepTerminatedRows: (registryPath, input, options) => sweepTerminatedRows(registryPath, input, options),
    captureIdentity: capturePythonProcessIdentity,
    pidAlive: knownPidIsAlive,
    pathExists: (path: string) => {
      try {
        return statSync(path).isDirectory();
      } catch {
        return false;
      }
    },
    ...(overrides.dependencies || {})
  };
  const cooldownMs = Math.max(0, overrides.cooldownMs ?? RECONCILE_ATTEMPT_COOLDOWN_MS);
  const graceMs = Math.max(0, overrides.graceMs ?? REGISTRY_OBSERVATION_GRACE_MS);
  const lastAttemptAt = new Map<string, number>();
  const sweepGrace: SweepGraceTracker = new Map();
  const deadGrace: SweepGraceTracker = new Map();
  let inFlight: Promise<ReconcileWithObservationResult> | null = null;

  function cooledDown(instanceId: string, nowMs: number): boolean {
    const last = lastAttemptAt.get(instanceId);
    return last !== undefined && nowMs - last < cooldownMs;
  }

  async function run(input: ReconcileRegistryWithObservationInput): Promise<ReconcileWithObservationResult> {
    const registryPath = input.registryPath || instancesRegistryPath();
    const nowMs = input.nowMs ?? Date.now();
    const observation = observeBranchInstanceRuntimes(input.branchInstances);
    const registry = await dependencies.readRegistry(registryPath);
    const result: ReconcileWithObservationResult = { adopted: [], closed: [], failed: [], swept: [] };

    for (const [instanceId, live] of observation.liveBackends) {
      if (cooledDown(instanceId, nowMs) || !needsAdopt(registry.instances[instanceId], live)) {
        continue;
      }
      // Charge the cooldown before the async identity capture so a slow bridge
      // cannot turn one jittery probe into a capture storm.
      lastAttemptAt.set(instanceId, nowMs);
      const registeredPid = positiveInt(registry.instances[instanceId]?.spawnPid);
      const registeredSpawnPidAlive =
        registeredPid > 0 && registeredPid !== live.pid && dependencies.pidAlive(registeredPid);
      let identity: Awaited<ReturnType<typeof dependencies.captureIdentity>> = null;
      if (input.pythonPath) {
        identity = await dependencies.captureIdentity({
          pythonPath: input.pythonPath,
          workspaceRoot: live.projectRoot,
          pid: live.pid
        });
      }
      const applied = await dependencies.adoptLiveInstance(
        registryPath,
        {
          instanceId,
          projectRoot: live.projectRoot,
          branch: live.branch,
          observedPid: live.pid,
          observedPort: live.port,
          observedControlPort: live.controlPort,
          ...(identity ? { identity: { createTime: identity.createTime, executable: identity.executable } } : {}),
          commandId: `adopt:${randomUUID()}`,
          nowMs,
          registeredSpawnPidAlive
        },
        input.storeOptions
      );
      if (applied.applied) {
        result.adopted.push(instanceId);
      }
    }

    for (const [instanceId, entry] of Object.entries(registry.instances)) {
      if (observation.liveBackends.has(instanceId) || observation.openWindowIds.has(instanceId)) {
        deadGrace.delete(instanceId);
        continue;
      }
      const spawnPid = positiveInt(entry.spawnPid);
      if (spawnPid <= 0 || dependencies.pidAlive(spawnPid)) {
        deadGrace.delete(instanceId);
        continue;
      }
      if (cooledDown(instanceId, nowMs)) {
        continue;
      }
      const status = normalizedStatus(entry);
      let outcome: "closed" | "failed" | null = null;
      let failureMessage = "";
      if (status === "steady") {
        outcome = "closed";
      } else if (
        (status === "starting" || status === "restarting")
        && isStaleInFlightStart(entry, { nowMs })
      ) {
        outcome = "failed";
        failureMessage = START_SUPERVISOR_LOST_MESSAGE;
      }
      if (!outcome) {
        // Non-stale in-flight rows have a live supervisor; stopping rows need
        // an independently verified retirement. Never close them here.
        continue;
      }
      const fingerprint = `${spawnPid}|${positiveInt(entry.generation)}`;
      const prev = deadGrace.get(instanceId);
      if (!prev || prev.fingerprint !== fingerprint) {
        deadGrace.set(instanceId, { since: nowMs, fingerprint });
        continue;
      }
      if (nowMs - prev.since < graceMs) {
        continue;
      }
      deadGrace.delete(instanceId);
      lastAttemptAt.set(instanceId, nowMs);
      const applied = await dependencies.closeConfirmedDeadInstance(
        registryPath,
        {
          instanceId,
          expectedGeneration: positiveInt(entry.generation),
          outcome,
          failureMessage,
          nowMs
        },
        input.storeOptions
      );
      if (applied.applied) {
        (outcome === "failed" ? result.failed : result.closed).push(instanceId);
      }
    }

    const swept = await dependencies.sweepTerminatedRows(
      registryPath,
      {
        nowMs,
        graceMs,
        pidAlive: dependencies.pidAlive,
        pathExists: dependencies.pathExists,
        protectedInstanceIds: [...observation.liveBackends.keys(), ...observation.openWindowIds],
        graceTracker: sweepGrace
      },
      input.storeOptions
    );
    result.swept = swept.removedInstanceIds;
    for (const instanceId of swept.removedInstanceIds) {
      lastAttemptAt.delete(instanceId);
      deadGrace.delete(instanceId);
    }
    return result;
  }

  return {
    reconcile: (input: ReconcileRegistryWithObservationInput) => {
      if (inFlight !== null) {
        return inFlight;
      }
      const pending = run(input).finally(() => {
        if (inFlight === pending) {
          inFlight = null;
        }
      });
      inFlight = pending;
      return pending;
    }
  };
}

const defaultReconciler = createInstanceRegistryReconciler();

/** Single-flight, cooldown-limited reconcile pass against the real registry. */
export function reconcileRegistryWithObservation(
  input: ReconcileRegistryWithObservationInput
): Promise<ReconcileWithObservationResult> {
  return defaultReconciler.reconcile(input);
}
