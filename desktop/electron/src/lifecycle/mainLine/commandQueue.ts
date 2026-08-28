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

export const CLOSE_BACKOFF_BASE_MS = 2_000;
export const CLOSE_BACKOFF_MAX_MS = 60_000;

export const CLOSE_BACKOFF_COALESCED_CODE = "close_backoff_coalesced";

export type CloseBackoffCoalescedInfo = {
  operation: MainLineLifecycleOperation;
  /** Consecutive close executions observed before this coalesced request. */
  runs: number;
  /** The backoff window that absorbed this request, in milliseconds. */
  backoffMs: number;
  /** Milliseconds elapsed since the previous close settled. */
  ageMs: number;
};

/**
 * Exponential backoff window after the n-th consecutive close execution:
 * 2s, 4s, 8s, ... capped at CLOSE_BACKOFF_MAX_MS. During the window new close
 * requests are coalesced into the previous close's result instead of re-running
 * the retire sequence, which is what turned a web-side close retry loop into a
 * 1.5s-per-command, 40-minute storm on 2026-08-28.
 */
export function closeBackoffWindowMs(runs: number): number {
  const exponent = Math.max(0, Math.trunc(runs) - 1);
  return Math.min(CLOSE_BACKOFF_BASE_MS * 2 ** exponent, CLOSE_BACKOFF_MAX_MS);
}

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
  onCloseBackoffCoalesced?: (info: CloseBackoffCoalescedInfo) => void;
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
  let lastClose: {
    settledAtMs: number;
    runs: number;
    result: MainLineLifecycleResult;
  } | null = null;
  // The slot whose settlement produced lastClose. It stays addressable through
  // the queue's active/pending structures until its drain finally clears it, so
  // the join branch can tell a live in-flight close from the just-settled one.
  let settledCloseSlot: Slot | null = null;

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

  // Close-domain retry accounting. A close that settles — successfully,
  // rejected, or failed — starts (or extends) a backoff chain so retry loops
  // cannot re-run the retire sequence at wire speed. Any open/restart or an
  // explicit force_close settlement breaks the chain: the next close is then a
  // fresh intent and must execute immediately.
  const noteCloseSettlement = (slot: Slot, result: MainLineLifecycleResult): void => {
    if (slot.type === "close") {
      lastClose = {
        settledAtMs: now(),
        runs: (lastClose?.runs ?? 0) + 1,
        result: { ...result }
      };
      settledCloseSlot = slot;
      return;
    }
    lastClose = null;
    settledCloseSlot = null;
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
        noteCloseSettlement(next, result);
        next.resolve(result);
      },
      (error: unknown) => {
        noteCloseSettlement(next, {
          schemaVersion: 1,
          accepted: false,
          operation: next.operation,
          code: "execute_failed",
          message: error instanceof Error ? error.message.slice(0, 300) : String(error).slice(0, 300)
        });
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
      // A close that only "joins" the just-settled close slot (its drain
      // finally has not run yet) is actually a retry backoff case and is
      // handled by the coalescing branch below; a genuinely in-flight close
      // still joins normally.
      const joinedSettledClose = (mapped === "close" || mapped === "force_close")
        && joined !== null
        && joined === settledCloseSlot;
      if (joined && !joinedSettledClose) {
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

      // Close-domain backoff coalescing: when the queue is idle (or only the
      // just-settled close slot is still draining) and a close settled moments
      // ago, absorb the re-request into the previous close's result instead of
      // executing it again. Explicit force-close requests and supersede-
      // carrying closes (handled above) never hit this path.
      if (
        mapped === "close"
        && lastClose !== null
        && (!active || active.type === "close")
        && pending.length === 0
      ) {
        const backoffMs = closeBackoffWindowMs(lastClose.runs);
        const ageMs = now() - lastClose.settledAtMs;
        if (ageMs < backoffMs) {
          try {
            options.onCloseBackoffCoalesced?.({
              operation: input.operation,
              runs: lastClose.runs,
              backoffMs,
              ageMs
            });
          } catch {
            // Observability must not change queue semantics.
          }
          return Promise.resolve({
            ...lastClose.result,
            joined: true,
            code: CLOSE_BACKOFF_COALESCED_CODE,
            message: `Close re-request coalesced into the previous close result; close retry backoff window is ${Math.round(backoffMs / 1000)}s.`
          });
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
