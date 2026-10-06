import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { appendSupervisorEventFallback } from "../lifecycle/supervisorEventFallback.js";

const JOB_TERMINATE_WAIT_MS = 8_000;
const JOB_TERMINATE_POLL_MS = 100;
const JOB_REAP_INTERVAL_MS = 1_000;

export type WorkbenchJobHandle = object;

export type WorkbenchJobSpawnInput = {
  executable: string;
  arguments: string[];
  cwd: string;
  env: NodeJS.ProcessEnv;
  stdoutPath: string;
  stderrPath: string;
  /** Test seam; production keeps the native 64 MiB default. */
  maxLogBytes?: number;
};

export type WorkbenchJobDrainChannelStatus = {
  stream: "stdout" | "stderr";
  complete: boolean;
  errorCode: number;
  droppedBytes: number;
  rotations: number;
};

export type WorkbenchJobDrainStatus = {
  complete: boolean;
  channels: WorkbenchJobDrainChannelStatus[];
};

export type WorkbenchJobNative = {
  spawn: (input: WorkbenchJobSpawnInput) => { pid: number; job: WorkbenchJobHandle };
  terminate: (job: WorkbenchJobHandle) => boolean;
  activeCount: (job: WorkbenchJobHandle) => number;
  drainStatus: (job: WorkbenchJobHandle) => WorkbenchJobDrainStatus;
  close: (job: WorkbenchJobHandle) => void;
};

type TrackedJob = {
  key: string;
  workspaceRoot: string;
  pid: number;
  job: WorkbenchJobHandle;
  native: WorkbenchJobNative;
  retiring?: Promise<boolean>;
  released?: boolean;
};

const tracked = new Map<string, TrackedJob>();
let nativeOverride: WorkbenchJobNative | null | undefined;
let nativeModule: WorkbenchJobNative | null = null;
let reapTimer: ReturnType<typeof setInterval> | null = null;

function forgetJob(current: TrackedJob): void {
  current.released = true;
  if (tracked.get(current.key) === current) {
    tracked.delete(current.key);
  }
  if (tracked.size === 0 && reapTimer !== null) {
    clearInterval(reapTimer);
    reapTimer = null;
  }
}

function ensureReaper(): void {
  if (reapTimer !== null) return;
  reapTimer = setInterval(() => {
    for (const current of tracked.values()) {
      if (current.retiring) continue;
      try {
        const status = current.native.drainStatus(current.job);
        if (current.native.activeCount(current.job) === 0 && status.complete) {
          reportDrainIssues(current.workspaceRoot, status);
          current.native.close(current.job);
          forgetJob(current);
          continue;
        }
        try {
          process.kill(current.pid, 0);
        } catch (error: unknown) {
          if ((error as NodeJS.ErrnoException).code === "ESRCH") {
            // The owned root exited but left children in its Job. Reclaim the
            // same group; never infer ownership from a later process-tree walk.
            void terminateTrackedWorkbenchJob(current.key, current.pid);
          }
        }
      } catch {
        // Keep ownership for a later reconciliation if native inspection fails.
      }
    }
  }, JOB_REAP_INTERVAL_MS);
  reapTimer.unref?.();
}

const requireNative = createRequire(import.meta.url);

function jobKey(workspaceRoot: string): string {
  return resolve(workspaceRoot).replaceAll("\\", "/").toLowerCase();
}

function addonCandidates(): string[] {
  const here = dirname(fileURLToPath(import.meta.url));
  return [
    join(here, "../native/workbench_job.node"),
    join(here, "../../dist/native/workbench_job.node")
  ];
}

export function loadWorkbenchJobNative(): WorkbenchJobNative {
  if (nativeOverride !== undefined) {
    if (nativeOverride === null) {
      throw new Error("workbench job native binding is disabled");
    }
    return nativeOverride;
  }
  if (nativeModule !== null) {
    return nativeModule;
  }
  const found = addonCandidates().find((candidate) => existsSync(candidate));
  if (!found) {
    throw new Error(
      `Windows workbench job addon is not built. Run npm run build:job in desktop/electron. Looked in ${addonCandidates().join(", ")}`
    );
  }
  nativeModule = requireNative(found) as WorkbenchJobNative;
  return nativeModule;
}

export function __setWorkbenchJobNativeForTests(native: WorkbenchJobNative | null | undefined): void {
  for (const current of tracked.values()) {
    try { current.native.close(current.job); } catch { /* Test teardown. */ }
  }
  if (reapTimer !== null) clearInterval(reapTimer);
  reapTimer = null;
  nativeOverride = native;
  nativeModule = null;
  tracked.clear();
}

function delay(ms: number): Promise<void> {
  return new Promise((resolveDelay) => {
    setTimeout(resolveDelay, ms);
  });
}

export function spawnTrackedWorkbenchProcess(
  workspaceRoot: string,
  input: WorkbenchJobSpawnInput
): { pid: number } {
  const native = loadWorkbenchJobNative();
  if (typeof native.drainStatus !== "function") {
    throw new Error("workbench job native binding does not expose bounded stdio drain status; rebuild the desktop addon");
  }
  const key = jobKey(workspaceRoot);
  const previous = tracked.get(key);
  if (previous) {
    let idle = false;
    try {
      idle = previous.native.activeCount(previous.job) === 0
        && previous.native.drainStatus(previous.job).complete;
    } catch {
      throw new Error("previous workbench job retirement could not be inspected");
    }
    if (!idle) {
      if (!previous.retiring && !previous.native.terminate(previous.job)) {
        throw new Error("previous workbench job termination was not confirmed");
      }
      // The old Job remains registered until the process tree and both output
      // drains finish. A caller retries after reconciliation rather than
      // reopening the same log files while a drain still owns them.
      ensureReaper();
      throw new Error("previous workbench job is still terminating or draining stdout/stderr");
    }
    reportDrainIssues(previous.workspaceRoot, previous.native.drainStatus(previous.job));
    previous.native.close(previous.job);
    forgetJob(previous);
  }
  const spawned = native.spawn(input);
  tracked.set(key, { key, workspaceRoot: resolve(workspaceRoot), pid: spawned.pid, job: spawned.job, native });
  ensureReaper();
  return { pid: spawned.pid };
}

export function hasTrackedWorkbenchJob(workspaceRoot: string): boolean {
  return tracked.has(jobKey(workspaceRoot));
}

/** Capture ownership before any asynchronous identity/readiness work. */
export function captureTrackedWorkbenchJobRetirement(workspaceRoot: string, pid: number): (() => Promise<boolean>) | null {
  const current = tracked.get(jobKey(workspaceRoot));
  if (!current || current.pid !== pid) return null;
  return async () => {
    if (current.released) return true;
    if (tracked.get(current.key) !== current) return false;
    return await retireJob(current);
  };
}

async function waitUntilIdle(job: WorkbenchJobHandle, native: WorkbenchJobNative, isReleased?: () => boolean): Promise<boolean> {
  const deadline = Date.now() + JOB_TERMINATE_WAIT_MS;
  while (Date.now() < deadline) {
    if (isReleased?.()) return true;
    if (native.activeCount(job) === 0 && native.drainStatus(job).complete) {
      return true;
    }
    await delay(JOB_TERMINATE_POLL_MS);
  }
  if (isReleased?.()) return true;
  return native.activeCount(job) === 0 && native.drainStatus(job).complete;
}

export async function terminateTrackedWorkbenchJob(workspaceRoot: string, expectedPid?: number): Promise<boolean> {
  const current = tracked.get(jobKey(workspaceRoot));
  if (!current || (expectedPid !== undefined && current.pid !== expectedPid)) {
    return false;
  }
  return await retireJob(current);
}

async function retireJob(current: TrackedJob): Promise<boolean> {
  if (current.retiring) return await current.retiring;
  const retirement = (async (): Promise<boolean> => {
    try {
      if (!current.native.terminate(current.job)) return false;
      if (!(await waitUntilIdle(current.job, current.native))) return false;
      // A replacement may already have closed this handle. Its registration
      // belongs to a different spawn and must survive this late completion.
      if (tracked.get(current.key) !== current) return true;
      reportDrainIssues(current.workspaceRoot, current.native.drainStatus(current.job));
      current.native.close(current.job);
      forgetJob(current);
      return true;
    } catch {
      return false;
    }
  })();
  current.retiring = retirement;
  try { return await retirement; } finally {
    if (current.retiring === retirement) current.retiring = undefined;
  }
}

export async function closeTrackedWorkbenchJob(workspaceRoot: string): Promise<boolean> {
  const current = tracked.get(jobKey(workspaceRoot));
  if (!current) {
    return false;
  }
  try {
    // Process exit can precede pipe draining. Preserve ownership while waiting,
    // and accept the reaper releasing this same handle during the wait.
    if (!(await waitUntilIdle(current.job, current.native, () => Boolean(current.released)))) {
      return false;
    }
    if (current.released) return true;
    if (tracked.get(current.key) !== current) return false;
    reportDrainIssues(current.workspaceRoot, current.native.drainStatus(current.job));
    current.native.close(current.job);
  } catch {
    return false;
  }
  forgetJob(current);
  return true;
}

function reportDrainIssues(workspaceRoot: string, status: WorkbenchJobDrainStatus): void {
  for (const channel of status.channels) {
    if (channel.errorCode === 0 && channel.droppedBytes === 0) continue;
    appendSupervisorEventFallback(workspaceRoot, {
      eventCode: "workbench_stdio_log_bounded_drain",
      message: `${channel.stream} log sink failed; remaining backend output was drained and discarded to keep the process unblocked.`,
      fields: {
        stream: channel.stream,
        errorCode: channel.errorCode,
        droppedBytes: Math.max(0, Math.trunc(channel.droppedBytes)),
        rotations: Math.max(0, Math.trunc(channel.rotations))
      }
    });
  }
}
