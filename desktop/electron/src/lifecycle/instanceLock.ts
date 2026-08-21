import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
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
  pidAlive?: (pid: number) => boolean;
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
  // A contender must not mistake a partially written holder as an abandoned
  // lock. Publish the complete JSON in one same-directory rename.
  const target = holderFilePath(lockdir);
  const temporary = join(lockdir, `.${HOLDER_FILE_NAME}.${randomUUID()}.tmp`);
  try {
    await writeFile(temporary, `${JSON.stringify(holder)}\n`, "utf8");
    await rename(temporary, target);
  } finally {
    await rm(temporary, { force: true }).catch(() => undefined);
  }
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

function defaultPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return isNodeError(error) && error.code === "EPERM";
  }
}

function sameHolder(left: InstanceLockHolder | null, right: InstanceLockHolder | null): boolean {
  return Boolean(
    left
    && right
    && left.pid === right.pid
    && left.startedAt === right.startedAt
  );
}

function quarantinePath(lockdir: string, label: "stale" | "release"): string {
  return `${lockdir}.${label}-${process.pid}-${randomUUID()}`;
}

type StaleLock = {
  reason: InstanceLockEventPayload["reason"];
  holder: InstanceLockHolder | null;
};

async function staleReason(
  lockdir: string,
  options: {
    nowMs: number;
    staleMs: number;
    missingHolderGraceMs: number;
    pidAlive: (pid: number) => boolean;
  }
): Promise<StaleLock | null> {
  const holder = await readLockHolder(lockdir);
  if (!holder) {
    return (await lockdirAgeMs(lockdir, options.nowMs)) >= options.missingHolderGraceMs
      ? { reason: "missing_holder", holder: null }
      : null;
  }
  if (options.pidAlive(holder.pid)) {
    return null;
  }
  const startedMs = Date.parse(holder.startedAt);
  if (!Number.isFinite(startedMs)) {
    return (await lockdirAgeMs(lockdir, options.nowMs)) >= options.missingHolderGraceMs
      ? { reason: "invalid_holder", holder }
      : null;
  }
  if (options.nowMs - startedMs >= options.staleMs) {
    return { reason: "stale_started_at", holder };
  }
  return null;
}

async function breakStaleLockdir(
  lockdir: string,
  nowMs: number,
  stale: StaleLock,
  pidAlive: (pid: number) => boolean,
  emitEvent?: InstanceLockEventEmitter
): Promise<boolean> {
  const current = await readLockHolder(lockdir);
  if (stale.holder ? !sameHolder(current, stale.holder) : current !== null) {
    return false;
  }
  // Classification and rename are separate filesystem operations. A live
  // holder must never be quarantined based on an obsolete liveness sample.
  if (current && pidAlive(current.pid)) {
    return false;
  }
  const quarantinedPath = quarantinePath(lockdir, "stale");
  try {
    await rename(lockdir, quarantinedPath);
  } catch (error) {
    if (isNodeError(error) && error.code === "ENOENT") {
      return false;
    }
    throw error;
  }
  await removeLockdir(quarantinedPath);
  emitEvent?.(LOCK_STALE_BROKEN_EVENT, {
    lockdir,
    previousPid: stale.holder?.pid ?? null,
    previousStartedAt: stale.holder?.startedAt ?? "",
    brokenAt: isoTimestamp(nowMs),
    reason: stale.reason
  });
  return true;
}

async function releaseOwnedLockdir(
  lockdir: string,
  ownerPid: number,
  startedAt: string
): Promise<void> {
  const holder = await readLockHolder(lockdir);
  if (!holder || holder.pid !== ownerPid || holder.startedAt !== startedAt) {
    return;
  }
  const quarantinedPath = quarantinePath(lockdir, "release");
  try {
    await rename(lockdir, quarantinedPath);
  } catch (error) {
    if (isNodeError(error) && error.code === "ENOENT") {
      return;
    }
    throw error;
  }
  await removeLockdir(quarantinedPath);
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
  const pidAlive = options.pidAlive ?? defaultPidAlive;
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
      const stale = await staleReason(lockdir, { nowMs: now, staleMs, missingHolderGraceMs, pidAlive });
      if (stale && await breakStaleLockdir(lockdir, now, stale, pidAlive, options.emitEvent)) {
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
      await releaseOwnedLockdir(lockdir, ownerPid, startedAt);
    }
  }
}
