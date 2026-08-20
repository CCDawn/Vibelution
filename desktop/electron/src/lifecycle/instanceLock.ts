import { mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";

export const LOCKDIR_SUFFIX = ".lockdir";
export const HOLDER_FILE_NAME = "holder.json";
export const LOCK_POLL_MS = 10;
export const LOCK_TIMEOUT_MS = 5000;
export const LOCK_STALE_MS = 10000;
export const MISSING_HOLDER_GRACE_MS = 100;
export const LOCK_STALE_BROKEN_EVENT = "launcher.registry.lock_stale_broken";

const REMOVE_ATTEMPTS = 8;
const REMOVE_RETRY_MS = 10;

export type InstanceLockHolder = {
  pid: number;
  startedAt: string;
};

export type InstanceLockEventPayload = {
  lockdir: string;
  previousPid: number | null;
  previousStartedAt: string;
  brokenAt: string;
  reason: "stale_started_at" | "missing_holder" | "invalid_holder";
};

export type InstanceLockEventEmitter = (
  eventName: typeof LOCK_STALE_BROKEN_EVENT,
  payload: InstanceLockEventPayload
) => void;

export type InstanceLockOptions = {
  timeoutMs?: number;
  staleMs?: number;
  pollMs?: number;
  missingHolderGraceMs?: number;
  pid?: number;
  nowMs?: () => number;
  sleep?: (ms: number) => Promise<void>;
  emitEvent?: InstanceLockEventEmitter;
};

export class InstanceLockTimeoutError extends Error {
  constructor(lockdir: string) {
    super(`Timed out acquiring instance registry lock: ${lockdir}`);
    this.name = "InstanceLockTimeoutError";
  }
}

export function instanceLockdirPath(registryPath: string): string {
  return `${registryPath}${LOCKDIR_SUFFIX}`;
}

export function holderFilePath(lockdir: string): string {
  return join(lockdir, HOLDER_FILE_NAME);
}

function isoTimestamp(ms: number): string {
  return new Date(ms).toISOString();
}

function sleepMs(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return typeof error === "object" && error !== null && "code" in error;
}

async function removeLockdir(lockdir: string): Promise<void> {
  for (let attempt = 0; attempt < REMOVE_ATTEMPTS; attempt += 1) {
    try {
      await rm(lockdir, { recursive: true, force: true });
      return;
    } catch (error) {
      if (attempt >= REMOVE_ATTEMPTS - 1) {
        throw error;
      }
      await sleepMs(REMOVE_RETRY_MS);
    }
  }
}

export async function readLockHolder(lockdir: string): Promise<InstanceLockHolder | null> {
  try {
    const parsed = JSON.parse(await readFile(holderFilePath(lockdir), "utf8")) as {
      pid?: unknown;
      startedAt?: unknown;
    };
    const pid = Number(parsed.pid);
    const startedAt = String(parsed.startedAt || "").trim();
    if (!Number.isInteger(pid) || pid <= 0 || !startedAt) {
      return null;
    }
    return { pid, startedAt };
  } catch {
    return null;
  }
}

export async function writeLockHolder(
  lockdir: string,
  holder: InstanceLockHolder
): Promise<void> {
  await writeFile(holderFilePath(lockdir), `${JSON.stringify(holder)}\n`, "utf8");
}

export async function plantLockdir(
  registryPath: string,
  holder: InstanceLockHolder
): Promise<string> {
  const lockdir = instanceLockdirPath(registryPath);
  await mkdir(lockdir, { recursive: true });
  await writeLockHolder(lockdir, holder);
  return lockdir;
}

async function lockdirAgeMs(lockdir: string, nowMs: number): Promise<number> {
  try {
    const info = await stat(lockdir);
    return Math.max(0, nowMs - info.mtimeMs);
  } catch {
    return 0;
  }
}

async function staleReason(
  lockdir: string,
  options: {
    nowMs: number;
    staleMs: number;
    missingHolderGraceMs: number;
  }
): Promise<InstanceLockEventPayload["reason"] | null> {
  const holder = await readLockHolder(lockdir);
  if (!holder) {
    return (await lockdirAgeMs(lockdir, options.nowMs)) >= options.missingHolderGraceMs
      ? "missing_holder"
      : null;
  }
  const startedMs = Date.parse(holder.startedAt);
  if (!Number.isFinite(startedMs)) {
    return (await lockdirAgeMs(lockdir, options.nowMs)) >= options.missingHolderGraceMs
      ? "invalid_holder"
      : null;
  }
  if (options.nowMs - startedMs >= options.staleMs) {
    return "stale_started_at";
  }
  return null;
}

async function breakStaleLockdir(
  lockdir: string,
  nowMs: number,
  reason: InstanceLockEventPayload["reason"],
  emitEvent?: InstanceLockEventEmitter
): Promise<void> {
  const holder = await readLockHolder(lockdir);
  await removeLockdir(lockdir);
  emitEvent?.(LOCK_STALE_BROKEN_EVENT, {
    lockdir,
    previousPid: holder?.pid ?? null,
    previousStartedAt: holder?.startedAt ?? "",
    brokenAt: isoTimestamp(nowMs),
    reason
  });
}

export async function withInstanceLock<T>(
  registryPath: string,
  fn: () => Promise<T> | T,
  options: InstanceLockOptions = {}
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? LOCK_TIMEOUT_MS;
  const staleMs = options.staleMs ?? LOCK_STALE_MS;
  const pollMs = options.pollMs ?? LOCK_POLL_MS;
  const missingHolderGraceMs = options.missingHolderGraceMs ?? MISSING_HOLDER_GRACE_MS;
  const ownerPid = options.pid ?? process.pid;
  const nowMs = options.nowMs ?? Date.now;
  const sleep = options.sleep ?? sleepMs;
  const lockdir = instanceLockdirPath(registryPath);
  const deadline = Date.now() + Math.max(0, timeoutMs);
  let startedAt = "";
  let owned = false;

  await mkdir(dirname(registryPath), { recursive: true });
  while (!owned) {
    try {
      await mkdir(lockdir);
      startedAt = isoTimestamp(nowMs());
      await writeLockHolder(lockdir, { pid: ownerPid, startedAt });
      owned = true;
      break;
    } catch (error) {
      if (!isNodeError(error) || error.code !== "EEXIST") {
        if (Date.now() >= deadline) {
          throw error;
        }
        await sleep(Math.max(0, pollMs));
        continue;
      }
      const now = nowMs();
      const reason = await staleReason(lockdir, { nowMs: now, staleMs, missingHolderGraceMs });
      if (reason) {
        await breakStaleLockdir(lockdir, now, reason, options.emitEvent);
        continue;
      }
      if (Date.now() >= deadline) {
        throw new InstanceLockTimeoutError(lockdir);
      }
      await sleep(Math.max(0, pollMs));
    }
  }

  try {
    return await fn();
  } finally {
    if (owned && startedAt) {
      const holder = await readLockHolder(lockdir);
      if (holder && holder.pid === ownerPid && holder.startedAt === startedAt) {
        await removeLockdir(lockdir);
      }
    }
  }
}
