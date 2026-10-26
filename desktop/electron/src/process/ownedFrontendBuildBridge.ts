import { mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

import { pythonBridgeEnv } from "./pythonBridgeEnv.js";
import {
  DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES, PythonJsonBridgeError, pythonJsonBridgeFailureMessage
} from "./pythonJsonBridge.js";
import { loadWorkbenchJobNative, type WorkbenchJobHandle, type WorkbenchJobNative } from "./workbenchJob.js";

const POLL_MS = 20;
const RETIRE_WAIT_MS = 600;
const BUILD_WAIT_MS = 600_000;
const LOG_BYTES = 64 * 1024;

type BuildNative = WorkbenchJobNative & {
  exitCode: (job: WorkbenchJobHandle) => number | null;
};
type OwnedBuild = {
  key: string;
  job: WorkbenchJobHandle;
  native: BuildNative;
  directory: string;
  stdoutPath: string;
  stderrPath: string;
  released: boolean;
  failure?: PythonJsonBridgeError;
  retirement?: Promise<boolean>;
};

// Resource ownership only. The existing frontend builder remains the sole
// authority for release state; each invocation keeps its own exact Job handle.
const ownedBuilds = new Set<OwnedBuild>();
const workspaceKey = (root: string): string => resolve(root).replaceAll("\\", "/").toLowerCase();
const delay = (): Promise<void> => new Promise((done) => setTimeout(done, POLL_MS));

function failure(code: "aborted" | "timeout" | "output_limit" | "nonzero_exit", message: string): PythonJsonBridgeError {
  return code === "timeout"
    ? new PythonJsonBridgeError("uncertain_mutation", `${message}; the mutation outcome is uncertain and must be reconciled`, { causeCode: code })
    : new PythonJsonBridgeError(code, message);
}

function fileSize(path: string): number {
  try { return statSync(path).size; } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return 0;
    throw error;
  }
}

function readLog(path: string): string {
  try { return readFileSync(path, "utf8"); } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return "";
    throw error;
  }
}

function release(current: OwnedBuild): void {
  current.native.close(current.job);
  current.released = true;
  ownedBuilds.delete(current);
  // Never delete files still owned by native drain threads. Cleanup failure
  // does not change the independently confirmed process retirement.
  try { rmSync(current.directory, { recursive: true, force: true }); } catch { /* OS temp cleanup can be retried externally. */ }
}

function retire(current: OwnedBuild): Promise<boolean> {
  if (current.released) return Promise.resolve(true);
  if (current.retirement) return current.retirement;
  // Execute termination before the first await, including close-start capture.
  const operation = (async (): Promise<boolean> => {
    try {
      if (!current.native.terminate(current.job)) return false;
      const deadline = Date.now() + RETIRE_WAIT_MS;
      while (true) {
        if (current.released) return true;
        if (current.native.activeCount(current.job) === 0 && current.native.drainStatus(current.job).complete) {
          release(current);
          return true;
        }
        if (Date.now() >= deadline) return false;
        await delay();
      }
    } catch {
      // Keep the handle and bounded log directory for an exact-Job retry.
      return false;
    }
  })();
  current.retirement = operation;
  void operation.then(() => {
    if (current.retirement === operation) current.retirement = undefined;
  });
  return operation;
}

/** Capture the current Jobs synchronously; later builds never join this closure. */
export function captureFrontendBuildRetirement(workspaceRoot: string): () => Promise<boolean> {
  const key = workspaceKey(workspaceRoot);
  const captured = [...ownedBuilds].filter((current) => current.key === key);
  return async () => {
    const results = await Promise.all(captured.map((current) => {
      current.failure ??= failure("aborted", "frontend build preflight was aborted");
      return retire(current);
    }));
    return results.every(Boolean);
  };
}

/** Windows-only bridge: spawn, assign to Job, then resume in the native addon. */
export async function runOwnedFrontendBuildBridge(input: {
  workspaceRoot: string;
  pythonPath: string;
  args: string[];
  signal?: AbortSignal;
  env?: NodeJS.ProcessEnv;
}): Promise<string> {
  if (input.signal?.aborted) throw failure("aborted", "frontend build preflight was aborted before spawn");
  const native = loadWorkbenchJobNative() as BuildNative;
  if (typeof native.exitCode !== "function" || typeof native.drainStatus !== "function") {
    throw new Error("frontend build requires root exit status and bounded drains; rebuild the desktop addon");
  }
  const directory = mkdtempSync(join(tmpdir(), "vibelution-frontend-build-"));
  const stdoutPath = join(directory, "stdout.log");
  const stderrPath = join(directory, "stderr.log");
  let job: WorkbenchJobHandle;
  try {
    const spawnInput = {
      executable: input.pythonPath, arguments: input.args, cwd: input.workspaceRoot,
      env: pythonBridgeEnv(input.env), stdoutPath, stderrPath, maxLogBytes: LOG_BYTES,
      containDescendants: true
    };
    job = native.spawn(spawnInput).job;
  } catch (error) {
    rmSync(directory, { recursive: true, force: true });
    throw error;
  }
  const current: OwnedBuild = {
    key: workspaceKey(input.workspaceRoot), job, native, directory, stdoutPath, stderrPath, released: false
  };
  ownedBuilds.add(current); // Ownership is registered before any await.
  const onAbort = (): void => {
    current.failure ??= failure("aborted", "frontend build preflight was aborted");
    void retire(current);
  };
  input.signal?.addEventListener("abort", onAbort, { once: true });
  if (input.signal?.aborted) onAbort();
  const deadline = Date.now() + BUILD_WAIT_MS;
  let retirementAttempted = false;
  let rootExitDeadline: number | undefined;
  let descendantsTerminated = false;
  try {
    while (true) {
      if (current.failure) {
        retirementAttempted = true;
        const confirmed = await retire(current);
        if (!confirmed) {
          throw new Error("frontend build Job retirement was not confirmed; ownership and logs retained", { cause: current.failure });
        }
        throw current.failure;
      }
      if (Date.now() >= deadline) {
        current.failure = failure("timeout", "frontend build preflight timed out after 600000ms");
        continue;
      }
      const status = native.drainStatus(job);
      const stdout = status.channels.find((channel) => channel.stream === "stdout");
      if ((stdout?.rotations ?? 0) > 0 || fileSize(stdoutPath) > DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES) {
        current.failure = failure("output_limit", "frontend build preflight output exceeded limit");
        continue;
      }
      const code = native.exitCode(job);
      const active = native.activeCount(job);
      if (code !== null) rootExitDeadline ??= Date.now() + RETIRE_WAIT_MS;
      if (code !== null && active > 0 && !descendantsTerminated) {
        // The root exited, but descendants still own resources. Reclaim its
        // original Job before accepting either success or failure.
        if (!native.terminate(job)) throw new Error("frontend build descendant retirement was not confirmed");
        descendantsTerminated = true;
      }
      if (code !== null && active === 0 && status.complete) {
        const raw = readLog(stdoutPath);
        const stderr = readLog(stderrPath).slice(-800);
        const drainFailed = status.channels.some((channel) => channel.errorCode !== 0 || channel.droppedBytes > 0);
        release(current);
        if (drainFailed) throw new Error("frontend build output drain failed");
        if (code !== 0) throw failure("nonzero_exit", pythonJsonBridgeFailureMessage(raw, stderr, `frontend build preflight exited with code ${code}`));
        return raw;
      }
      if (rootExitDeadline !== undefined && Date.now() >= rootExitDeadline) {
        throw new Error("frontend build exited but Job processes or output drains remain unconfirmed");
      }
      await delay();
    }
  } catch (error) {
    // A failed inspection cannot erase ownership or leave an executing build
    // uncontrolled. Retirement itself never substitutes for a successful build.
    if (!current.released && !retirementAttempted) await retire(current);
    throw error;
  } finally {
    input.signal?.removeEventListener("abort", onAbort);
  }
}
