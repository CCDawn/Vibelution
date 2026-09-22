import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const JOB_TERMINATE_WAIT_MS = 8_000;
const JOB_TERMINATE_POLL_MS = 100;

export type WorkbenchJobHandle = object;

export type WorkbenchJobSpawnInput = {
  executable: string;
  arguments: string[];
  cwd: string;
  env: NodeJS.ProcessEnv;
  stdoutPath: string;
  stderrPath: string;
};

export type WorkbenchJobNative = {
  spawn: (input: WorkbenchJobSpawnInput) => { pid: number; job: WorkbenchJobHandle };
  terminate: (job: WorkbenchJobHandle) => boolean;
  activeCount: (job: WorkbenchJobHandle) => number;
  close: (job: WorkbenchJobHandle) => void;
};

type TrackedJob = {
  key: string;
  job: WorkbenchJobHandle;
};

const tracked = new Map<string, TrackedJob>();
let nativeOverride: WorkbenchJobNative | null | undefined;
let nativeModule: WorkbenchJobNative | null = null;

const requireNative = createRequire(import.meta.url);

function jobKey(workspaceRoot: string): string {
  return resolve(workspaceRoot).replaceAll("\\", "/").toLowerCase();
}

function addonCandidates(): string[] {
  const here = dirname(fileURLToPath(import.meta.url));
  return [
    join(here, "../native/workbench_job.node"),
    join(here, "../../native/workbench-job/build/Release/workbench_job.node")
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
  const key = jobKey(workspaceRoot);
  const previous = tracked.get(key);
  if (previous) {
    try {
      native.terminate(previous.job);
    } catch {
      // The previous group is replaced by the new job either way.
    }
    try {
      native.close(previous.job);
    } catch {
      // Closing a finished job is cleanup.
    }
    tracked.delete(key);
  }
  const spawned = native.spawn(input);
  tracked.set(key, { key, job: spawned.job });
  return { pid: spawned.pid };
}

export function hasTrackedWorkbenchJob(workspaceRoot: string): boolean {
  return tracked.has(jobKey(workspaceRoot));
}

async function waitUntilIdle(job: WorkbenchJobHandle, native: WorkbenchJobNative): Promise<boolean> {
  const deadline = Date.now() + JOB_TERMINATE_WAIT_MS;
  while (Date.now() < deadline) {
    if (native.activeCount(job) === 0) {
      return true;
    }
    await delay(JOB_TERMINATE_POLL_MS);
  }
  return native.activeCount(job) === 0;
}

export async function terminateTrackedWorkbenchJob(workspaceRoot: string): Promise<boolean> {
  const current = tracked.get(jobKey(workspaceRoot));
  if (!current) {
    return false;
  }
  const native = nativeOverride === undefined ? loadWorkbenchJobNative() : nativeOverride;
  if (native === null) {
    return false;
  }
  try {
    native.terminate(current.job);
  } catch {
    return false;
  }
  const idle = await waitUntilIdle(current.job, native);
  if (!idle) {
    return false;
  }
  try {
    native.close(current.job);
  } catch {
    // The group is already idle; dropping the handle is best-effort.
  }
  tracked.delete(current.key);
  return true;
}

export async function closeTrackedWorkbenchJob(workspaceRoot: string): Promise<boolean> {
  const current = tracked.get(jobKey(workspaceRoot));
  if (!current) {
    return false;
  }
  const native = nativeOverride === undefined ? loadWorkbenchJobNative() : nativeOverride;
  if (native === null) {
    return false;
  }
  try {
    native.close(current.job);
  } catch {
    return false;
  }
  tracked.delete(current.key);
  return true;
}
