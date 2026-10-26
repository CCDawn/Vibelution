import { randomBytes } from "node:crypto";
import { realpathSync } from "node:fs";
import { resolve } from "node:path";

// Settlement may need a durable queue fingerprint before the Python daemon has
// ever provisioned state.json. Keep this local to the actual queued object;
// promises must never leak into queue snapshots or protocol payloads.
const intentPersistenceByCommand = new WeakMap<object, () => Promise<void>>();

export async function waitForMainLineIntentPersistence(command: object): Promise<void> {
  await intentPersistenceByCommand.get(command)?.();
}

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
  /** Cancelled lease work must not occupy or later settle the current lane. */
  signal?: AbortSignal;
  noBrowser?: boolean;
  /** Trusted caller admission: persist request association before native effects. */
  onCommand?: (command: MainLineQueuedCommand) => Promise<void>;
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
    signal?: AbortSignal;
    detachAbort?: () => void;
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
  let latestPersistCommandId = "";
  let persistOrdinal = 0;
  let latestPersistOrdinal = 0;
  let intentPersistence: Promise<unknown> = Promise.resolve();
  const admissions = new WeakMap<object, {
    ready: Promise<void>; admitted: boolean; cancel: (reason: unknown) => void;
  }>();

  const admit = (input: MainLineSubmitInput, command: MainLineQueuedCommand): Promise<void> => {
    // Only metadata crosses this seam; never hand a callback the mutable Slot.
    const projection = {
      commandId: command.commandId, type: command.type,
      operation: command.operation, noBrowser: command.noBrowser,
    };
    const called = Promise.resolve().then(() => {
      input.signal?.throwIfAborted();
      return input.onCommand?.(projection);
    });
    if (!input.signal) return called;
    const signal = input.signal;
    let abort!: () => void;
    const cancelled = new Promise<never>((_resolve, reject) => {
      abort = () => reject(signal.reason ?? new Error("main-line lifecycle command aborted"));
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, { once: true });
    });
    return Promise.race([called, cancelled]).then(() => { signal.throwIfAborted(); })
      .finally(() => signal.removeEventListener("abort", abort));
  };

  const prepareAdmission = (input: MainLineSubmitInput, command: MainLineQueuedCommand): void => {
    if (!input.onCommand) return;
    let cancel!: (reason: unknown) => void;
    const cancelled = new Promise<never>((_resolve, reject) => { cancel = reject; });
    const entry = { ready: Promise.resolve(), admitted: false, cancel };
    entry.ready = Promise.race([admit(input, command), cancelled]).then(() => { entry.admitted = true; });
    // Pending commands may wait behind another command before drain observes failure.
    void entry.ready.catch(() => undefined);
    admissions.set(command, entry);
  };

  const execute = (input: MainLineSubmitInput, command: MainLineQueuedCommand): Promise<MainLineLifecycleResult> => {
    const admission = admissions.get(command);
    if (!admission) return input.execute(command);
    return admission.ready.then(() => {
      input.signal?.throwIfAborted();
      return input.execute(command);
    });
  };

  const persist = (command: MainLineQueuedCommand): void => {
    const ordinal = ++persistOrdinal;
    const markIntent = (): void => {
      if (ordinal > latestPersistOrdinal) {
        latestPersistOrdinal = ordinal;
        latestPersistCommandId = command.commandId;
      }
    };
    const admission = admissions.get(command);
    if (admission) void admission.ready.then(markIntent).catch(() => undefined);
    else markIntent();
    const snapshot: MainLineIntentSnapshot = {
      schemaVersion: 1,
      desiredState: desiredStateFor(command.type),
      operation: command.operation,
      commandId: command.commandId,
      updatedAt: new Date(now()).toISOString(),
    };
    // Atomic renames are individually safe but can finish out of order. Keep
    // recovery writes ordered without making close wait for disk I/O; skip
    // older snapshots that have not started writing yet.
    intentPersistence = intentPersistence.catch(() => undefined).then(() => {
      const write = (): void | Promise<void> => {
        if (latestPersistCommandId !== command.commandId) return;
        return options.persistIntent?.(snapshot);
      };
      const admission = admissions.get(command);
      return admission ? admission.ready.then(write) : write();
    }).catch(() => undefined);
    if (options.persistIntent) {
      intentPersistenceByCommand.set(command, async () => {
        let observed: Promise<unknown>;
        do {
          observed = intentPersistence;
          await observed;
        } while (observed !== intentPersistence);
      });
    }
    const writeMarker = (): void => {
      try { void Promise.resolve(options.writeOwnerMarker?.()).catch(() => undefined); }
      catch { /* Owner marker is best-effort for the daemon idle skip. */ }
    };
    if (admission) void admission.ready.then(writeMarker).catch(() => undefined);
    else writeMarker();
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
        if (active === next && !next.signal?.aborted) noteCloseSettlement(next, result);
        next.resolve(result);
      },
      (error: unknown) => {
        if (active === next && !next.signal?.aborted && (!admissions.has(next) || admissions.get(next)?.admitted)) noteCloseSettlement(next, {
          schemaVersion: 1,
          accepted: false,
          operation: next.operation,
          code: "execute_failed",
          message: error instanceof Error ? error.message.slice(0, 300) : String(error).slice(0, 300)
        });
        next.reject(error instanceof Error ? error : new Error(String(error)));
      },
    ).finally(() => {
      next.detachAbort?.();
      // An aborted command can finish after its replacement has started.
      if (active === next) {
        active = null;
        draining = false;
        drain();
      }
    });
  };

  return {
    submit(input) {
      if (input.signal?.aborted) return Promise.reject(input.signal.reason);
      const mapped = JOINABLE_OPERATIONS[input.operation];
      const noBrowser = Boolean(input.noBrowser);
      // Once an open intent is admitted, an older closed result cannot prove
      // closure anymore: that open can spawn and then be cancelled before its
      // promise settles. A following close must execute in that case.
      if (mapped === "open" || mapped === "restart" || input.operation === "rebuild-and-start") {
        lastClose = null;
        settledCloseSlot = null;
      }
      if (mapped === null) {
        const passthrough: MainLineQueuedCommand = {
          commandId: newCommandId(now()),
          type: input.operation === "shutdown" ? "close" : "restart",
          operation: input.operation,
          noBrowser,
        };
        prepareAdmission(input, passthrough);
        persist(passthrough);
        return execute(input, passthrough);
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
        const result = joined.result.then((result) => ({
          ...result,
          joined: true,
          message: result.message || "joined existing main-line lifecycle command",
        }));
        if (!input.onCommand) return result;
        // Observe both promises immediately even if the existing command fails first.
        return Promise.all([admit(input, joined), result]).then(([, value]) => value);
      }

      for (let index = pending.length - 1; index >= 0; index -= 1) {
        const item = pending[index];
        if (item && supersedesPending(mapped, item.type)) {
          pending.splice(index, 1);
          item.detachAbort?.();
          admissions.get(item)?.cancel(new Error("main-line lifecycle command superseded"));
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
          const result: MainLineSubmitResult = {
            ...lastClose.result,
            joined: true,
            code: CLOSE_BACKOFF_COALESCED_CODE,
            message: `Close re-request coalesced into the previous close result; close retry backoff window is ${Math.round(backoffMs / 1000)}s.`
          };
          if (!input.onCommand) return Promise.resolve(result);
          if (!settledCloseSlot) return Promise.reject(new Error("main-line close association unavailable"));
          return admit(input, settledCloseSlot).then(() => result);
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
        execute: (queued) => execute(input, queued),
        signal: input.signal,
        result,
        resolve,
        reject,
      };
      prepareAdmission(input, command);
      const abort = (): void => {
        command.detachAbort?.();
        admissions.get(command)?.cancel(input.signal?.reason ?? new Error("main-line lifecycle command aborted"));
        const index = pending.indexOf(command);
        if (index >= 0) pending.splice(index, 1);
        command.reject(input.signal?.reason ?? new Error("main-line lifecycle command aborted"));
        if (active === command) {
          active = null;
          draining = false;
          drain();
        }
      };
      command.detachAbort = () => input.signal?.removeEventListener("abort", abort);
      input.signal?.addEventListener("abort", abort, { once: true });
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

const PROJECT_QUEUE_LIMIT = 128;
const projectQueues = new Map<string, {
  runtimeManagerDir: string;
  queue: MainLineCommandQueue;
}>();

function canonicalQueuePath(path: string): string {
  const resolvedPath = resolve(path);
  let canonicalPath = resolvedPath;
  try {
    canonicalPath = realpathSync.native(resolvedPath);
  } catch {
    // New or temporarily unavailable paths still have a stable resolved key.
  }
  return process.platform === "win32" ? canonicalPath.toLowerCase() : canonicalPath;
}

export function getMainLineCommandQueueForProject(
  workspaceRoot: string,
  runtimeManagerDir: string,
  options?: Parameters<typeof createMainLineCommandQueue>[0],
): MainLineCommandQueue {
  const rootKey = canonicalQueuePath(workspaceRoot);
  const ownerDir = canonicalQueuePath(resolve(runtimeManagerDir));
  const existing = projectQueues.get(rootKey);
  if (existing) {
    if (existing.runtimeManagerDir !== ownerDir) {
      throw new Error("MAIN_LINE_QUEUE_OWNER_CHANGED");
    }
    return existing.queue;
  }
  if (projectQueues.size >= PROJECT_QUEUE_LIMIT) {
    throw new Error("MAIN_LINE_QUEUE_LIMIT");
  }
  const queue = createMainLineCommandQueue(options);
  projectQueues.set(rootKey, { runtimeManagerDir: ownerDir, queue });
  return queue;
}

export function getSharedMainLineCommandQueue(
  options?: Parameters<typeof createMainLineCommandQueue>[0],
): MainLineCommandQueue {
  sharedQueue ??= createMainLineCommandQueue(options);
  return sharedQueue;
}

export function resetSharedMainLineCommandQueueForTests(): void {
  sharedQueue = null;
  projectQueues.clear();
}
