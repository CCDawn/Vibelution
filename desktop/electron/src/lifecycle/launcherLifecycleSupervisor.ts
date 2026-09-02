import { PythonJsonBridgeError } from "../process/pythonJsonBridge.js";

export type LauncherDesiredState = "open" | "closed";

export type LauncherLifecycleOperation =
  | "start"
  | "stop"
  | "force-stop"
  | "restart"
  | "rebuild-and-start"
  | "shutdown"
  | "close";

export type LauncherLifecyclePhase = "intent" | "observing" | "ready" | "uncertain";

export type LauncherLifecycleLease = {
  revision: number;
  desiredState: LauncherDesiredState;
  instanceId: string;
  operation: LauncherLifecycleOperation;
  commandId: string;
  generation: number;
  signal: AbortSignal;
};

export type LauncherLifecycleIntent = {
  desiredState: LauncherDesiredState;
  instanceId: string;
  operation: LauncherLifecycleOperation;
  generation?: number;
};

export type LauncherLifecycleSnapshot = Omit<LauncherLifecycleLease, "signal"> & {
  phase: LauncherLifecyclePhase;
  readyClaimed: boolean;
};

export type LauncherLifecycleBeginOptions = {
  /**
   * Window-level and forwarded stop provenance must never abort an in-flight
   * restart or rebuild-and-start lease: killing the mutation mid stop+start
   * leaves the backend down and the command never settles. When set and the
   * current lease for this instance is an actively running restart or
   * rebuild-and-start (intent phase, mutation still executing), the begin
   * returns that lease for joining instead of aborting. Every other in-flight
   * lease keeps the unconditional supersede semantics, and an operator stop
   * supersedes a restart or rebuild exactly as before.
   */
  joinInFlightRestart?: boolean;
};

export type LauncherLifecycleBeginResult =
  | { outcome: "begun"; lease: LauncherLifecycleLease }
  | { outcome: "joined-in-flight-restart"; lease: LauncherLifecycleLease };

type LifecycleSlot = {
  lease: LauncherLifecycleLease;
  controller: AbortController;
  phase: LauncherLifecyclePhase;
  readyClaimed: boolean;
};

export type LifecycleMutationResult<T> =
  | { outcome: "committed"; value: T }
  | { outcome: "superseded"; value: T }
  | { outcome: "ignored" }
  | { outcome: "uncertain"; reconciliationError?: Error }
  | { outcome: "failed"; error: Error };

function normalizedGeneration(value: number | undefined): number | null {
  if (!Number.isFinite(value) || Number(value) <= 0) {
    return null;
  }
  return Math.trunc(Number(value));
}

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}

export function isUncertainMutationError(error: unknown): boolean {
  return error instanceof PythonJsonBridgeError && error.code === "uncertain_mutation";
}

/**
 * Electron main's in-memory lifecycle authority.
 *
 * Revisions are global and monotonic for diagnostics. Each instance owns one
 * current lease and one mutation queue, so a command for instance A cannot
 * cancel or serialize unrelated work for instance B.
 */
export class LauncherLifecycleSupervisor {
  private nextRevision = 0;
  private readonly slots = new Map<string, LifecycleSlot>();
  private readonly generations = new Map<string, number>();
  private readonly mutationTails = new Map<string, Promise<void>>();

  beginIntent(intent: LauncherLifecycleIntent): LauncherLifecycleLease {
    return this.beginIntentWithOptions(intent).lease;
  }

  /**
   * beginIntent with optional join semantics; see LauncherLifecycleBeginOptions.
   */
  beginIntentWithOptions(
    intent: LauncherLifecycleIntent,
    options: LauncherLifecycleBeginOptions = {},
  ): LauncherLifecycleBeginResult {
    const instanceId = intent.instanceId.trim();
    if (!instanceId) {
      throw new Error("launcher lifecycle instance id is required");
    }
    if (options.joinInFlightRestart === true) {
      const joinable = this.joinableInFlightMutationSlot(instanceId);
      if (joinable) {
        return { outcome: "joined-in-flight-restart", lease: joinable.lease };
      }
    }
    const previous = this.slots.get(instanceId);
    previous?.controller.abort(new Error(`launcher lifecycle intent superseded for ${instanceId}`));

    this.nextRevision += 1;
    const explicitGeneration = normalizedGeneration(intent.generation);
    const generation = explicitGeneration ?? ((this.generations.get(instanceId) ?? 0) + 1);
    this.generations.set(instanceId, Math.max(this.generations.get(instanceId) ?? 0, generation));
    const controller = new AbortController();
    const lease: LauncherLifecycleLease = {
      revision: this.nextRevision,
      desiredState: intent.desiredState,
      instanceId,
      operation: intent.operation,
      commandId: "",
      generation,
      signal: controller.signal,
    };
    this.slots.set(instanceId, {
      lease,
      controller,
      phase: "intent",
      readyClaimed: false,
    });
    return { outcome: "begun", lease };
  }

  /**
   * A restart or rebuild-and-start lease is joinable only while its mutation
   * may still be executing (intent phase). Once the mutation settles,
   * bindCommand moves the lease to observing and a later stop may supersede it
   * exactly as before.
   */
  private joinableInFlightMutationSlot(instanceId: string): LifecycleSlot | null {
    const slot = this.slots.get(instanceId);
    if (!slot || slot.controller.signal.aborted) {
      return null;
    }
    const joinableOperation = slot.lease.operation === "restart"
      || slot.lease.operation === "rebuild-and-start";
    if (!joinableOperation || slot.phase !== "intent") {
      return null;
    }
    return slot;
  }

  /**
   * Drops the slot for a lease whose mutation failed permanently. Without this
   * the dead lease would keep occupying the instance in intent phase and a
   * later join-eligible stop would keep joining a restart that can never
   * finish. Only the exact lease (revision + abort signal identity) is
   * cleared; a newer intent for the same instance is never touched.
   */
  clearSlotIfCurrent(lease: LauncherLifecycleLease): boolean {
    const slot = this.slots.get(lease.instanceId);
    if (!slot || slot.lease.revision !== lease.revision || slot.controller.signal !== lease.signal) {
      return false;
    }
    return this.slots.delete(lease.instanceId);
  }

  bindCommand(
    lease: LauncherLifecycleLease,
    input: { commandId: string; generation?: number },
  ): LauncherLifecycleLease | null {
    if (!this.isCurrent(lease)) {
      return null;
    }
    const commandId = input.commandId.trim();
    if (!commandId) {
      throw new Error("launcher lifecycle command id is required");
    }
    const slot = this.slots.get(lease.instanceId);
    if (!slot) {
      return null;
    }
    const generation = normalizedGeneration(input.generation) ?? lease.generation;
    this.generations.set(
      lease.instanceId,
      Math.max(this.generations.get(lease.instanceId) ?? 0, generation),
    );
    const bound = { ...lease, commandId, generation };
    slot.lease = bound;
    slot.phase = "observing";
    slot.readyClaimed = false;
    return bound;
  }

  isCurrent(lease: LauncherLifecycleLease): boolean {
    const slot = this.slots.get(lease.instanceId);
    if (!slot || lease.signal.aborted || slot.controller.signal.aborted) {
      return false;
    }
    const current = slot.lease;
    return (
      current.signal === lease.signal
      && current.revision === lease.revision
      && current.commandId === lease.commandId
      && current.generation === lease.generation
      && current.desiredState === lease.desiredState
      && current.instanceId === lease.instanceId
      && current.operation === lease.operation
    );
  }

  claimReady(lease: LauncherLifecycleLease): boolean {
    const slot = this.slots.get(lease.instanceId);
    if (
      !slot
      || !this.isCurrent(lease)
      || lease.desiredState !== "open"
      || !lease.commandId
      || slot.phase !== "observing"
      || slot.readyClaimed
    ) {
      return false;
    }
    slot.readyClaimed = true;
    return true;
  }

  completeReady(lease: LauncherLifecycleLease): boolean {
    const slot = this.slots.get(lease.instanceId);
    if (
      !slot
      || !this.isCurrent(lease)
      || lease.desiredState !== "open"
      || !lease.commandId
      || slot.phase !== "observing"
      || !slot.readyClaimed
    ) {
      return false;
    }
    slot.phase = "ready";
    return true;
  }

  releaseReadyClaim(lease: LauncherLifecycleLease): boolean {
    const slot = this.slots.get(lease.instanceId);
    if (
      !slot
      || !this.isCurrent(lease)
      || slot.phase !== "observing"
      || !slot.readyClaimed
    ) {
      return false;
    }
    slot.readyClaimed = false;
    return true;
  }

  snapshot(instanceId: string): LauncherLifecycleSnapshot | null {
    const slot = this.slots.get(instanceId.trim());
    if (!slot) {
      return null;
    }
    const { signal: _signal, ...lease } = slot.lease;
    return {
      ...lease,
      phase: slot.phase,
      readyClaimed: slot.readyClaimed,
    };
  }

  async executeMutation<T>(input: {
    lease: LauncherLifecycleLease;
    mutate: (lease: LauncherLifecycleLease) => Promise<T>;
    reconcile: (lease: LauncherLifecycleLease) => Promise<void>;
  }): Promise<LifecycleMutationResult<T>> {
    const instanceId = input.lease.instanceId;
    const previous = this.mutationTails.get(instanceId) ?? Promise.resolve();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const tail = previous.catch(() => undefined).then(() => gate);
    this.mutationTails.set(instanceId, tail);

    await previous.catch(() => undefined);
    try {
      if (!this.isCurrent(input.lease)) {
        return { outcome: "ignored" };
      }
      let value: T;
      try {
        value = await input.mutate(input.lease);
      } catch (error: unknown) {
        if (!this.isCurrent(input.lease)) {
          return { outcome: "ignored" };
        }
        if (!isUncertainMutationError(error)) {
          return { outcome: "failed", error: asError(error) };
        }
        const slot = this.slots.get(instanceId);
        if (slot && this.isCurrent(input.lease)) {
          slot.phase = "uncertain";
        }
        try {
          await input.reconcile(input.lease);
          return { outcome: "uncertain" };
        } catch (reconciliationError: unknown) {
          return { outcome: "uncertain", reconciliationError: asError(reconciliationError) };
        }
      }
      if (!this.isCurrent(input.lease)) {
        return { outcome: "superseded", value };
      }
      return { outcome: "committed", value };
    } finally {
      release();
      void tail.finally(() => {
        if (this.mutationTails.get(instanceId) === tail) {
          this.mutationTails.delete(instanceId);
        }
      });
    }
  }
}
