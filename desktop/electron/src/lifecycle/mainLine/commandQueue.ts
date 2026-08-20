import { randomBytes } from "node:crypto";

export type MainLineLifecycleOperation =
  | "start"
  | "stop"
  | "force-stop"
  | "restart"
  | "rebuild-and-start"
  | "shutdown";

export type MainLineLifecycleResult = {
  schemaVersion: 1;
  accepted: boolean;
  operation: string;
  commandId?: string;
  message?: string;
  code?: string;
  activeWorkRuns?: unknown[];
};

export type MainLineQueueType = "open" | "close" | "force_close" | "restart";

export type MainLineQueuedCommand = {
  commandId: string;
  type: MainLineQueueType;
  operation: MainLineLifecycleOperation;
  noBrowser: boolean;
};

export type MainLineSubmitInput = {
  operation: MainLineLifecycleOperation;
  noBrowser?: boolean;
  execute: (command: MainLineQueuedCommand) => Promise<MainLineLifecycleResult>;
};

export type MainLineSubmitResult = MainLineLifecycleResult & {
  joined?: boolean;
};

export type MainLineIntentSnapshot = {
  schemaVersion: 1;
  desiredState: "open" | "closed";
  operation: MainLineLifecycleOperation;
  commandId: string;
  updatedAt: string;
};

export type MainLineCommandQueue = {
  submit(input: MainLineSubmitInput): Promise<MainLineSubmitResult>;
  snapshot(): {
    active: MainLineQueuedCommand | null;
    pending: MainLineQueuedCommand[];
  };
};

const JOINABLE_OPERATIONS: Record<MainLineLifecycleOperation, MainLineQueueType | null> = {
  start: "open",
  stop: "close",
  "force-stop": "force_close",
  restart: "restart",
  "rebuild-and-start": null,
  shutdown: null,
};

function newCommandId(nowMs: number): string {
  const stamp = new Date(nowMs).toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
  return `cmd_${stamp}_${randomBytes(4).toString("hex")}`;
}

function desiredStateFor(type: MainLineQueueType): "open" | "closed" {
  return type === "close" || type === "force_close" ? "closed" : "open";
}

function openRequestsAreCompatible(existingNoBrowser: boolean, requestedNoBrowser: boolean): boolean {
  return !(existingNoBrowser && !requestedNoBrowser);
}

function isJoinable(existing: MainLineQueuedCommand, incoming: MainLineQueueType, noBrowser: boolean): boolean {
  if (incoming === "open") {
    return (
      (existing.type === "open" || existing.type === "restart")
      && openRequestsAreCompatible(existing.noBrowser, noBrowser)
    );
  }
  if (incoming === "restart") {
    return existing.type === "restart" && openRequestsAreCompatible(existing.noBrowser, noBrowser);
  }
  if (incoming === "close") {
    return existing.type === "close";
  }
  return existing.type === "close" || existing.type === "force_close";
}

function supersedesPending(incoming: MainLineQueueType, pending: MainLineQueueType): boolean {
  const incomingOpens = incoming === "open" || incoming === "restart";
  const pendingCloses = pending === "close" || pending === "force_close";
  if (incomingOpens && pendingCloses) {
    return true;
  }
  const incomingCloses = incoming === "close" || incoming === "force_close";
  const pendingOpens = pending === "open" || pending === "restart";
  return incomingCloses && pendingOpens;
}

function supersededResult(operation: MainLineLifecycleOperation): MainLineSubmitResult {
  return {
    schemaVersion: 1,
    accepted: false,
    operation,
    code: "lifecycle_intent_superseded",
    message: "A newer Launcher lifecycle intent superseded this command.",
  };
}

/**
 * In-process main-line open/close/restart queue.
 *
 * Join/supersede is adapted from Python `command_queue.py` (same-type join,
 * close supersedes pending open, open/restart supersedes pending close,
 * noBrowser compatibility). Execution stays a caller-supplied function so I5
 * can replace the Python lifecycle CLI without changing queue rules.
 */
export function createMainLineCommandQueue(options: {
  now?: () => number;
  persistIntent?: (intent: MainLineIntentSnapshot) => void | Promise<void>;
  writeOwnerMarker?: () => void | Promise<void>;
} = {}): MainLineCommandQueue {
  type Slot = MainLineQueuedCommand & {
    execute: MainLineSubmitInput["execute"];
    result: Promise<MainLineSubmitResult>;
    resolve: (result: MainLineSubmitResult) => void;
    reject: (error: unknown) => void;
  };

  const now = options.now ?? Date.now;
  let active: Slot | null = null;
  const pending: Slot[] = [];
  let draining = false;

  const persist = (command: MainLineQueuedCommand): void => {
    const snapshot: MainLineIntentSnapshot = {
      schemaVersion: 1,
      desiredState: desiredStateFor(command.type),
      operation: command.operation,
      commandId: command.commandId,
      updatedAt: new Date(now()).toISOString(),
    };
    try {
      void options.persistIntent?.(snapshot);
    } catch {
      // Persistence is crash-recovery assistance, not the execute path.
    }
    try {
      void options.writeOwnerMarker?.();
    } catch {
      // Owner marker is best-effort for the daemon idle skip.
    }
  };

  const findJoinable = (type: MainLineQueueType, noBrowser: boolean): Slot | null => {
    if (active && isJoinable(active, type, noBrowser)) {
      return active;
    }
    return pending.find((item) => isJoinable(item, type, noBrowser)) ?? null;
  };

  const drain = (): void => {
    if (draining || active !== null) {
      return;
    }
    const next = pending.shift();
    if (!next) {
      return;
    }
    draining = true;
    active = next;
    persist(next);
    void next.execute(next).then(
      (result) => {
        next.resolve(result);
      },
      (error: unknown) => {
        next.reject(error instanceof Error ? error : new Error(String(error)));
      },
    ).finally(() => {
      active = null;
      draining = false;
      drain();
    });
  };

  return {
    submit(input) {
      const mapped = JOINABLE_OPERATIONS[input.operation];
      const noBrowser = Boolean(input.noBrowser);
      if (mapped === null) {
        const passthrough: MainLineQueuedCommand = {
          commandId: newCommandId(now()),
          type: input.operation === "shutdown" ? "close" : "restart",
          operation: input.operation,
          noBrowser,
        };
        persist(passthrough);
        return input.execute(passthrough);
      }

      const joined = findJoinable(mapped, noBrowser);
      if (joined) {
        return joined.result.then((result) => ({
          ...result,
          joined: true,
          message: result.message || "joined existing main-line lifecycle command",
        }));
      }

      for (let index = pending.length - 1; index >= 0; index -= 1) {
        const item = pending[index];
        if (item && supersedesPending(mapped, item.type)) {
          pending.splice(index, 1);
          item.resolve(supersededResult(item.operation));
        }
      }

      let resolve!: (result: MainLineSubmitResult) => void;
      let reject!: (error: unknown) => void;
      const result = new Promise<MainLineSubmitResult>((next, fail) => {
        resolve = next;
        reject = fail;
      });
      const command: Slot = {
        commandId: newCommandId(now()),
        type: mapped,
        operation: input.operation,
        noBrowser,
        execute: input.execute,
        result,
        resolve,
        reject,
      };
      pending.push(command);
      persist(command);
      drain();
      return result;
    },
    snapshot() {
      return {
        active: active
          ? {
              commandId: active.commandId,
              type: active.type,
              operation: active.operation,
              noBrowser: active.noBrowser,
            }
          : null,
        pending: pending.map((item) => ({
          commandId: item.commandId,
          type: item.type,
          operation: item.operation,
          noBrowser: item.noBrowser,
        })),
      };
    },
  };
}

let sharedQueue: MainLineCommandQueue | null = null;

export function getSharedMainLineCommandQueue(
  options?: Parameters<typeof createMainLineCommandQueue>[0],
): MainLineCommandQueue {
  sharedQueue ??= createMainLineCommandQueue(options);
  return sharedQueue;
}

export function resetSharedMainLineCommandQueueForTests(): void {
  sharedQueue = null;
}
