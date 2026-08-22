import { randomUUID } from "node:crypto";

import { knownPidIsAlive } from "./mainLine/observation.js";
import {
  claimStopIfGeneration,
  instancesRegistryPath,
  isStaleInFlightStart,
  isStaleInFlightStop,
  readRegistry,
  START_SUPERVISOR_LOST_MESSAGE,
  type RegistryEntry,
  type RegistryPayload
} from "./instanceRegistryStore.js";
import {
  retireClaimedIsolatedRuntime,
  type IsolatedStartRetireResult
} from "./isolatedInstanceRegistryHost.js";

type RecoveryDependencies = {
  readRegistry: (registryPath: string) => Promise<RegistryPayload>;
  claimStopIfGeneration: typeof claimStopIfGeneration;
  retireClaimed: typeof retireClaimedIsolatedRuntime;
  pidAlive: (pid: number) => boolean;
};

const DEFAULT_RECOVERY_DEPENDENCIES: RecoveryDependencies = {
  readRegistry,
  claimStopIfGeneration,
  retireClaimed: retireClaimedIsolatedRuntime,
  pidAlive: knownPidIsAlive
};

export type InstanceRegistryRecoveryResult = {
  reconciled: string[];
  retained: string[];
};

function positiveInt(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : 0;
}
function normalizedStatus(entry: RegistryEntry): string {
  return String(entry.status || "").trim().toLowerCase();
}

function normalizedDesiredState(entry: RegistryEntry): string {
  return String(entry.desiredState || "").trim().toLowerCase();
}

function ownerProcessGone(entry: RegistryEntry, pidAlive: (pid: number) => boolean): boolean {
  const ownerPid = positiveInt(entry.ownerPid);
  return ownerPid > 0 && !pidAlive(ownerPid);
}

function hasLiveRegisteredWindow(entry: RegistryEntry, pidAlive: (pid: number) => boolean): boolean {
  const windowPid = positiveInt(entry.windowPid);
  return windowPid > 0 && pidAlive(windowPid);
}

function isRecoverableOrphan(
  entry: RegistryEntry,
  nowMs: number,
  pidAlive: (pid: number) => boolean
): boolean {
  const status = normalizedStatus(entry);
  const desiredState = normalizedDesiredState(entry);
  if (status === "stopping" && desiredState === "closed") {
    return isStaleInFlightStop(entry, { nowMs }) || ownerProcessGone(entry, pidAlive);
  }
  if ((status === "starting" || status === "restarting") && desiredState === "open") {
    return isStaleInFlightStart(entry, { nowMs }) || ownerProcessGone(entry, pidAlive);
  }
  return false;
}

function recoveryFailureMessage(status: string): string | undefined {
  return status === "starting" || status === "restarting"
    ? START_SUPERVISOR_LOST_MESSAGE
    : undefined;
}

/**
 * Reconcile in-flight registry rows after an Electron supervisor restart.
 *
 * The registry deadline/owner PID only identifies a candidate; it never proves
 * that the backend has exited. Every candidate is fenced with a generation CAS
 * and passed through the existing health-identity retirement path. A failed
 * retirement therefore keeps the registered handles and port lease visible.
 */
export async function reconcileOrphanedInstanceRegistry(input: {
  registryPath?: string;
  nowMs?: number;
  dependencies?: Partial<RecoveryDependencies>;
} = {}): Promise<InstanceRegistryRecoveryResult> {
  const registryPath = input.registryPath || instancesRegistryPath();
  const nowMs = input.nowMs ?? Date.now();
  const dependencies: RecoveryDependencies = {
    ...DEFAULT_RECOVERY_DEPENDENCIES,
    ...(input.dependencies || {})
  };
  const registry = await dependencies.readRegistry(registryPath);
  const reconciled: string[] = [];
  const retained: string[] = [];

  for (const [instanceId, observed] of Object.entries(registry.instances)) {
    if (!isRecoverableOrphan(observed, nowMs, dependencies.pidAlive)) {
      continue;
    }
    if (hasLiveRegisteredWindow(observed, dependencies.pidAlive)) {
      retained.push(instanceId);
      continue;
    }

    const status = normalizedStatus(observed);
    const claimed = await dependencies.claimStopIfGeneration(registryPath, {
      instanceId,
      expectedGeneration: positiveInt(observed.generation),
      expectedCommandId: String(observed.commandId || "").trim() || undefined,
      projectRoot: String(observed.projectRoot || "").trim(),
      commandId: `startup-reconcile:${randomUUID()}`,
      nowMs
    });
    if (!claimed.applied) {
      // A concurrent lifecycle owner won the CAS; leave its newer row alone.
      retained.push(instanceId);
      continue;
    }

    let retired: IsolatedStartRetireResult;
    try {
      retired = await dependencies.retireClaimed({
        instanceId,
        workspaceRoot: String(claimed.entry.projectRoot || observed.projectRoot || "").trim(),
        entry: claimed.entry,
        registryPath,
        desiredStateOnFailure: status === "stopping" ? "closed" : "open",
        successFailureMessage: recoveryFailureMessage(status)
      });
    } catch {
      // The retirement owner is responsible for preserving the fenced row on
      // exceptions. Keep this recovery pass fail-closed as well.
      retained.push(instanceId);
      continue;
    }
    if (retired.ok) {
      reconciled.push(instanceId);
    } else {
      retained.push(instanceId);
    }
  }

  return { reconciled, retained };
}
