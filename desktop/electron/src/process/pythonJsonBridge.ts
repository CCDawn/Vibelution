import { spawn } from "node:child_process";

import { pythonBridgeEnv } from "./pythonBridgeEnv.js";

export const DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES = 64_000;
export const LAUNCHER_API_JSON_BRIDGE_MAX_BYTES = 2_000_000;
export const PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS = 5_000;
export const PYTHON_JSON_BRIDGE_COMMAND_TIMEOUT_MS = 20_000;
export const PYTHON_JSON_BRIDGE_ISOLATED_STOP_TIMEOUT_MS = 75_000;
export const PYTHON_JSON_BRIDGE_MAINTENANCE_TIMEOUT_MS = 600_000;
export const PYTHON_JSON_BRIDGE_TERMINATION_GRACE_MS = 2_000;
export const PYTHON_JSON_BRIDGE_PROCESS_TREE_TIMEOUT_MS = 10_000;

export type PythonJsonBridgeErrorCode =
  | "timeout"
  | "aborted"
  | "output_limit"
  | "nonzero_exit"
  | "invalid_payload"
  | "uncertain_mutation";

export type PythonJsonBridgeKillPolicy = "child" | "owned-tree" | "none";

export class PythonJsonBridgeError extends Error {
  readonly code: PythonJsonBridgeErrorCode;
  readonly causeCode?: Exclude<PythonJsonBridgeErrorCode, "uncertain_mutation">;

  constructor(
    code: PythonJsonBridgeErrorCode,
    message: string,
    options: { causeCode?: Exclude<PythonJsonBridgeErrorCode, "uncertain_mutation">; cause?: unknown } = {}
  ) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "PythonJsonBridgeError";
    this.code = code;
    this.causeCode = options.causeCode;
  }
}

export type PythonJsonBridgeChild = Pick<
  ReturnType<typeof spawn>,
  "kill" | "once" | "stdout" | "stderr" | "pid"
>;

export type PythonProcessIdentity = {
  pid: number;
  createTime: number;
  executable: string;
};
export type PythonJsonBridgeSpawn = (
  command: string,
  args: string[],
  options: {
    cwd: string;
    windowsHide: boolean;
    stdio: ["ignore", "pipe", "pipe"];
    env: NodeJS.ProcessEnv;
  }
) => PythonJsonBridgeChild;

export type PythonJsonBridgeOwnedTreeTerminator = (child: PythonJsonBridgeChild) => void | Promise<void>;

const CHILD_PROCESS_IDENTITIES = new WeakMap<object, Promise<PythonProcessIdentity | null>>();

export function pythonJsonBridgeChildIdentity(
  child: PythonJsonBridgeChild
): Promise<PythonProcessIdentity | null> {
  return CHILD_PROCESS_IDENTITIES.get(child as object) ?? Promise.resolve(null);
}

/**
 * A process-tree root must be classified by the project-owned Python process
 * inventory before Electron asks the helper to terminate it.  The helper is
 * intentionally narrow: it never accepts a process-table scan or a shell
 * command as a kill authority.
 */
export type PythonOwnedProcessTreeKind =
  | "managed_workbench_backend"
  | "runtime_manager_daemon"
  | "frontend_build_bridge"
  | "frontend_build_process";

export type PythonOwnedProcessTreeResult = {
  status: "terminated" | "already_dead" | "not_owned" | "still_alive" | "unverified";
  pid: number;
  kind?: string;
  reason?: string;
  remainingPids?: number[];
};

const PYTHON_OWNED_PROCESS_TREE_STATUSES: ReadonlySet<string> = new Set([
  "terminated",
  "already_dead",
  "not_owned",
  "still_alive",
  "unverified",
]);

function isPythonOwnedProcessTreeResult(value: unknown): value is PythonOwnedProcessTreeResult {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const candidate = value as { pid?: unknown; status?: unknown };
  return (
    typeof candidate.pid === "number" &&
    Number.isInteger(candidate.pid) &&
    typeof candidate.status === "string" &&
    PYTHON_OWNED_PROCESS_TREE_STATUSES.has(candidate.status)
  );
}

export type PythonOwnedProcessTreeTerminator = (
  pid: number,
  expectedIdentity?: PythonProcessIdentity
) => Promise<boolean>;

const PYTHON_PROCESS_IDENTITY_SCRIPT = String.raw`
import json
import sys

pid = int(sys.argv[1] or 0)
try:
    from core.runtime_manager.process_identity import capture_process_identity
    identity = capture_process_identity(pid)
except Exception:
    identity = {}
print(json.dumps(identity or {}, separators=(",", ":")))
`;

const PYTHON_OWNED_PROCESS_TREE_SCRIPT = String.raw`
import json
import math
import os
import sys

pid = int(sys.argv[1] or 0)
workspace = os.path.abspath(sys.argv[2] or os.getcwd())
allowed = set(json.loads(sys.argv[3] or "[]"))
expected = json.loads(sys.argv[4] or "{}")

def emit(status, kind="", reason="", remaining=None):
    print(json.dumps({
        "status": status,
        "pid": pid,
        "kind": kind,
        "reason": reason,
        "remainingPids": list(remaining or []),
    }, separators=(",", ":")))

if pid <= 0:
    emit("not_owned", reason="invalid_pid")
    raise SystemExit(0)

try:
    import psutil
except Exception:
    emit("not_owned", reason="psutil_unavailable")
    raise SystemExit(0)

def normalized(value):
    return os.path.normcase(os.path.normpath(str(value or "")))

def build_bridge_owned(process):
    try:
        cwd = normalized(process.cwd())
        command = " ".join(str(item or "") for item in process.cmdline()).replace("\\", "/").lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False
    return (
        cwd == normalized(workspace)
        and "scripts/vibelution_desktop_entry.py" in command
        and "ensure-frontend-build" in command
    )

def build_process_owned(process):
    try:
        cwd = normalized(process.cwd()).replace("\\", "/").rstrip("/")
        command = " ".join(str(item or "") for item in process.cmdline()).replace("\\", "/").lower()
        web_root = normalized(os.path.join(workspace, "web")).replace("\\", "/").rstrip("/")
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False
    if cwd != web_root:
        return False
    return (
        "typescript/bin/tsc" in command
        or "vite/bin/vite.js" in command
    )

def identity_matches(process):
    try:
        expected_pid = int(expected.get("pid") or 0)
        expected_create_time = float(expected.get("createTime") or 0)
        expected_executable = os.path.normcase(os.path.normpath(str(expected.get("executable") or "")))
        actual_create_time = float(process.create_time())
        actual_executable = os.path.normcase(os.path.normpath(str(process.exe() or "")))
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError, TypeError, ValueError):
        return False
    return (
        expected_pid == pid
        and expected_create_time > 0
        and bool(expected_executable)
        and abs(actual_create_time - expected_create_time) <= 0.001
        and actual_executable == expected_executable
    )

def descendants_snapshot(root_process):
    try:
        processes = list(root_process.children(recursive=True))
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        emit("unverified", reason="root_disappeared_during_child_enumeration")
        raise SystemExit(0)
    except (psutil.AccessDenied, OSError) as error:
        emit("unverified", reason="child_enumeration_failed:" + type(error).__name__)
        raise SystemExit(0)
    fingerprints = []
    for process in processes:
        try:
            process_pid = int(process.pid)
            create_time = float(process.create_time())
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            emit("unverified", reason="descendant_disappeared_during_snapshot")
            raise SystemExit(0)
        except (psutil.AccessDenied, OSError, TypeError, ValueError) as error:
            emit("unverified", reason="descendant_identity_unavailable:" + type(error).__name__)
            raise SystemExit(0)
        if not math.isfinite(create_time) or create_time <= 0:
            emit("unverified", reason="descendant_identity_invalid")
            raise SystemExit(0)
        fingerprints.append((process_pid, create_time))
    return processes, sorted(fingerprints)

try:
    root = psutil.Process(pid)
    kind = ""
    if "frontend_build_bridge" in allowed and build_bridge_owned(root):
        kind = "frontend_build_bridge"
    elif "frontend_build_process" in allowed and build_process_owned(root):
        kind = "frontend_build_process"
    else:
        try:
            from core.runtime_manager.process_inventory import repo_runtime_process_for_pid
            classified = repo_runtime_process_for_pid(pid, project_root=workspace)
            kind = str(getattr(classified, "kind", "") or "")
        except Exception:
            kind = ""
    if kind not in allowed:
        emit("not_owned", kind=kind, reason="process_identity_unconfirmed")
        raise SystemExit(0)
    if not identity_matches(root):
        emit("not_owned", kind=kind, reason="process_identity_mismatch")
        raise SystemExit(0)

    processes, process_fingerprints = descendants_snapshot(root)
    # A second stable snapshot is the narrowest proof available before the
    # helper starts mutating the tree.  If descendants appear/disappear while
    # enumerating, the helper cannot prove it has a complete tree and must
    # leave the lifecycle handle for a later reconciliation pass.  The
    # create-time component protects against a PID being reused between the
    # two snapshots; psutil's Process handles provide the PID-reuse guard for
    # the subsequent kill, while this fingerprint prevents a reused child
    # from being omitted and still reported as a complete termination.
    verification_processes, verification_fingerprints = descendants_snapshot(root)
    if process_fingerprints != verification_fingerprints:
        emit("unverified", kind=kind, reason="child_enumeration_unstable")
        raise SystemExit(0)
    # Use the second snapshot's fresh Process handles after its fingerprint
    # matches.  This keeps the kill list tied to the most recent enumeration.
    processes = verification_processes
    # The root identity may change after the snapshots but before mutation.
    # Keep the lifecycle handle open for reconciliation if that final guard
    # cannot prove that the original owned root is still the target.
    try:
        fresh_root = psutil.Process(pid)
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        emit("unverified", kind=kind, reason="root_reacquire_failed")
        raise SystemExit(0)
    except (psutil.AccessDenied, OSError) as error:
        emit("unverified", kind=kind, reason="root_reacquire_failed:" + type(error).__name__)
        raise SystemExit(0)
    if not identity_matches(fresh_root):
        emit("unverified", kind=kind, reason="root_identity_changed_before_termination")
        raise SystemExit(0)
    root = fresh_root
    # Descendants first prevents a child from surviving a root termination.
    for process in reversed(processes):
        try:
            if not process.is_running():
                continue
            process.terminate()
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied, OSError):
            pass
    try:
        root.terminate()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    all_processes = processes + [root]
    _, alive = psutil.wait_procs(all_processes, timeout=1.5)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if alive:
        psutil.wait_procs(alive, timeout=1.0)
    remaining = []
    for process in all_processes:
        try:
            if process.is_running():
                remaining.append(int(process.pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    emit("still_alive" if remaining else "terminated", kind=kind, remaining=remaining)
except (psutil.NoSuchProcess, psutil.ZombieProcess):
    # A missing root does not prove that descendants are gone. The caller
    # must retain the handle and reconcile it through a later verified pass.
    emit("unverified", reason="root_not_found")
except (psutil.AccessDenied, OSError) as error:
    emit("unverified", reason=type(error).__name__)
`;

/**
 * Create a fail-closed process-tree terminator for one project root.
 *
 * The Python helper is itself a directly spawned child and is therefore safe
 * to terminate with the bridge's ordinary child policy if it exceeds its
 * bound.  Only the helper may terminate the target tree, after it has
 * classified the target against the supplied project-owned process kinds.
 */
export function createPythonOwnedProcessTreeTerminator(input: {
  pythonPath: string;
  workspaceRoot: string;
  allowedKinds: readonly PythonOwnedProcessTreeKind[];
  spawnImpl?: PythonJsonBridgeSpawn;
  expectedIdentities?: Readonly<Record<string, PythonProcessIdentity>>;
  timeoutMs?: number;
  terminationGraceMs?: number;
}): PythonOwnedProcessTreeTerminator {
  const allowedKinds = [...new Set(input.allowedKinds)];
  if (!input.pythonPath.trim()) {
    throw new TypeError("python owned-tree terminator requires a pythonPath");
  }
  if (!input.workspaceRoot.trim()) {
    throw new TypeError("python owned-tree terminator requires a workspaceRoot");
  }
  if (allowedKinds.length === 0) {
    throw new TypeError("python owned-tree terminator requires at least one allowed process kind");
  }

  return async (pid: number, expectedIdentity?: PythonProcessIdentity): Promise<boolean> => {
    const normalizedPid = Math.trunc(Number(pid));
    if (!Number.isFinite(normalizedPid) || normalizedPid <= 0) {
      return false;
    }
    const identity = expectedIdentity ?? input.expectedIdentities?.[String(normalizedPid)];
    if (!identity || identity.pid !== normalizedPid || identity.createTime <= 0 || !identity.executable) {
      return false;
    }

    let raw: string;
    try {
      raw = await runPythonJsonBridge({
        pythonPath: input.pythonPath,
        args: [
          "-c",
          PYTHON_OWNED_PROCESS_TREE_SCRIPT,
          String(normalizedPid),
          input.workspaceRoot,
          JSON.stringify(allowedKinds),
          JSON.stringify(identity)
        ],
        cwd: input.workspaceRoot,
        spawnImpl: input.spawnImpl,
        failureLabel: `owned process-tree terminator for pid ${normalizedPid}`,
        maxBytes: 16_000,
        timeoutMs: input.timeoutMs ?? PYTHON_JSON_BRIDGE_PROCESS_TREE_TIMEOUT_MS,
        killPolicy: "child",
        mutation: true,
        terminationGraceMs: input.terminationGraceMs
      });
    } catch {
      // A bridge failure cannot establish that the target was owned or
      // terminated.  Returning false keeps callers fail-closed and lets them
      // perform their normal liveness/error reconciliation.
      return false;
    }

    let result: PythonOwnedProcessTreeResult;
    try {
      const parsed = parsePythonJsonBridgePayload<unknown>(
        raw,
        `owned process-tree terminator for pid ${normalizedPid}`
      );
      if (!isPythonOwnedProcessTreeResult(parsed)) {
        return false;
      }
      result = parsed;
    } catch {
      return false;
    }
    if (result.pid !== normalizedPid) {
      return false;
    }
    // "already_dead" and "unverified" are not proof that descendants are
    // gone. Only the helper's explicit post-termination verification can
    // close the handle.
    return result.status === "terminated";
  };
}

export async function capturePythonProcessIdentity(input: {
  pythonPath: string;
  workspaceRoot: string;
  pid: number;
  timeoutMs?: number;
  spawnImpl?: PythonJsonBridgeSpawn;
}): Promise<PythonProcessIdentity | null> {
  const pid = Math.trunc(Number(input.pid));
  if (!input.pythonPath.trim() || !input.workspaceRoot.trim() || !Number.isFinite(pid) || pid <= 0) {
    return null;
  }
  let raw: string;
  try {
    raw = await runPythonJsonBridge({
      pythonPath: input.pythonPath,
      args: ["-c", PYTHON_PROCESS_IDENTITY_SCRIPT, String(pid)],
      cwd: input.workspaceRoot,
      spawnImpl: input.spawnImpl,
      failureLabel: `process identity capture for pid ${pid}`,
      timeoutMs: input.timeoutMs ?? PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS,
      killPolicy: "child"
    });
  } catch {
    return null;
  }
  try {
    const parsed = parsePythonJsonBridgePayload<Partial<PythonProcessIdentity>>(raw, `process identity capture for pid ${pid}`);
    const createTime = Number(parsed.createTime);
    const executable = String(parsed.executable || "").trim();
    return Number(parsed.pid) === pid && Number.isFinite(createTime) && createTime > 0 && executable
      ? { pid, createTime, executable }
      : null;
  } catch {
    return null;
  }
}

export function invalidPythonJsonBridgePayload(
  failureLabel: string,
  detail = "returned an invalid JSON payload",
  cause?: unknown
): PythonJsonBridgeError {
  return new PythonJsonBridgeError("invalid_payload", `${failureLabel} ${detail}`, { cause });
}

export function parsePythonJsonBridgePayload<T>(raw: string, failureLabel: string): T {
  try {
    return JSON.parse(raw) as T;
  } catch (error: unknown) {
    throw invalidPythonJsonBridgePayload(failureLabel, "returned malformed JSON", error);
  }
}

function bridgeFailure(
  input: { failureLabel: string; mutation?: boolean },
  code: Exclude<PythonJsonBridgeErrorCode, "invalid_payload" | "uncertain_mutation">,
  message: string
): PythonJsonBridgeError {
  if (input.mutation && code === "timeout") {
    return new PythonJsonBridgeError(
      "uncertain_mutation",
      `${message}; the mutation outcome is uncertain and must be reconciled`,
      { causeCode: "timeout" }
    );
  }
  return new PythonJsonBridgeError(code, message);
}

export async function runPythonJsonBridge(input: {
  pythonPath: string;
  args: string[];
  cwd: string;
  spawnImpl?: PythonJsonBridgeSpawn;
  failureLabel: string;
  maxBytes?: number;
  timeoutMs: number;
  signal?: AbortSignal;
  killPolicy: PythonJsonBridgeKillPolicy;
  mutation?: boolean;
  terminateOwnedTree?: PythonJsonBridgeOwnedTreeTerminator;
  captureChildIdentity?: (pid: number) => Promise<PythonProcessIdentity | null>;
  terminationGraceMs?: number;
}): Promise<string> {
  if (!Number.isFinite(input.timeoutMs) || input.timeoutMs <= 0) {
    throw new RangeError("python JSON bridge timeoutMs must be a positive finite number");
  }
  if (input.killPolicy === "owned-tree" && !input.terminateOwnedTree) {
    throw new TypeError("python JSON bridge owned-tree policy requires an explicit owned-tree terminator");
  }
  if (input.signal?.aborted) {
    throw bridgeFailure(input, "aborted", `${input.failureLabel} was aborted before spawn`);
  }

  const spawnImpl = input.spawnImpl ?? spawn;
  const maxBytes = Math.max(1_000, Math.round(input.maxBytes ?? DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES));
  const terminationGraceMs = Math.max(
    1,
    Math.round(input.terminationGraceMs ?? PYTHON_JSON_BRIDGE_TERMINATION_GRACE_MS)
  );
  const child = spawnImpl(input.pythonPath, input.args, {
    cwd: input.cwd,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: pythonBridgeEnv()
  });
  if (input.killPolicy === "owned-tree" && input.captureChildIdentity && Number(child.pid) > 0) {
    const identityPromise = Promise.resolve(input.captureChildIdentity(Math.trunc(Number(child.pid)))).catch(() => null);
    CHILD_PROCESS_IDENTITIES.set(child as object, identityPromise);
  }

  return await new Promise((resolveOutput, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    let settled = false;
    let terminating = false;
    let pendingFailure: PythonJsonBridgeError | null = null;
    let terminationTimer: ReturnType<typeof setTimeout> | null = null;

    const cleanup = (): void => {
      clearTimeout(timeoutTimer);
      if (terminationTimer !== null) {
        clearTimeout(terminationTimer);
        terminationTimer = null;
      }
      input.signal?.removeEventListener("abort", onAbort);
    };

    const rejectOnce = (error: Error): void => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      reject(error);
    };

    const resolveOnce = (): void => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolveOutput(Buffer.concat(chunks).toString("utf8"));
    };

    const finishPendingFailure = (): void => {
      rejectOnce(pendingFailure ?? new PythonJsonBridgeError("aborted", `${input.failureLabel} was aborted`));
    };

    const beginTermination = (failure: PythonJsonBridgeError): void => {
      if (settled || terminating) {
        return;
      }
      terminating = true;
      pendingFailure = failure;
      terminationTimer = setTimeout(finishPendingFailure, terminationGraceMs);
      if (input.killPolicy === "none") {
        return;
      }
      try {
        if (input.killPolicy === "owned-tree") {
          void Promise.resolve(input.terminateOwnedTree?.(child)).catch(() => {
            // The original bounded bridge failure remains authoritative. The
            // grace timer prevents a failed terminator from hanging the caller.
          });
        } else {
          child.kill();
        }
      } catch {
        finishPendingFailure();
      }
    };

    const onAbort = (): void => {
      beginTermination(bridgeFailure(input, "aborted", `${input.failureLabel} was aborted`));
    };

    const timeoutTimer = setTimeout(() => {
      beginTermination(
        bridgeFailure(input, "timeout", `${input.failureLabel} timed out after ${Math.round(input.timeoutMs)}ms`)
      );
    }, Math.round(input.timeoutMs));

    input.signal?.addEventListener("abort", onAbort, { once: true });
    child.stdout?.on("data", (chunk: Buffer) => {
      if (settled || terminating) {
        return;
      }
      total += chunk.length;
      if (total > maxBytes) {
        beginTermination(
          bridgeFailure(input, "output_limit", `${input.failureLabel} output exceeded limit`)
        );
        return;
      }
      chunks.push(chunk);
    });
    child.stderr?.on("data", () => {
      // Drain stderr so stdio pipes cannot deadlock; detailed logs stay in Python log files.
    });
    child.once("error", (error: Error) => {
      if (terminating) {
        finishPendingFailure();
        return;
      }
      rejectOnce(
        new PythonJsonBridgeError(
          "nonzero_exit",
          `${input.failureLabel} failed to start or communicate with the child process`,
          { cause: error }
        )
      );
    });
    child.once("close", (code) => {
      if (settled) {
        return;
      }
      if (terminating) {
        finishPendingFailure();
        return;
      }
      if (code !== 0) {
        rejectOnce(
          bridgeFailure(input, "nonzero_exit", `${input.failureLabel} exited with code ${code ?? "unknown"}`)
        );
        return;
      }
      resolveOnce();
    });
  });
}
