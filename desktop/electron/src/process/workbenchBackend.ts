import { execFileSync, spawn as nodeSpawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync
} from "node:fs";
import { basename, dirname, join, resolve as resolvePath } from "node:path";
import type { Readable } from "node:stream";
import { setTimeout as delay } from "node:timers/promises";

import { BoundedStdioSink, type BoundedStdioStatus } from "./boundedStdio.js";
import { appendSupervisorEventFallback } from "../lifecycle/supervisorEventFallback.js";
import { pythonBridgeEnv } from "./pythonBridgeEnv.js";
import { runOwnedFrontendBuildBridge } from "./ownedFrontendBuildBridge.js";
import {
  PYTHON_JSON_BRIDGE_MAINTENANCE_TIMEOUT_MS,
  createPythonOwnedProcessTreeTerminator,
  capturePythonProcessIdentity,
  parsePythonJsonBridgePayload,
  pythonJsonBridgeChildIdentity,
  runPythonJsonBridge,
  type PythonJsonBridgeOwnedTreeTerminator,
  type PythonProcessIdentity,
  type PythonOwnedProcessTreeTerminator
} from "./pythonJsonBridge.js";
import {
  resolveActiveCanonicalRuntimeHome,
  resolveCanonicalRuntimeHome,
  resolveCheckoutRuntimeHome,
  resolveLauncherRuntimeDir,
  resolveRuntimeManagerDir
} from "../lifecycle/projectStoragePaths.js";
import {
  resolveWorkbenchPortOwner,
  type WorkbenchPortOwnerResolution
} from "./resolveWorkbenchPortOwner.js";
import { knownPidIsAlive, observeMainLineWorkbench, probeTcpConnect } from "../lifecycle/mainLine/observation.js";
import { captureTrackedWorkbenchJobRetirement, closeTrackedWorkbenchJob, getTrackedWorkbenchJobPid, hasTrackedWorkbenchJob, spawnTrackedWorkbenchProcess, terminateTrackedWorkbenchJob, type WorkbenchNaturalJobRetirement } from "./workbenchJob.js";
import { closeOwnedWorkbenchFast, type WorkbenchCloseTiming } from "./fastWorkbenchClose.js";
import { getBackgroundWorkbenchRetirement, startBackgroundWorkbenchRetirement } from "./backgroundWorkbenchRetirement.js";
import {
  BACKEND_HEALTH_HTTP_TIMEOUT_MS,
  defaultFetchWorkbenchHealth,
  waitForBackendHealthy,
  workbenchHealthUrl,
  type WorkbenchHealthResponse
} from "./workbenchBackendHealth.js";
import {
  collectRegisteredHandles,
  reconcileDeadRegisteredHandles,
  requestGracefulWorkbenchShutdown,
  retireRegisteredHandles,
  terminatePid,
  waitForPortRelease,
  type GracefulWorkbenchShutdownResult
} from "./workbenchBackendRetire.js";
import {
  blockLifecycleIfActiveWork,
  listActiveWorkRuns,
  type ActiveWorkRun
} from "./activeWorkGuard.js";
import type { WorkbenchLifecycleOperation, WorkbenchLifecycleResult } from "./workbenchLifecycle.js";
import { trackMainLineBackgroundWork, type MainLineQueuedCommand } from "../lifecycle/mainLine/commandQueue.js";

export const DEFAULT_WORKBENCH_HOST = "127.0.0.1";
export const DEFAULT_WORKBENCH_PORT = 8000;
export const WEB_WORKBENCH_SCRIPT = ["scripts", "web_workbench.py"] as const;
// Pre-governance checkout-relative fingerprint location. Reads fall back to it
// during the storage migration; the governed write side lives in Python
// (code_freshness.running_code_fingerprint_path), Electron only ever reads.
export const RUNNING_CODE_FINGERPRINT_RELATIVE = [".runtime", "running-code-fingerprint.json"] as const;
const RUNNING_CODE_FINGERPRINT_NAME = "running-code-fingerprint.json";

export type WorkbenchBackendSpawnChild = {
  pid?: number;
  killed?: boolean;
  exitCode?: number | null;
  stdout?: Readable | null;
  stderr?: Readable | null;
  unref?: () => void;
  kill: (signal?: NodeJS.Signals) => boolean;
  once?: (event: "error", listener: (error: Error) => void) => unknown;
};

export type WorkbenchBackendSpawn = (
  command: string,
  args: string[],
  options: {
    cwd: string;
    env: NodeJS.ProcessEnv;
    windowsHide: boolean;
    detached: boolean;
    stdio: ["ignore", "pipe", "pipe"] | ["ignore", "ignore", "ignore"];
  }
) => WorkbenchBackendSpawnChild;

export type WorkbenchBackendState = Record<string, unknown>;

/** Trusted main-only, same captured owner for all retries. The caller must
 * retain source/admission fences and verify the port, token and Job binding. */
export function beginNaturalWorkbenchShutdown(input: {
  job: WorkbenchNaturalJobRetirement; port: number; controlToken: string;
  verifyBinding(): void;
  /** Test seam; production uses the native graceful request. */
  shutdown?: typeof requestGracefulWorkbenchShutdown;
}): { observe(): Promise<"pending" | "drained"> } {
  if (!input || !input.job || typeof input.job !== "function" || typeof input.job.isCurrent !== "function"
    || !Number.isSafeInteger(input.job.pid) || input.job.pid <= 0 || !Number.isInteger(input.port)
    || input.port <= 0 || input.port > 65535 || typeof input.controlToken !== "string"
    || input.controlToken.trim().length < 16 || typeof input.verifyBinding !== "function")
    throw new Error("WORKBENCH_NATURAL_RETIREMENT_INVALID");
  let attempted = false;
  let running: Promise<"pending" | "drained"> | undefined;
  const check = () => {
    if ((input.verifyBinding as () => unknown)() !== undefined) throw new Error("WORKBENCH_NATURAL_RETIREMENT_UNKNOWN");
  };
  const observe = (): Promise<"pending" | "drained"> => {
    if (running) return running;
    const operation = (async (): Promise<"pending" | "drained"> => {
      try {
        check();
        if (await input.job()) { check(); return "drained"; }
        if (attempted || !input.job.isCurrent()) return "pending";
        // A timeout/lost acknowledgement may follow acceptance. It must not
        // trigger another shutdown; only explicit 409 proves no request won.
        attempted = true;
        const result = await (input.shutdown ?? requestGracefulWorkbenchShutdown)({ port: input.port,
          backendPid: input.job.pid, host: DEFAULT_WORKBENCH_HOST, controlToken: input.controlToken,
          healthVerified: true, interruptActiveWork: false });
        check();
        if (result.status === 409 && !result.requested) attempted = false;
        if (!result.completed) return "pending";
        if (await input.job()) { check(); return "drained"; }
      } catch { /* Unknown keeps the captured Job and never forces a stop. */ }
      return "pending";
    })();
    running = operation;
    void operation.finally(() => { if (running === operation) running = undefined; });
    return operation;
  };
  return { observe };
}

export type ExecuteMainLineWorkbenchInput = {
  workspaceRoot: string;
  pythonPath: string;
  targetEnvironment?: NodeJS.ProcessEnv;
  operation: WorkbenchLifecycleOperation;
  command: MainLineQueuedCommand;
  signal?: AbortSignal;
  spawnImpl?: WorkbenchBackendSpawn;
  /** Trusted in-process admission check immediately before backend spawn. */
  beforeSpawn?: () => void;
  fileExists?: (path: string) => boolean;
  readState?: () => WorkbenchBackendState;
  writeState?: (state: WorkbenchBackendState) => void | Promise<void>;
  listActiveWork?: () => ActiveWorkRun[];
  ensureFrontend?: (input: { force: boolean; signal?: AbortSignal; env?: NodeJS.ProcessEnv }) => Promise<void>;
  now?: () => string;
  connect?: (port: number, host: string) => Promise<boolean>;
  fetchHealth?: (url: string) => Promise<WorkbenchHealthResponse>;
  pidAlive?: (pid: number) => boolean;
  killPid?: (pid: number) => void | Promise<void>;
  terminateProcessTree?: (pid: number, expectedIdentity?: PythonProcessIdentity) => boolean | Promise<boolean>;
  expectedIdentities?: Readonly<Record<string, PythonProcessIdentity>>;
  controlToken?: string;
  /** Internal explicit window-close budget; never accepted from renderer JSON. */
  fastCloseTiming?: WorkbenchCloseTiming;
  captureRetirement?: typeof captureTrackedWorkbenchJobRetirement;
  /** Explicit operator restart consent to pause active work through graceful shutdown. */
  interruptActiveWork?: boolean;
  gracefulShutdown?: typeof requestGracefulWorkbenchShutdown;
  ownedDirectPids?: readonly number[];
  readDaemonPid?: (workspaceRoot: string) => number;
  readDaemonIdentity?: (workspaceRoot: string) => PythonProcessIdentity | null;
  captureProcessIdentity?: (input: {
    pythonPath: string;
    workspaceRoot: string;
    env?: NodeJS.ProcessEnv;
    pid: number;
    signal?: AbortSignal;
  }) => Promise<PythonProcessIdentity | null>;
  /** Inventory-based port owner resolution for a wedged backend that owns the port. */
  resolvePortOwner?: (input: {
    pythonPath: string;
    workspaceRoot: string;
    env?: NodeJS.ProcessEnv;
    port: number;
    signal?: AbortSignal;
  }) => Promise<WorkbenchPortOwnerResolution | null>;
};

function isoNow(now?: () => string): string {
  return now?.() ?? new Date().toISOString();
}

function accepted(
  operation: string,
  commandId: string,
  extra: Partial<WorkbenchLifecycleResult> = {}
): WorkbenchLifecycleResult {
  return {
    schemaVersion: 1,
    accepted: true,
    operation,
    commandId,
    ...extra
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function resolveNoConsolePython(
  pythonPath: string,
  fileExists: (path: string) => boolean = existsSync,
  options: { consoleSuppressedByCaller?: boolean } = {}
): string {
  const raw = String(pythonPath || "").trim();
  if (!raw) {
    return "";
  }
  const lower = raw.toLowerCase();
  // A caller that already suppresses the console window itself (the tracked
  // native spawn wraps the child in a Job with CREATE_NO_WINDOW and
  // file-redirected stdio) must keep the plain console executable: the venv
  // ``pythonw.exe`` is a launcher stub that CreateProcess-delegates the real
  // base-Python interpreter as a child, so the registered pid is a ~5MB stub
  // that never binds the port while the server runs as an unregistered
  // grandchild (documented in core/launcher/desktop_shell.py).
  if (options.consoleSuppressedByCaller) {
    if (lower.endsWith("pythonw.exe")) {
      const sibling = raw.slice(0, -"pythonw.exe".length) + "python.exe";
      if (fileExists(sibling)) {
        return sibling;
      }
    }
    return raw;
  }
  if (lower.endsWith("pythonw.exe")) {
    return raw;
  }
  if (lower.endsWith("python.exe")) {
    const sibling = raw.slice(0, -"python.exe".length) + "pythonw.exe";
    if (fileExists(sibling)) {
      return sibling;
    }
  }
  return raw;
}

export function workbenchBackendArgs(input: { host: string; port: number }): string[] {
  return [
    "--host",
    input.host,
    "--port",
    String(Math.trunc(input.port)),
    "--no-browser",
    "--managed-by-launcher"
  ];
}

export function workbenchBackendEnv(input: {
  workspaceRoot: string;
  port: number;
  baseEnv?: NodeJS.ProcessEnv;
  host?: string;
  dataHome?: string;
  configHome?: string;
  controlPort?: number;
  allowDirty?: boolean;
  allowNonMain?: boolean;
  extra?: NodeJS.ProcessEnv;
}): NodeJS.ProcessEnv {
  const env = pythonBridgeEnv({
    ...(input.baseEnv ?? process.env),
    ...(input.extra ?? {})
  });
  env.VIBELUTION_WORKSPACE_ROOT = input.workspaceRoot;
  env.VIBELUTION_PORT = String(Math.trunc(input.port));
  env.AGENT_WORKBENCH_BACKEND_PORT = String(Math.trunc(input.port));
  if (input.dataHome) {
    env.VIBELUTION_DATA_HOME = input.dataHome;
  }
  if (input.configHome) {
    env.VIBELUTION_CONFIG_HOME = input.configHome;
  }
  if (Number.isFinite(input.controlPort) && Number(input.controlPort) > 0) {
    const controlPort = Math.trunc(Number(input.controlPort));
    env.VIBELUTION_LAUNCHER_PORT = String(controlPort);
    env.AGENT_LAUNCHER_CONTROL_PORT = String(controlPort);
  }
  if (input.allowDirty) {
    env.VIBELUTION_ALLOW_DIRTY_LAUNCH = "1";
  }
  if (input.allowNonMain) {
    env.VIBELUTION_ALLOW_NON_MAIN_LAUNCH = "1";
  }
  return env;
}

export function launcherStatePath(workspaceRoot: string): string {
  return join(resolveLauncherRuntimeDir(workspaceRoot), "state.json");
}

export function launcherPortsPath(workspaceRoot: string): string {
  return join(resolveLauncherRuntimeDir(workspaceRoot), "ports.json");
}

export function runtimeManagerDaemonPidPath(workspaceRoot: string): string {
  return join(resolveRuntimeManagerDir(workspaceRoot), "daemon.pid");
}

export function runtimeManagerDaemonLockPath(workspaceRoot: string): string {
  return join(resolveRuntimeManagerDir(workspaceRoot), "daemon.lock");
}

export function runtimeManagerDaemonIdentityPath(workspaceRoot: string): string {
  return join(resolveRuntimeManagerDir(workspaceRoot), "daemon.identity.json");
}

export function launcherLifecycleBlockedResultPath(workspaceRoot: string): string {
  return join(resolveRuntimeManagerDir(workspaceRoot), "launcher-lifecycle-blocked.json");
}


export function deferredRestartIntentPath(workspaceRoot: string, intentId: string): string {
  return join(resolveRuntimeManagerDir(workspaceRoot), "restart-intents", `${intentId}.json`);
}


export function queueDeferredRestartIntent(
  workspaceRoot: string,
  payload: {
    reason: string;
    sourceCommandId: string;
    requestedBy?: string;
  }
): { intentId: string; path: string } | null {
  // Active work blocks restart with no output, so the operator can only retry
  // by hand. Persist a runtime-manager restart intent instead: the daemon
  // fulfils it from its idle branch, which is the same boundary the guard
  // wants, and the operator gets a durable answer for "when will it restart".
  try {
    const intentId = `intent_ts_${Date.now().toString(36)}_${randomUUID().slice(0, 8)}`;
    const target = deferredRestartIntentPath(workspaceRoot, intentId);
    mkdirSync(dirname(target), { recursive: true });
    const now = new Date().toISOString();
    const intent = {
      intentId,
      target: "workbench_restart",
      reason: String(payload.reason || "").trim(),
      requestedBy: String(payload.requestedBy || "electron_main").trim() || "electron_main",
      sourceCommandId: String(payload.sourceCommandId || "").trim(),
      status: "pending",
      createdAt: now,
      updatedAt: now,
      attempts: 0,
      failureCount: 0,
      lastError: "",
      nextAllowedAt: "",
      payload: { action: "restart_workbench" }
    };
    writeFileSync(target, JSON.stringify(intent, null, 2), "utf8");
    return { intentId, path: target };
  } catch {
    return null;
  }
}

export function recordBlockedLifecycleDiagnostic(
  workspaceRoot: string,
  payload: {
    operation: string;
    commandId: string;
    code: string;
    message: string;
    activeWorkRuns: readonly ActiveWorkRun[];
  }
): void {
  // A blocked lifecycle command otherwise surfaces as a bare nonzero exit code
  // with no output, so "why was my restart refused" has no answer. Persist the
  // same structured reason the tray shows, without changing the decision.
  try {
    const target = launcherLifecycleBlockedResultPath(workspaceRoot);
    mkdirSync(dirname(target), { recursive: true });
    writeFileSync(
      target,
      JSON.stringify(
        {
          schemaVersion: 1,
          operation: payload.operation,
          commandId: payload.commandId,
          code: payload.code,
          message: payload.message,
          activeWorkCount: payload.activeWorkRuns.length,
          activeWorkRuns: payload.activeWorkRuns.slice(0, 8),
          retryMode: "after_active_work",
          recordedAt: new Date().toISOString()
        },
        null,
        2
      ),
      "utf-8"
    );
  } catch {
    // Diagnostics must never change the lifecycle decision itself.
  }
}

export function readDaemonPid(workspaceRoot: string): number {
  try {
    const raw = readFileSync(runtimeManagerDaemonPidPath(workspaceRoot), "utf8").trim();
    const pid = Number(raw.split(/\s+/)[0] || 0);
    return Number.isFinite(pid) && pid > 0 ? Math.trunc(pid) : 0;
  } catch {
    return 0;
  }
}

export function readDaemonIdentity(workspaceRoot: string): PythonProcessIdentity | null {
  try {
    const parsed = JSON.parse(readFileSync(runtimeManagerDaemonIdentityPath(workspaceRoot), "utf8")) as Record<string, unknown>;
    const pid = Math.trunc(Number(parsed.pid || 0));
    const createTime = Number(parsed.createTime || 0);
    const executable = String(parsed.executable || "").trim();
    return pid > 0 && Number.isFinite(createTime) && createTime > 0 && executable
      ? { pid, createTime, executable }
      : null;
  } catch {
    return null;
  }
}

const PYTHON_DAEMON_EXECUTABLE_NAME = /^pythonw?(\d+(\.\d+)*)?$/;

/**
 * Whether an executable path could plausibly belong to a Runtime Manager
 * daemon (the python/pythonw family the product spawns). Windows pid reuse
 * turns a stale daemon.pid into an unrelated conhost/node pid; this check
 * separates that reuse from a real daemon whose identity file was lost.
 */
export function executableLooksLikePythonDaemon(executable: string): boolean {
  const name = basename(String(executable || "").trim()).toLowerCase();
  if (!name) {
    return false;
  }
  return PYTHON_DAEMON_EXECUTABLE_NAME.test(name.endsWith(".exe") ? name.slice(0, -".exe".length) : name);
}

const MANAGED_BROWSER_EXECUTABLE_NAME = /^(msedge|msedgewebview2)$/;

/**
 * Whether an executable path could plausibly belong to the managed workbench
 * browser (the Edge family the launcher spawns for the built-in window).
 * Windows pid reuse turns a stale browser/window handle into an unrelated
 * process; this check separates that reuse from a genuinely open browser.
 */
export function executableLooksLikeManagedBrowser(executable: string): boolean {
  const name = basename(String(executable || "").trim()).toLowerCase();
  if (!name) {
    return false;
  }
  return MANAGED_BROWSER_EXECUTABLE_NAME.test(name.endsWith(".exe") ? name.slice(0, -".exe".length) : name);
}

export type RuntimeManagerDaemonRecordCleanupResult = {
  removedPaths: string[];
  failedPaths: string[];
};

/**
 * Delete only the stale daemon record files (daemon.pid, daemon.lock,
 * daemon.identity.json). Callers must first have proven the recorded pid is
 * dead or reused by a foreign process: while a daemon runs, the Python side
 * owns these descriptors and an O_EXCL claim depends on them staying intact.
 * No process is ever signalled here.
 */
export function clearStaleRuntimeManagerDaemonRecords(
  workspaceRoot: string
): RuntimeManagerDaemonRecordCleanupResult {
  const paths = [
    runtimeManagerDaemonPidPath(workspaceRoot),
    runtimeManagerDaemonLockPath(workspaceRoot),
    runtimeManagerDaemonIdentityPath(workspaceRoot)
  ];
  const removedPaths: string[] = [];
  const failedPaths: string[] = [];
  for (const path of paths) {
    try {
      unlinkSync(path);
      removedPaths.push(path);
    } catch (error: unknown) {
      if ((error as NodeJS.ErrnoException)?.code !== "ENOENT") {
        failedPaths.push(path);
      }
    }
  }
  return { removedPaths, failedPaths };
}

type RuntimeManagerDaemonRecordReconciliation = {
  /**
   * True when the record no longer describes a plausible daemon and its files
   * may be (or have been) removed: the recorded pid is dead, or the pid now
   * belongs to a confirmed non-python process.
   */
  stale: boolean;
  cleared: boolean;
  failedPaths: string[];
  note: string;
};

/**
 * Classify a daemon.pid record against the live process table and drop the
 * record files when they are provably stale. A live python-family pid (or one
 * whose identity cannot be captured) is left untouched so the conservative
 * fail-closed paths keep their meaning; only record files are ever removed.
 */
async function reconcileStaleRuntimeManagerDaemonRecords(input: {
  workspaceRoot: string;
  daemonPid: number;
  pidAlive: (pid: number) => boolean;
  captureIdentity: (pid: number) => Promise<PythonProcessIdentity | null>;
}): Promise<RuntimeManagerDaemonRecordReconciliation> {
  const daemonPid = input.daemonPid;
  if (daemonPid <= 0) {
    return { stale: false, cleared: false, failedPaths: [], note: "" };
  }
  let foreignExecutable = "";
  if (input.pidAlive(daemonPid)) {
    const identity = await input.captureIdentity(daemonPid);
    if (!identity || executableLooksLikePythonDaemon(identity.executable)) {
      return { stale: false, cleared: false, failedPaths: [], note: "" };
    }
    foreignExecutable = basename(identity.executable.trim());
  }
  const cleanup = clearStaleRuntimeManagerDaemonRecords(input.workspaceRoot);
  return {
    stale: true,
    cleared: cleanup.failedPaths.length === 0,
    failedPaths: cleanup.failedPaths,
    note: cleanup.failedPaths.length > 0
      ? `Runtime Manager daemon records for pid ${daemonPid} could not be cleared: ${cleanup.failedPaths.join(", ")}`
      : foreignExecutable
        ? `Ignored stale Runtime Manager daemon pid ${daemonPid}; the pid was reused by ${foreignExecutable} and its record files were cleared without terminating any process.`
        : `Cleared stale Runtime Manager daemon pid ${daemonPid} records; the recorded process had exited.`
  };
}

function stateProcessIdentities(state: WorkbenchBackendState): Readonly<Record<string, PythonProcessIdentity>> {
  const identities: Record<string, PythonProcessIdentity> = {};
  const add = (pidKey: string, createKey: string, executableKey: string): void => {
    const pid = Math.trunc(Number(state[pidKey] || 0));
    const createTime = Number(state[createKey] || 0);
    const executable = String(state[executableKey] || "").trim();
    if (pid > 0 && Number.isFinite(createTime) && createTime > 0 && executable) {
      identities[String(pid)] = { pid, createTime, executable };
    }
  };
  add("backendPid", "backendCreateTime", "backendExecutable");
  add("backendLaunchPid", "backendLaunchCreateTime", "backendLaunchExecutable");
  add("spawnPid", "spawnCreateTime", "spawnExecutable");
  return identities;
}

function stateWithoutReconciledBackendHandles(
  state: WorkbenchBackendState,
  reconciledPids: ReadonlySet<number>
): WorkbenchBackendState {
  const sanitized = { ...state };
  const clearIfReconciled = (
    pidKey: string,
    createTimeKey: string,
    executableKey: string
  ): void => {
    const pid = Math.trunc(Number(state[pidKey] || 0));
    if (!reconciledPids.has(pid)) {
      return;
    }
    sanitized[pidKey] = 0;
    sanitized[createTimeKey] = 0;
    sanitized[executableKey] = "";
  };
  clearIfReconciled("backendPid", "backendCreateTime", "backendExecutable");
  clearIfReconciled("backendLaunchPid", "backendLaunchCreateTime", "backendLaunchExecutable");
  clearIfReconciled("spawnPid", "spawnCreateTime", "spawnExecutable");
  return sanitized;
}

const BROWSER_WINDOW_HANDLE_KEYS = [
  "browserLaunchPid",
  "browserWindowPid",
  "workbenchBrowserLaunchPid",
  "workbenchBrowserWindowPid"
] as const;

function liveUnverifiedBrowserWindowHandles(
  state: WorkbenchBackendState,
  pidAlive: (pid: number) => boolean,
  trustedPids: readonly number[] = []
): number[] {
  const trusted = new Set(trustedPids.map((pid) => Math.trunc(Number(pid))));
  const handles = new Set<number>();
  for (const key of BROWSER_WINDOW_HANDLE_KEYS) {
    const pid = Math.trunc(Number(state[key] || 0));
    if (Number.isFinite(pid) && pid > 0 && !trusted.has(pid) && pidAlive(pid)) {
      handles.add(pid);
    }
  }
  return [...handles].sort((left, right) => right - left);
}

function stateWithoutBrowserWindowHandles(
  state: WorkbenchBackendState,
  clearedPids: ReadonlySet<number>
): WorkbenchBackendState {
  if (clearedPids.size === 0) {
    return state;
  }
  const sanitized = { ...state };
  for (const key of BROWSER_WINDOW_HANDLE_KEYS) {
    const pid = Math.trunc(Number(state[key] || 0));
    if (Number.isFinite(pid) && pid > 0 && clearedPids.has(pid)) {
      sanitized[key] = 0;
    }
  }
  return sanitized;
}

type BrowserWindowHandleFalsification = {
  /** Handles whose pid exited or was provably reused: cleared from state. */
  clearedPids: number[];
  /** Live handles that stay unverified and keep the conservative refusal. */
  livePids: number[];
  note: string;
};

/**
 * Falsify stale browser/window handle records before the start path refuses on
 * them. Closing the built-in browser window leaves the handle in state; when
 * the recorded pid has exited, or Windows reused it for a process outside the
 * managed browser family (Edge), the record is provably stale and is dropped
 * without terminating anything, so cleanup/restart cannot wedge on it forever.
 * A live browser-family pid — or one whose identity cannot be captured — keeps
 * the conservative refusal, mirroring the daemon-record falsification.
 */
async function falsifyStaleBrowserWindowHandles(input: {
  state: WorkbenchBackendState;
  pidAlive: (pid: number) => boolean;
  trustedPids?: readonly number[];
  captureIdentity: (pid: number) => Promise<PythonProcessIdentity | null>;
  signal?: AbortSignal;
}): Promise<BrowserWindowHandleFalsification> {
  const trusted = new Set((input.trustedPids ?? []).map((pid) => Math.trunc(Number(pid))));
  const handles = new Set<number>();
  for (const key of BROWSER_WINDOW_HANDLE_KEYS) {
    const pid = Math.trunc(Number(input.state[key] || 0));
    if (Number.isFinite(pid) && pid > 0 && !trusted.has(pid)) {
      handles.add(pid);
    }
  }
  if (handles.size === 0) {
    return { clearedPids: [], livePids: [], note: "" };
  }
  const clearedPids: number[] = [];
  const exitedPids: number[] = [];
  const reusedExecutables = new Map<number, string>();
  const livePids: number[] = [];
  for (const pid of [...handles].sort((left, right) => right - left)) {
    input.signal?.throwIfAborted();
    if (!input.pidAlive(pid)) {
      exitedPids.push(pid);
      clearedPids.push(pid);
      continue;
    }
    let identity: PythonProcessIdentity | null = null;
    try {
      identity = await input.captureIdentity(pid);
    } catch {
      identity = null;
    }
    input.signal?.throwIfAborted();
    const executable = String(identity?.executable || "").trim();
    if (
      identity
      && Math.trunc(Number(identity.pid)) === pid
      && executable
      && !executableLooksLikeManagedBrowser(executable)
    ) {
      reusedExecutables.set(pid, basename(executable));
      clearedPids.push(pid);
      continue;
    }
    livePids.push(pid);
  }
  const notes = [
    exitedPids.length > 0
      ? `Cleared stale browser/window handle pid ${exitedPids.join(",")}; the recorded process had exited.`
      : "",
    reusedExecutables.size > 0
      ? `Ignored stale browser/window handle pid ${[...reusedExecutables.keys()].join(",")}; the pid was reused by `
        + `${[...reusedExecutables.values()].join(", ")} and the handle was cleared without terminating any process.`
      : ""
  ].filter(Boolean);
  return { clearedPids, livePids, note: notes.join("; ") };
}

export function readLauncherStateFile(path: string, options: { required?: boolean } = {}): WorkbenchBackendState {
  try {
    const content = readFileSync(path, "utf8");
    if (options.required && content.length > 1024 * 1024) throw new Error("State is oversized.");
    const parsed = JSON.parse(content) as unknown;
    if (!isRecord(parsed) && options.required) throw new Error("State must be an object.");
    return isRecord(parsed) ? parsed : {};
  } catch {
    if (options.required) throw new Error("Launcher retirement state is unavailable.");
    return {};
  }
}

export async function mainLineBackendIsReachable(
  workspaceRoot: string,
  options?: {
    readState?: () => WorkbenchBackendState;
    connect?: (port: number, host: string) => Promise<boolean>;
    pidAlive?: (pid: number) => boolean;
  }
): Promise<boolean> {
  const state = (options?.readState ?? (() => readLauncherStateFile(launcherStatePath(workspaceRoot))))();
  const port = Number(state.backendPort || state.port || 0);
  const host = String(state.host || DEFAULT_WORKBENCH_HOST);
  const pid = Number(state.backendPid || 0);
  const observation = await observeMainLineWorkbench({
    port,
    host,
    knownPids: [pid],
    desiredState: "open",
    frontendReady: true,
    windowOpen: false,
    connect: options?.connect,
    pidAlive: options?.pidAlive
  });
  return observation.backendListening || observation.backendAlive;
}

export function sameProjectRoot(left: string, right: string): boolean {
  const normalize = (value: string): string => value.trim().replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  const a = normalize(left);
  const b = normalize(right);
  return Boolean(a) && a === b;
}

function sameFilesystemPath(left: string, right: string): boolean {
  const normalize = (value: string): string =>
    process.platform === "win32" ? value.toLowerCase() : value;
  return normalize(resolvePath(left)) === normalize(resolvePath(right));
}

/**
 * Fingerprint locations in read order: the governed runtime home first, then
 * the pre-governance checkout copy so an instance that started before (or
 * during) the storage migration stays visible. A present-but-invalid migration
 * marker fails closed on both runtimes and yields no candidate at all, which
 * makes reuse checks conservatively restart instead of reading bypassed
 * storage.
 */
export function runningCodeFingerprintReadPaths(workspaceRoot: string): string[] {
  const paths: string[] = [];
  try {
    const canonicalHome = resolveActiveCanonicalRuntimeHome(workspaceRoot);
    if (canonicalHome) {
      paths.push(join(canonicalHome, RUNNING_CODE_FINGERPRINT_NAME));
    }
  } catch {
    return paths;
  }
  const legacy = join(workspaceRoot, ...RUNNING_CODE_FINGERPRINT_RELATIVE);
  if (!paths.some((existing) => sameFilesystemPath(existing, legacy))) {
    paths.push(legacy);
  }
  return paths;
}

export function readRunningCodeFingerprint(workspaceRoot: string): Record<string, unknown> | null {
  for (const path of runningCodeFingerprintReadPaths(workspaceRoot)) {
    try {
      const parsed = JSON.parse(readFileSync(path, "utf8")) as unknown;
      if (isRecord(parsed)) {
        return parsed;
      }
    } catch {
      // Missing or unreadable candidate: keep consulting the legacy location.
    }
  }
  return null;
}

export function readWorkspaceGitHead(workspaceRoot: string): string {
  try {
    return execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: workspaceRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
      timeout: 10_000
    }).trim();
  } catch {
    return "";
  }
}

export function mainLineRunningCodeIsCurrent(input: {
  workspaceRoot: string;
  fingerprint?: Record<string, unknown> | null;
  diskHead?: string;
}): boolean {
  const fingerprint = input.fingerprint === undefined
    ? readRunningCodeFingerprint(input.workspaceRoot)
    : input.fingerprint;
  if (!fingerprint || Number(fingerprint.schemaVersion) !== 1) {
    return false;
  }
  const runningHead = String(fingerprint.runningHead || "").trim();
  const diskHead = String(input.diskHead ?? readWorkspaceGitHead(input.workspaceRoot)).trim();
  if (!runningHead || !diskHead || runningHead !== diskHead) {
    return false;
  }
  return sameProjectRoot(String(fingerprint.projectRoot || ""), input.workspaceRoot);
}

export async function mainLineBackendIsReusable(
  workspaceRoot: string,
  options?: {
    readState?: () => WorkbenchBackendState;
    connect?: (port: number, host: string) => Promise<boolean>;
    pidAlive?: (pid: number) => boolean;
    fingerprint?: Record<string, unknown> | null;
    diskHead?: string;
  }
): Promise<boolean> {
  if (!await mainLineBackendIsReachable(workspaceRoot, options)) {
    return false;
  }
  return mainLineRunningCodeIsCurrent({
    workspaceRoot,
    fingerprint: options?.fingerprint,
    diskHead: options?.diskHead
  });
}

export async function writeLauncherStateFile(
  path: string, state: WorkbenchBackendState, signal?: AbortSignal,
  isCurrent?: () => boolean
): Promise<void> {
  signal?.throwIfAborted();
  mkdirSync(dirname(path), { recursive: true });
  // State is published by more than one lifecycle writer. A fixed sibling
  // temp name lets concurrent writers overwrite each other's in-progress
  // document before either rename, which can publish torn or stale JSON.
  const tmp = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    writeFileSync(tmp, `${JSON.stringify(state, null, 2)}\n`, "utf8");
    // Windows readers can briefly hold the destination without delete sharing.
    // Keep the old document intact; retry only transient replacement errors,
    // with at most 150ms of asynchronous backoff and no delay on success.
    for (let attempt = 0; ; attempt += 1) {
      signal?.throwIfAborted();
      try {
        // Check + replace stay in one event-loop turn so a superseding intent
        // cannot interleave while an OS rename is still queued.
        if (isCurrent && !isCurrent()) throw new Error("Workbench lifecycle state write was superseded.");
        renameSync(tmp, path);
        break;
      } catch (error: unknown) {
        const code = (error as NodeJS.ErrnoException | null)?.code;
        if (attempt >= 5 || !["EPERM", "EACCES", "EBUSY"].includes(code ?? "")) throw error;
        await delay(10 * (attempt + 1), undefined, { signal });
      }
    }
  } finally {
    try {
      if (existsSync(tmp)) {
        unlinkSync(tmp);
      }
    } catch {
      // The successful rename already published the state; a best-effort
      // cleanup must not turn a successful write into a lifecycle failure.
    }
  }
}

export function preferredWorkbenchPort(input: {
  workspaceRoot: string;
  envPort?: string;
  state?: WorkbenchBackendState;
}): number {
  const envPort = Number(String(input.envPort ?? process.env.VIBELUTION_PORT ?? "").trim());
  if (Number.isFinite(envPort) && envPort > 0) {
    return Math.trunc(envPort);
  }
  const ports = readLauncherStateFile(launcherPortsPath(input.workspaceRoot));
  const saved = Number(ports.backendPort || 0);
  if (Number.isFinite(saved) && saved > 0) {
    return Math.trunc(saved);
  }
  const statePort = Number(input.state?.backendPort || input.state?.port || 0);
  if (Number.isFinite(statePort) && statePort > 0) {
    return Math.trunc(statePort);
  }
  return DEFAULT_WORKBENCH_PORT;
}

export type WorkbenchPortOccupant =
  | { kind: "free" }
  | {
      kind: "same-project-backend";
      pid: number;
      /**
       * False when the pid was proven by the process inventory instead of a
       * live /api/health response. A health-unverified occupant may only be
       * retired through identity capture plus the owned-tree terminator.
       */
      healthVerified?: boolean;
    }
  | { kind: "same-project-legacy-backend" }
  | { kind: "other-project-backend"; workspaceRoot: string }
  | { kind: "unknown" };

// A stale backend can hold gigabytes of paged-out private memory; its graceful
// shutdown needs longer than the normal retire window before it looks stuck.
export const STALE_BACKEND_PORT_RELEASE_WAIT_MS = 15_000;
const OCCUPANT_HEALTH_PROBE_ATTEMPTS = 3;
const OCCUPANT_HEALTH_PROBE_RETRY_MS = 250;

export type WorkbenchRuntimeStateCleanupResult = {
  cleared: boolean;
  removedCount: number;
  failedCount: number;
};

/**
 * Remove only the per-worktree Launcher descriptors after the backend is known
 * to be gone. Keeping a stale state/ports file makes the branch projection
 * report a dead backend as alive and leases its old port on the next start.
 */
export function clearWorkbenchLauncherRuntimeState(
  workspaceRoot: string, options: { preservePath?: string } = {}
): WorkbenchRuntimeStateCleanupResult {
  const canonicalRuntimeHome = resolveCanonicalRuntimeHome(workspaceRoot);
  const runtimeDirs = new Set<string>([
    join(resolveCheckoutRuntimeHome(workspaceRoot), "launcher"),
    ...(canonicalRuntimeHome ? [join(canonicalRuntimeHome, "launcher")] : []),
    resolveLauncherRuntimeDir(workspaceRoot)
  ]);
  const paths = [...runtimeDirs].flatMap((runtimeDir) => [
    join(runtimeDir, "state.json"),
    join(runtimeDir, "ports.json")
  ]);
  let removedCount = 0;
  let failedCount = 0;
  for (const path of paths) {
    if (options.preservePath && resolvePath(path).toLowerCase() === resolvePath(options.preservePath).toLowerCase()) continue;
    try {
      unlinkSync(path);
      removedCount += 1;
    } catch (error: unknown) {
      if ((error as NodeJS.ErrnoException)?.code !== "ENOENT") {
        failedCount += 1;
      }
    }
  }
  return {
    cleared: failedCount === 0,
    removedCount,
    failedCount
  };
}

export async function classifyWorkbenchPortOccupant(input: {
  port: number;
  host?: string;
  workspaceRoot: string;
  signal?: AbortSignal;
  connect?: (port: number, host: string) => Promise<boolean>;
  fetchHealth?: (url: string) => Promise<WorkbenchHealthResponse>;
  /**
   * Inventory-based port owner resolution for a wedged backend that still
   * holds the port but no longer answers /api/health.
   */
  resolvePortOwner?: (port: number) => Promise<WorkbenchPortOwnerResolution | null>;
}): Promise<WorkbenchPortOccupant> {
  input.signal?.throwIfAborted();
  const host = input.host?.trim() || DEFAULT_WORKBENCH_HOST;
  const port = Math.trunc(input.port);
  const connect = input.connect ?? ((nextPort, nextHost) => probeTcpConnect(nextPort, nextHost));
  if (!Number.isFinite(port) || port <= 0 || !(await connect(port, host))) {
    return { kind: "free" };
  }
  const fetchHealth =
    input.fetchHealth
    ?? defaultFetchWorkbenchHealth({
      httpTimeoutMs: BACKEND_HEALTH_HTTP_TIMEOUT_MS,
      signal: input.signal
    });
  let body: Record<string, unknown> | null = null;
  for (let attempt = 1; attempt <= OCCUPANT_HEALTH_PROBE_ATTEMPTS; attempt += 1) {
    input.signal?.throwIfAborted();
    try {
      const response = await fetchHealth(workbenchHealthUrl(port, host));
      if (response.status === 200 && typeof response.json === "function") {
        const parsed: unknown = await response.json();
        input.signal?.throwIfAborted();
        if (isRecord(parsed)) {
          body = parsed;
          break;
        }
      }
    } catch {
      // A booting backend accepts TCP before /api/health answers; retry before
      // declaring the occupant unknown.
    }
    if (attempt < OCCUPANT_HEALTH_PROBE_ATTEMPTS) {
      await new Promise<void>((resolve) => setTimeout(resolve, OCCUPANT_HEALTH_PROBE_RETRY_MS));
    }
  }
  input.signal?.throwIfAborted();
  if (
    body === null
    || body.status !== "ok"
    || typeof body.routesReady !== "boolean"
    || typeof body.workspaceRoot !== "string"
  ) {
    // A wedged backend can keep the listening socket and its process identity
    // while never answering /api/health again. When the project inventory can
    // still prove this pid is the managed workbench backend of this workspace,
    // surface it as a health-unverified same-project occupant so the retire
    // path can capture its identity and terminate it through the owned-tree
    // verifier. Any other outcome stays fail-closed as "unknown".
    if (input.resolvePortOwner) {
      let owner: WorkbenchPortOwnerResolution | null = null;
      try {
        owner = await input.resolvePortOwner(port);
      } catch {
        owner = null;
      }
      input.signal?.throwIfAborted();
      if (
        owner
        && owner.pid > 0
        && owner.alive
        && owner.kind === "managed_workbench_backend"
      ) {
        return { kind: "same-project-backend", pid: owner.pid, healthVerified: false };
      }
    }
    return { kind: "unknown" };
  }
  if (!sameProjectRoot(String(body.workspaceRoot), input.workspaceRoot)) {
    return { kind: "other-project-backend", workspaceRoot: String(body.workspaceRoot) };
  }
  const pid = Number(body.pid || 0);
  if (!Number.isFinite(pid) || pid <= 0) {
    // Same project, but an older build that does not report its pid.
    return { kind: "same-project-legacy-backend" };
  }
  return { kind: "same-project-backend", pid };
}

export type BackendRegistrationOwnership = {
  /** The verified listening-process pid when it differs from the launch pid. */
  ownerPid: number;
  ownerIdentity: PythonProcessIdentity | null;
  note: string;
};

/**
 * Verify that the pid registered for a freshly healthy backend actually owns
 * the listening socket.
 *
 * Health proves a same-project backend answers on the port, not that the
 * spawn pid is the server: a venv ``pythonw.exe`` launcher stub delegates the
 * real base-Python interpreter to a child process, and an unregistered
 * same-project orphan can still own the port. The project process inventory
 * resolves the actual socket owner; when it is this project's managed backend
 * and its identity can be captured, the caller re-registers the owner as
 * ``backendPid`` while keeping the spawn pid as the launch handle — mirroring
 * the launcher's backendPid/launchPid split (_wait_for_started_backend in
 * scripts/vibelution_launcher.py). Everything else stays on the launch
 * registration with a visible note instead of a silent adoption.
 */
export async function adoptBackendRegistrationOwner(input: {
  port: number;
  spawnPid: number;
  healthPid?: number;
  resolvePortOwner: (port: number) => Promise<WorkbenchPortOwnerResolution | null>;
  captureIdentity: (pid: number) => Promise<PythonProcessIdentity | null>;
  signal?: AbortSignal;
}): Promise<BackendRegistrationOwnership> {
  const port = Math.trunc(input.port);
  const spawnPid = Math.trunc(input.spawnPid);
  const healthPid = Math.trunc(Number(input.healthPid || 0));
  if (healthPid > 0 && healthPid === spawnPid) {
    // The health-verified server self-reports the registered spawn pid; no
    // inventory roundtrip is needed for the common direct-python.exe case.
    return { ownerPid: 0, ownerIdentity: null, note: "" };
  }
  let owner: WorkbenchPortOwnerResolution | null = null;
  try {
    owner = await input.resolvePortOwner(port);
  } catch {
    owner = null;
  }
  input.signal?.throwIfAborted();
  const ownerPid = Math.trunc(Number(owner?.pid || 0));
  if (ownerPid <= 0 || !owner?.alive) {
    return {
      ownerPid: 0,
      ownerIdentity: null,
      note: healthPid > 0 && healthPid !== spawnPid
        ? `workbench backend health reported pid ${healthPid} on port ${port} while the registered launch pid is ${spawnPid}; the process inventory could not confirm the socket owner, so the launch registration was kept`
        : ""
    };
  }
  if (ownerPid === spawnPid) {
    // The inventory proves the registered pid owns the socket; a diverging
    // health self-report does not override the socket authority.
    return { ownerPid: 0, ownerIdentity: null, note: "" };
  }
  const discrepancy = `workbench backend port ${port} is owned by pid ${ownerPid} while the registered launch pid ${spawnPid} does not own the listening socket`;
  if (owner.kind !== "managed_workbench_backend") {
    return {
      ownerPid,
      ownerIdentity: null,
      note: `${discrepancy} (process kind ${owner.kind || "unclassified"}); the launch registration was kept without adoption`
    };
  }
  let ownerIdentity: PythonProcessIdentity | null = null;
  try {
    ownerIdentity = await input.captureIdentity(ownerPid);
  } catch {
    ownerIdentity = null;
  }
  input.signal?.throwIfAborted();
  if (!ownerIdentity || Math.trunc(Number(ownerIdentity.pid)) !== ownerPid) {
    return {
      ownerPid,
      ownerIdentity: null,
      note: `${discrepancy} (managed backend); the owner identity could not be captured, so the launch registration was kept without adoption`
    };
  }
  return {
    ownerPid,
    ownerIdentity,
    note: `${discrepancy}; the backend registration adopted the verified socket owner pid ${ownerPid} and kept pid ${spawnPid} as the launch handle (pythonw launcher delegation or an adopted same-project backend)`
  };
}

/** Timing only: diagnostics must not alter retirement or create synthetic test roots. */
function recordBackendRetirementTiming(workspaceRoot: string, stage: string, startedAt: number): number {
  const settledAt = Date.now();
  try {
    if (existsSync(launcherStatePath(workspaceRoot))) {
      appendSupervisorEventFallback(workspaceRoot, {
        eventCode: "electron.backend_retirement.stage",
        message: "Backend retirement stage settled.",
        fields: { stage, durationMs: Math.max(0, settledAt - startedAt) }
      });
    }
  } catch { /* Diagnostic failure cannot change the stop outcome. */ }
  return settledAt;
}

/**
 * Structured note for a registration released because the captured identity
 * proved Windows pid reuse (foreign executable) while the owned port was
 * already free. Diagnostics only: must never alter the reclaim outcome.
 */
function recordForeignPidRegistrationClearance(
  workspaceRoot: string,
  port: number,
  foreignReused: ReadonlyMap<number, string>
): void {
  try {
    if (!existsSync(launcherStatePath(workspaceRoot))) {
      return;
    }
    appendSupervisorEventFallback(workspaceRoot, {
      eventCode: "electron.backend_reclaim.foreign_pid_registration_cleared",
      message: "Registered backend pid was reused by an unrelated process; its registration was cleared without terminating any process.",
      fields: {
        port,
        reusedPids: [...foreignReused.keys()].join(","),
        reusedExecutables: [...foreignReused.values()].join(",")
      }
    });
  } catch { /* Diagnostic failure cannot change the reclaim outcome. */ }
}

/**
 * Structured note for auto-relocating the backend because the preferred port
 * is held by a process whose identity cannot be established. Mirrors the
 * launcher's fresh-start policy (_resolve_start_backend_port): relocation
 * continues the start instead of refusing it. Diagnostics only.
 */
function recordUnknownOccupantPortRelocation(
  workspaceRoot: string,
  preferredPort: number,
  boundPort: number
): void {
  try {
    if (!existsSync(launcherStatePath(workspaceRoot))) {
      return;
    }
    appendSupervisorEventFallback(workspaceRoot, {
      eventCode: "electron.backend_port.unknown_occupant_relocated",
      message: "Preferred backend port was held by an unidentifiable process; the backend auto-bound to the next free port.",
      fields: { preferredPort, boundPort }
    });
  } catch { /* Diagnostic failure cannot change the start outcome. */ }
}

export async function reclaimStaleWorkbenchBackend(input: {
  port: number;
  host?: string;
  workspaceRoot: string;
  signal?: AbortSignal;
  connect?: (port: number, host: string) => Promise<boolean>;
  fetchHealth?: (url: string) => Promise<WorkbenchHealthResponse>;
  pidAlive?: (pid: number) => boolean;
  killPid?: (pid: number) => void | Promise<void>;
  terminateProcessTree?: (pid: number, expectedIdentity?: PythonProcessIdentity) => boolean | Promise<boolean>;
  expectedIdentities?: Readonly<Record<string, PythonProcessIdentity>>;
  /**
   * Capture an identity only after the loopback health check has proved that
   * this PID belongs to this project's workbench. This recovers an orphaned
   * backend whose original launcher parent has already exited.
   */
  captureProcessIdentity?: (pid: number) => Promise<PythonProcessIdentity | null>;
  /** Inventory-based port owner resolution; see classifyWorkbenchPortOccupant. */
  resolvePortOwner?: (port: number) => Promise<WorkbenchPortOwnerResolution | null>;
  /**
   * Python bridge inputs for the identity-checked owned-tree terminator that
   * replaces the single-pid kill fallback when no explicit terminator is
   * injected.
   */
  pythonPath?: string;
  env?: NodeJS.ProcessEnv;
  controlToken?: string;
  /** Explicit operator restart consent to pause active work through graceful shutdown. */
  interruptActiveWork?: boolean;
  gracefulShutdown?: typeof requestGracefulWorkbenchShutdown;
  /** Track log drain work which can outlive its bounded wait. */
  trackBackground?: (work: Promise<unknown>) => void;
  /** Only an explicitly authorized force-stop may bypass an HTTP 409 active-work refusal. */
  forceRetireOnActiveWorkRefusal?: boolean;
  registeredPids?: number[];
  extraPids?: number[];
  now?: () => number;
  delay?: (ms: number) => Promise<void>;
}): Promise<{
  reclaimed: boolean;
  reason: string;
  verifiedPid?: number;
  activeWorkBlocked?: boolean;
  /** A retired real server that was absent from the launcher registry. */
  retiredUnregisteredPid?: number;
  /**
   * Registered pids whose live identity was captured and proven foreign (not
   * the python family the backend runs as) while the owned port was already
   * free: Windows pid reuse, not a leaked tree. Callers must release these
   * registrations; no process behind them was signalled.
   */
  foreignReusePids?: number[];
}> {
  input.signal?.throwIfAborted();
  const port = Math.trunc(input.port);
  if (!Number.isFinite(port) || port <= 0) {
    const pidAlive = input.pidAlive ?? knownPidIsAlive;
    const killPid = input.killPid ?? terminatePid;
    const terminateProcessTree = input.terminateProcessTree;
    const failedTreePids = new Set<number>();
    const extraPids = [...new Set((input.extraPids ?? [])
      .map((pid) => Math.trunc(Number(pid)))
      .filter((pid) => Number.isFinite(pid) && pid > 0))];
    for (const pid of extraPids) {
      input.signal?.throwIfAborted();
      if (terminateProcessTree) {
        const expectedIdentity = input.expectedIdentities?.[String(pid)];
        if (!expectedIdentity || !(await terminateProcessTree(pid, expectedIdentity))) {
          failedTreePids.add(pid);
        }
      } else if (pidAlive(pid)) {
        await killPid(pid);
      }
    }
    const remaining = extraPids.filter((pid) => pidAlive(pid));
    return {
      reclaimed: false,
      reason: failedTreePids.size > 0
        ? `workbench backend port is unavailable; runtime manager pid ${[...failedTreePids].join(",")} retirement was not verified`
        : remaining.length > 0
        ? `workbench backend port is unavailable; runtime manager pid ${remaining.join(",")} remains alive`
        : "workbench backend port is unavailable; registered backend pids were left untouched"
    };
  }
  const pidAlive = input.pidAlive ?? knownPidIsAlive;
  const expectedIdentities: Record<string, PythonProcessIdentity> = {
    ...(input.expectedIdentities ?? {})
  };
  let stageStartedAt = Date.now();
  const occupant = await classifyWorkbenchPortOccupant(input);
  stageStartedAt = recordBackendRetirementTiming(input.workspaceRoot, "port_observation", stageStartedAt);
  input.signal?.throwIfAborted();
  const killPid = input.killPid ?? terminatePid;
  const failedTreePids = new Set<number>();
  // Without an injected terminator, upgrade the retirement from a single-pid
  // kill to the identity-checked, kind-checked owned-tree terminator: a
  // registered pid can be a pythonw launcher stub whose real server runs as a
  // child, and killing only the stub leaves the server holding the port.
  const fallbackTreeTerminator = input.terminateProcessTree || !input.captureProcessIdentity
    || !String(input.pythonPath || "").trim()
    ? undefined
    : createPythonOwnedProcessTreeTerminator({
        pythonPath: String(input.pythonPath),
        workspaceRoot: input.workspaceRoot,
        ...(input.env === undefined ? {} : { env: input.env }),
        allowedKinds: ["managed_workbench_backend"]
      });
  const treeTerminate = input.terminateProcessTree ?? fallbackTreeTerminator;
  const terminateOne = async (pid: number): Promise<boolean> => {
    input.signal?.throwIfAborted();
    const finishLogDrain = async (): Promise<boolean> => {
      const drained = await waitForWorkbenchBackendLogDrain(input.workspaceRoot, pid, undefined, input.trackBackground);
      if (!drained) failedTreePids.add(pid);
      return drained;
    };
    if (await terminateTrackedWorkbenchJob(input.workspaceRoot)) {
      if (!pidAlive(pid)) {
        return await finishLogDrain();
      }
    }
    input.signal?.throwIfAborted();
    if (treeTerminate) {
      let expectedIdentity = expectedIdentities[String(pid)];
      if (!expectedIdentity && input.captureProcessIdentity) {
        // A registered pid without persisted identity (legacy state) can still
        // be retired through the kind-checked verifier once its live identity
        // is captured; the verifier itself fails closed on foreign trees.
        const captured = await input.captureProcessIdentity(pid);
        input.signal?.throwIfAborted();
        if (
          captured
          && Math.trunc(Number(captured.pid)) === pid
          && Number.isFinite(Number(captured.createTime))
          && Number(captured.createTime) > 0
          && String(captured.executable || "").trim()
        ) {
          expectedIdentity = {
            pid,
            createTime: Number(captured.createTime),
            executable: String(captured.executable).trim()
          };
          expectedIdentities[String(pid)] = expectedIdentity;
        }
      }
      // The project classifier is not a substitute for pid/create-time/exe
      // identity. Old state without that identity remains visible rather than
      // risking a PID-reuse kill.
      if (!expectedIdentity) {
        // A legacy pre-identity entry whose process is already gone has
        // nothing to verify or terminate: a dead pid cannot be one of our
        // leaked backends, and no live process sits behind the pid for a
        // PID-reuse mis-kill to hit. If the owned port is also free, no
        // live listener remains to account for either.
        if (!pidAlive(pid)) {
          return await finishLogDrain();
        }
        failedTreePids.add(pid);
        return false;
      }
      const terminated = await treeTerminate(pid, expectedIdentity);
      if (!terminated) {
        failedTreePids.add(pid);
      }
      return terminated && await finishLogDrain();
    }
    await killPid(pid);
    return await finishLogDrain();
  };
  const extraPids = [...new Set((input.extraPids ?? [])
    .map((pid) => Math.trunc(Number(pid)))
    .filter((pid) => Number.isFinite(pid) && pid > 0))];
  const registeredPids = [...new Set((input.registeredPids ?? [])
    .map((pid) => Math.trunc(Number(pid)))
    .filter((pid) => Number.isFinite(pid) && pid > 0))];
  const retireExtras = async (excludePid?: number): Promise<number[]> => {
    // Invoke the verified terminator even when the root no longer exists. A
    // missing root can have re-parented descendants and therefore is not a
    // proof of a clean runtime tree.
    const candidates = extraPids.filter((pid) => pid !== excludePid && (input.terminateProcessTree || pidAlive(pid)));
    for (const pid of candidates) {
      await terminateOne(pid);
    }
    return [...new Set([...candidates.filter((pid) => pidAlive(pid)), ...failedTreePids])];
  };
  const retireRegistered = async (candidatesOverride?: readonly number[]): Promise<number[]> => {
    const candidates = (candidatesOverride ?? registeredPids).filter((pid) => input.terminateProcessTree || pidAlive(pid));
    for (const pid of candidates) {
      await terminateOne(pid);
    }
    return [...new Set([...candidates.filter((pid) => pidAlive(pid)), ...failedTreePids])];
  };
  if (occupant.kind === "free") {
    if (input.interruptActiveWork && (registeredPids.length > 0 || extraPids.length > 0)) {
      return {
        reclaimed: false,
        reason: "explicit user restart shutdown was not confirmed; registered trees remain without a reachable backend"
      };
    }
    // Windows can hand a retired backend's registered pid to an unrelated
    // process before the next reclaim. With the owned port already free, a
    // live registered pid whose captured identity is provably foreign (not
    // the python family the backend runs as) is pid reuse, not a leaked tree:
    // release that registration without signalling anything, mirroring the
    // start-side daemon-record falsification. An identity that cannot be
    // captured, or that still looks like our python family, keeps the
    // conservative verified-retirement requirement below.
    const foreignReused = new Map<number, string>();
    if (input.captureProcessIdentity) {
      for (const pid of registeredPids) {
        if (!pidAlive(pid)) {
          continue;
        }
        const captured = await input.captureProcessIdentity(pid);
        input.signal?.throwIfAborted();
        const executable = String(captured?.executable || "").trim();
        if (
          captured
          && Math.trunc(Number(captured.pid)) === pid
          && Number.isFinite(Number(captured.createTime))
          && Number(captured.createTime) > 0
          && executable
          && !executableLooksLikePythonDaemon(executable)
        ) {
          foreignReused.set(pid, basename(executable));
        }
      }
    }
    const registeredStillPresent = await retireRegistered(registeredPids.filter((pid) => !foreignReused.has(pid)));
    if (registeredStillPresent.length > 0) {
      return {
        reclaimed: false,
        reason: failedTreePids.size > 0
          ? `port ${port} is released but registered backend pid ${[...failedTreePids].join(",")} process-tree retirement was not verified`
          : `port ${port} is released but registered backend pid ${registeredStillPresent.join(",")} is still alive`
      };
    }
    const extrasStillAlive = await retireExtras();
    if (extrasStillAlive.length > 0) {
      return {
        reclaimed: false,
        reason: `port ${port} is released but runtime manager pid ${extrasStillAlive.join(",")} is still alive`
      };
    }
    if (foreignReused.size > 0) {
      const reuseSummary = [...foreignReused].map(([pid, executable]) => `${pid} (${executable})`).join(", ");
      recordForeignPidRegistrationClearance(input.workspaceRoot, port, foreignReused);
      return {
        reclaimed: true,
        reason: `port ${port} is already released; registered backend pid ${reuseSummary} `
          + `was reused by an unrelated process (Windows pid reuse), so its registration was cleared `
          + `without terminating any process`,
        verifiedPid: registeredPids.length === 1 ? registeredPids[0] : undefined,
        foreignReusePids: [...foreignReused.keys()]
      };
    }
    return {
      reclaimed: true,
      reason: `port ${port} is already released`,
      verifiedPid: registeredPids.length === 1 ? registeredPids[0] : undefined
    };
  }
  if (occupant.kind !== "same-project-backend") {
    if (input.interruptActiveWork) {
      return {
        reclaimed: false,
        reason: `explicit user restart shutdown was not confirmed; port ${port} occupant is ${occupant.kind}`
      };
    }
    const extrasStillAlive = await retireExtras();
    return {
      reclaimed: false,
      reason: extrasStillAlive.length > 0
        ? `port ${Math.trunc(input.port)} occupant is ${occupant.kind}; runtime manager pid ${extrasStillAlive.join(",")} remains alive`
        : `port ${Math.trunc(input.port)} occupant is ${occupant.kind}`
    };
  }
  let gracefulCompleted = false;
  let graceful: GracefulWorkbenchShutdownResult | undefined;
  if (occupant.healthVerified === false && !input.captureProcessIdentity) {
    // An inventory-adopted occupant has no live health proof, so the only
    // acceptable retirement evidence is the identity-checked owned-tree
    // terminator. Without an identity capture hook this must fail closed.
    return {
      reclaimed: false,
      reason: `stale backend pid ${occupant.pid} has no verified health and no identity capture is available`,
      verifiedPid: occupant.pid
    };
  }
  if (pidAlive(occupant.pid)) {
    // A graceful HTTP shutdown needs the backend to answer; an inventory-adopted
    // occupant already stopped answering /api/health, so skip the request and go
    // straight to identity capture plus the owned-tree terminator.
    if (input.gracefulShutdown && occupant.healthVerified !== false) {
      graceful = await input.gracefulShutdown({
        port,
        host: input.host,
        backendPid: occupant.pid,
        controlToken: input.controlToken,
        interruptActiveWork: input.interruptActiveWork,
        healthVerified: true,
        signal: input.signal,
        pidAlive,
        connect: input.connect,
        now: input.now,
        delay: input.delay
      });
      input.signal?.throwIfAborted();
      stageStartedAt = recordBackendRetirementTiming(input.workspaceRoot, "graceful_shutdown", stageStartedAt);
      gracefulCompleted = graceful.completed;
      if (gracefulCompleted) {
        const ownedJob = hasTrackedWorkbenchJob(input.workspaceRoot);
        const jobClosed = await closeTrackedWorkbenchJob(input.workspaceRoot);
        input.signal?.throwIfAborted();
        if ((ownedJob && !jobClosed) || !(await waitForWorkbenchBackendLogDrain(input.workspaceRoot, occupant.pid, undefined, input.trackBackground))) {
          return {
            reclaimed: false,
            reason: `backend pid ${occupant.pid} exited but its owned log drains remain pending`,
            verifiedPid: occupant.pid
          };
        }
      }
    }
    const restartPauseConfirmed = graceful?.status === 202 && graceful.requested;
    if (!gracefulCompleted && input.interruptActiveWork && !restartPauseConfirmed) {
      return {
        reclaimed: false,
        activeWorkBlocked: graceful?.status === 409,
        reason: graceful?.reason
          ? `explicit user restart shutdown was not confirmed: ${graceful.reason}`
          : "explicit user restart shutdown was not confirmed; verified process-tree retirement was withheld",
        verifiedPid: occupant.pid
      };
    }
    if (
      !gracefulCompleted
      && graceful?.status === 409
      && !input.forceRetireOnActiveWorkRefusal
    ) {
      return {
        reclaimed: false,
        activeWorkBlocked: true,
        reason: graceful.reason,
        verifiedPid: occupant.pid
      };
    }
    if (!gracefulCompleted) {
      // The occupant was identified either by a live health response or by the
      // project process inventory (wedged backend that stopped answering).
      // Capture its own identity before letting the existing identity-checked,
      // kind-checked tree terminator make the final call.
      if (!expectedIdentities[String(occupant.pid)] && input.captureProcessIdentity) {
        const captured = await input.captureProcessIdentity(occupant.pid);
        input.signal?.throwIfAborted();
        if (
          captured
          && Math.trunc(Number(captured.pid)) === occupant.pid
          && Number.isFinite(Number(captured.createTime))
          && Number(captured.createTime) > 0
          && String(captured.executable || "").trim()
        ) {
          expectedIdentities[String(occupant.pid)] = {
            pid: occupant.pid,
            createTime: Number(captured.createTime),
            executable: String(captured.executable).trim()
          };
        }
      }
      const terminated = await terminateOne(occupant.pid);
      if (!terminated) {
        return {
          reclaimed: false,
          reason: `stale backend pid ${occupant.pid} process-tree retirement was not verified`,
          verifiedPid: occupant.pid
        };
      }
    }
  } else {
    // Health identified a same-project backend, but its root disappeared before
    // retirement began.  Root-PID death does not prove that descendants were
    // reaped; only the identity-checked tree verifier can establish closure.
    if (input.interruptActiveWork) {
      return {
        reclaimed: false,
        reason: `explicit user restart shutdown was not confirmed; backend pid ${occupant.pid} exited before saving tasks`,
        verifiedPid: occupant.pid
      };
    }
    if (!input.terminateProcessTree) {
      return {
        reclaimed: false,
        reason: `stale backend pid ${occupant.pid} exited before process-tree retirement was verified`,
        verifiedPid: occupant.pid
      };
    }
    const terminated = await terminateOne(occupant.pid);
    if (!terminated) {
      return {
        reclaimed: false,
        reason: `stale backend pid ${occupant.pid} process-tree retirement was not verified`,
        verifiedPid: occupant.pid
      };
    }
  }
  const extrasStillAliveBeforePortWait = await retireExtras(occupant.pid);
  if (extrasStillAliveBeforePortWait.length > 0) {
    return {
      reclaimed: false,
      reason: failedTreePids.size > 0
        ? `runtime manager pid ${[...failedTreePids].join(",")} process-tree retirement was not verified`
        : `runtime manager pid ${extrasStillAliveBeforePortWait.join(",")} remains alive after backend retirement`,
      verifiedPid: occupant.pid
    };
  }
  const released = await waitForPortRelease({
    port: input.port,
    host: input.host,
    signal: input.signal,
    now: input.now,
    delay: input.delay,
    connect: input.connect,
    timeoutMs: STALE_BACKEND_PORT_RELEASE_WAIT_MS
  });
  if (!released) {
    return {
      reclaimed: false,
      reason: `stale backend pid ${occupant.pid} still holds port ${Math.trunc(input.port)}`,
      verifiedPid: occupant.pid
    };
  }
  if (pidAlive(occupant.pid)) {
    return {
      reclaimed: false,
      reason: `stale backend pid ${occupant.pid} remains alive after port ${port} was released`,
      verifiedPid: occupant.pid
    };
  }
  recordBackendRetirementTiming(input.workspaceRoot, "ownership_and_log_retirement", stageStartedAt);
  // A retired occupant absent from the registry is a real same-project server
  // that outlived its launcher registration (pythonw stub split or a lost
  // generation). Surface it separately from the generic stale-reclaim note so
  // diagnostics can distinguish "stopped what we registered" from "reclaimed
  // an unregistered server".
  const retiredUnregisteredPid = [...registeredPids, ...extraPids].includes(occupant.pid)
    ? undefined
    : occupant.pid;
  return {
    reclaimed: true,
    reason: gracefulCompleted
      ? `gracefully stopped stale backend pid ${occupant.pid} on port ${Math.trunc(input.port)}`
      : `reclaimed stale backend pid ${occupant.pid} on port ${Math.trunc(input.port)}`,
    verifiedPid: occupant.pid,
    ...(retiredUnregisteredPid ? { retiredUnregisteredPid } : {})
  };
}

export async function resolveBindableWorkbenchPort(input: {
  preferred: number;
  workspaceRoot: string;
  host?: string;
  signal?: AbortSignal;
  connect?: (port: number, host: string) => Promise<boolean>;
  fetchHealth?: (url: string) => Promise<WorkbenchHealthResponse>;
  pidAlive?: (pid: number) => boolean;
  killPid?: (pid: number) => void | Promise<void>;
  terminateProcessTree?: (pid: number, expectedIdentity?: PythonProcessIdentity) => boolean | Promise<boolean>;
  expectedIdentities?: Readonly<Record<string, PythonProcessIdentity>>;
  captureProcessIdentity?: (pid: number) => Promise<PythonProcessIdentity | null>;
  /** Inventory-based port owner resolution for a wedged backend. */
  resolvePortOwner?: (port: number) => Promise<WorkbenchPortOwnerResolution | null>;
  /** Python bridge inputs for the identity-checked tree terminator fallback. */
  pythonPath?: string;
  env?: NodeJS.ProcessEnv;
  controlToken?: string;
  /** Explicit operator restart consent to pause active work through graceful shutdown. */
  interruptActiveWork?: boolean;
  gracefulShutdown?: typeof requestGracefulWorkbenchShutdown;
  /** Track log drain work which can outlive its bounded wait. */
  trackBackground?: (work: Promise<unknown>) => void;
  /** Only an explicitly authorized force-stop may bypass an HTTP 409 active-work refusal. */
  forceRetireOnActiveWorkRefusal?: boolean;
  now?: () => number;
  delay?: (ms: number) => Promise<void>;
}): Promise<{ port: number; note: string }> {
  input.signal?.throwIfAborted();
  const host = input.host?.trim() || DEFAULT_WORKBENCH_HOST;
  const connect = input.connect ?? ((port, nextHost) => probeTcpConnect(port, nextHost));
  const preferred = Math.trunc(input.preferred) > 0 ? Math.trunc(input.preferred) : DEFAULT_WORKBENCH_PORT;
  if (!(await connect(preferred, host))) {
    return { port: preferred, note: "" };
  }
  // Never silently drift to a new port: identify the occupier first. A stale
  // backend of this project is reclaimed; verified foreign projects relocate
  // with a note, and an unidentifiable occupant relocates exactly like the
  // launcher does (_resolve_start_backend_port) instead of failing the start.
  const occupant = await classifyWorkbenchPortOccupant({ ...input, port: preferred, host });
  input.signal?.throwIfAborted();
  if (occupant.kind === "free") {
    // The occupier released the port between the connect probe and the
    // classification; the preferred port is bindable again.
    return { port: preferred, note: "" };
  }
  if (occupant.kind === "same-project-backend" || occupant.kind === "same-project-legacy-backend") {
    if (occupant.kind === "same-project-legacy-backend") {
      throw new Error(
        `workbench backend port ${preferred} is held by a stale backend of this project that does not report its pid (older build); `
          + "stop it manually or set VIBELUTION_PORT."
      );
    }
    const reclaim = await reclaimStaleWorkbenchBackend({ ...input, port: preferred, host });
    if (input.interruptActiveWork && !reclaim.reclaimed) {
      throw new Error(
        `workbench backend port ${preferred} was not rebound because explicit user restart cleanup was not confirmed (${reclaim.reason}).`
      );
    }
    if (await connect(preferred, host)) {
      throw new Error(
        `workbench backend port ${preferred} is still held by stale backend pid ${occupant.pid} of this project `
          + `(${reclaim.reason}); it did not stop within ${STALE_BACKEND_PORT_RELEASE_WAIT_MS}ms. `
          + "Stop it manually or set VIBELUTION_PORT."
      );
    }
    return {
      port: preferred,
      note: reclaim.reclaimed
        ? `port ${preferred} held stale backend pid ${occupant.pid} of this project; reclaimed`
        : `port ${preferred} released while reclaiming a stale backend of this project`
    };
  }
  for (let offset = 1; offset <= 48; offset += 1) {
    const candidate = preferred + offset;
    if (candidate >= 65536) {
      continue;
    }
    if (!(await connect(candidate, host))) {
      if (occupant.kind === "unknown") {
        recordUnknownOccupantPortRelocation(input.workspaceRoot, preferred, candidate);
      }
      return {
        port: candidate,
        note: occupant.kind === "unknown"
          ? `port ${preferred} is occupied by an unidentifiable process; auto-bound this project to ${candidate}`
          : `port ${preferred} in use by another Vibelution project (${occupant.workspaceRoot}); auto-bound this project to ${candidate}`
      };
    }
  }
  throw new Error(`No free workbench backend port found near ${preferred}`);
}

export type FrontendReleaseEnsureResult = {
  skipped: boolean;
  rebuilt: boolean;
  buildKey?: string;
  release?: string;
};

export async function ensureFrontendRelease(input: {
  workspaceRoot: string;
  pythonPath: string;
  env?: NodeJS.ProcessEnv;
  signal?: AbortSignal;
  runBridge?: typeof runPythonJsonBridge;
  terminateProcessTree?: PythonOwnedProcessTreeTerminator;
}): Promise<FrontendReleaseEnsureResult> {
  const runBridge = input.runBridge ?? runPythonJsonBridge;
  const terminateProcessTree = input.terminateProcessTree ?? createPythonOwnedProcessTreeTerminator({
    pythonPath: input.pythonPath,
    workspaceRoot: input.workspaceRoot,
    ...(input.env === undefined ? {} : { env: input.env }),
    allowedKinds: ["frontend_build_bridge"]
  });
  const terminateOwnedTree: PythonJsonBridgeOwnedTreeTerminator = async (child) => {
    const pid = Number(child.pid || 0);
    if (pid > 0) {
      const identity = await pythonJsonBridgeChildIdentity(child);
      if (!identity) {
        throw new Error(`frontend build bridge identity could not be captured for pid ${pid}`);
      }
      const terminated = await terminateProcessTree(pid, identity);
      if (!terminated) {
        throw new Error(`frontend build bridge process-tree retirement was not verified for pid ${pid}`);
      }
    }
  };
  const args = [
    join(input.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
    "--action",
    "ensure-frontend-build",
    "--workspace",
    input.workspaceRoot,
    "--output",
    "json"
  ];
  const raw = process.platform === "win32" && !input.runBridge && !input.terminateProcessTree
    ? await runOwnedFrontendBuildBridge({
      workspaceRoot: input.workspaceRoot, pythonPath: input.pythonPath, args, signal: input.signal, env: input.env
    })
    : await runBridge({
      pythonPath: input.pythonPath,
      args,
      cwd: input.workspaceRoot,
      env: input.env,
      failureLabel: "frontend build preflight",
      timeoutMs: PYTHON_JSON_BRIDGE_MAINTENANCE_TIMEOUT_MS,
      signal: input.signal,
      killPolicy: "owned-tree",
      mutation: true,
      terminateOwnedTree,
      captureChildIdentity: (pid) => capturePythonProcessIdentity({
        pythonPath: input.pythonPath,
        workspaceRoot: input.workspaceRoot,
        ...(input.env === undefined ? {} : { env: input.env }),
        pid
      })
    });
  const payload = parsePythonJsonBridgePayload<{
    ok?: unknown;
    reason?: unknown;
    skipped?: unknown;
    rebuilt?: unknown;
    buildKey?: unknown;
    release?: unknown;
  }>(raw, "frontend build preflight");
  if (payload.ok !== true) {
    throw new Error(String(payload.reason || "frontend build preflight failed"));
  }
  return {
    skipped: Boolean(payload.skipped),
    rebuilt: Boolean(payload.rebuilt),
    ...(typeof payload.buildKey === "string" && payload.buildKey ? { buildKey: payload.buildKey } : {}),
    ...(typeof payload.release === "string" && payload.release ? { release: payload.release } : {})
  };
}

export function defaultEnsureFrontend(
  workspaceRoot: string,
  options: { force: boolean; signal?: AbortSignal; env?: NodeJS.ProcessEnv },
  pythonPath?: string
): Promise<void> {
  // Every start path must verify the content-addressed frontend fingerprint
  // through the shared Python builder. Without pythonPath the bridge cannot
  // verify (or rebuild) a release, so fail fast instead of falling back to
  // serving an unverified legacy dist; ``force`` only means "ensure current
  // sources", matching the builder's own semantics.
  const resolved = String(pythonPath || "").trim();
  if (!resolved) {
    return Promise.reject(new Error(
      "pythonPath is required to verify the frontend build fingerprint; refusing to serve an unverified frontend."
    ));
  }
  void options;
  return ensureFrontendRelease({ workspaceRoot, pythonPath: resolved, signal: options.signal, env: options.env }).then(() => undefined);
}

export type SpawnedWorkbenchBackend = {
  child: WorkbenchBackendSpawnChild;
  pythonPath: string;
  args: string[];
  spawnError: () => Error | null;
  logStatus?: () => BoundedStdioStatus[];
};

type BackendLogOwner = { pid: number; sinks: BoundedStdioSink[] };
const backendLogOwners = new Map<string, BackendLogOwner>();
function backendLogKey(workspaceRoot: string): string {
  const path = resolvePath(workspaceRoot);
  return process.platform === "win32" ? path.toLowerCase() : path;
}

export function readWorkbenchBackendLogStatus(workspaceRoot: string): BoundedStdioStatus[] {
  return backendLogOwners.get(backendLogKey(workspaceRoot))?.sinks.map((sink) => sink.snapshot()) ?? [];
}

export async function waitForWorkbenchBackendLogDrain(
  workspaceRoot: string, expectedPid?: number, timeoutMs = 8_000,
  trackBackground?: (work: Promise<unknown>) => void
): Promise<boolean> {
  const key = backendLogKey(workspaceRoot);
  const owner = backendLogOwners.get(key);
  if (!owner || (expectedPid !== undefined && owner.pid !== expectedPid)) return true;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const retiring = Promise.all(owner.sinks.map((sink) => sink.retire())).then((results) => results.every((result) => result.complete));
    trackBackground?.(retiring);
    const complete = await Promise.race([
      retiring,
      new Promise<boolean>((resolveWait) => { timer = setTimeout(() => resolveWait(false), Math.max(0, timeoutMs)); })
    ]);
    if (complete && backendLogOwners.get(key) === owner) backendLogOwners.delete(key);
    return complete;
  } finally { if (timer) clearTimeout(timer); }
}

export function spawnWorkbenchBackend(input: {
  workspaceRoot: string;
  pythonPath: string;
  port: number;
  baseEnv?: NodeJS.ProcessEnv;
  host?: string;
  scriptRoot?: string;
  dataHome?: string;
  configHome?: string;
  controlPort?: number;
  allowDirty?: boolean;
  allowNonMain?: boolean;
  spawnImpl?: WorkbenchBackendSpawn;
  fileExists?: (path: string) => boolean;
  extraEnv?: NodeJS.ProcessEnv;
  /** Explicit test seam; injected spawn alone never creates log files. */
  logSinkFactory?: (path: string) => BoundedStdioSink;
}): SpawnedWorkbenchBackend {
  const host = input.host?.trim() || DEFAULT_WORKBENCH_HOST;
  const fileExists = input.fileExists ?? existsSync;
  // The tracked Windows spawn already creates the child with CREATE_NO_WINDOW
  // and file-redirected stdio inside a Job (native/workbench-job), so the
  // plain console executable stays windowless there. Keeping python.exe on
  // that path avoids the venv pythonw stub whose base-interpreter delegation
  // splits the real server into an unregistered grandchild pid. Callers
  // without native console suppression keep the pythonw preference.
  const nativeTrackedSpawn = process.platform === "win32" && !input.spawnImpl;
  const pythonPath = resolveNoConsolePython(
    input.pythonPath,
    fileExists,
    nativeTrackedSpawn ? { consoleSuppressedByCaller: true } : {}
  );
  if (!pythonPath) {
    throw new Error("pythonPath is required to spawn the workbench backend");
  }
  const scriptRoot = input.scriptRoot || input.workspaceRoot;
  const script = join(scriptRoot, ...WEB_WORKBENCH_SCRIPT);
  const args = [script, ...workbenchBackendArgs({ host, port: input.port })];
  if (input.dataHome && !input.spawnImpl) {
    mkdirSync(input.dataHome, { recursive: true });
  }
  const env = workbenchBackendEnv({
    workspaceRoot: input.workspaceRoot,
    baseEnv: input.baseEnv,
    port: input.port,
    host,
    dataHome: input.dataHome,
    configHome: input.configHome,
    controlPort: input.controlPort,
    allowDirty: input.allowDirty,
    allowNonMain: input.allowNonMain,
    extra: input.extraEnv
  });
  const spawnImpl = input.spawnImpl ?? (nodeSpawn as unknown as WorkbenchBackendSpawn);
  if (process.platform === "win32" && !input.spawnImpl) {
    const runtimeDir = resolveLauncherRuntimeDir(input.workspaceRoot);
    mkdirSync(runtimeDir, { recursive: true });
    const managed = spawnTrackedWorkbenchProcess(input.workspaceRoot, {
      executable: pythonPath,
      arguments: args,
      cwd: input.workspaceRoot,
      env,
      stdoutPath: join(runtimeDir, "backend.stdout.log"),
      stderrPath: join(runtimeDir, "backend.stderr.log")
    });
    const retireOwnedJob = captureTrackedWorkbenchJobRetirement(input.workspaceRoot, managed.pid);
    let killed = false;
    const child: WorkbenchBackendSpawnChild = {
      pid: managed.pid,
      get exitCode() {
        return killed || !knownPidIsAlive(managed.pid) ? 1 : null;
      },
      get killed() {
        return killed;
      },
      unref() {
        return undefined;
      },
      kill() {
        killed = true;
        void retireOwnedJob?.();
        return true;
      },
      once() {
        return undefined;
      }
    };
    return { child, pythonPath, args, spawnError: () => null };
  }
  const captureLogs = !input.spawnImpl || Boolean(input.logSinkFactory);
  const key = backendLogKey(input.workspaceRoot);
  if (backendLogOwners.has(key)) throw new Error("Previous workbench log pipes have not drained");
  const runtimeDir = resolveLauncherRuntimeDir(input.workspaceRoot);
  if (captureLogs && !input.logSinkFactory) mkdirSync(runtimeDir, { recursive: true });
  const child = spawnImpl(pythonPath, args, {
    cwd: input.workspaceRoot, env, windowsHide: true, detached: true,
    stdio: captureLogs ? ["ignore", "pipe", "pipe"] : ["ignore", "ignore", "ignore"]
  });
  let spawnError: Error | null = null;
  child.once?.("error", (error) => {
    spawnError = error instanceof Error ? error : new Error(String(error));
  });
  const sinks: BoundedStdioSink[] = [];
  if (captureLogs) {
    const owner: BackendLogOwner = { pid: Number(child.pid || 0), sinks };
    backendLogOwners.set(key, owner);
    for (const [name, source] of [["stdout", child.stdout], ["stderr", child.stderr]] as const) {
      if (!source) continue;
      const path = join(runtimeDir, `backend.${name}.log`);
      const sink = input.logSinkFactory?.(path) ?? new BoundedStdioSink(path);
      sinks.push(sink);
      source.once("error", (error) => { sink.recordError(error); sink.end(); });
      source.once("close", () => { if (!sink.writableEnded) sink.end(); });
      source.pipe(sink);
    }
    void Promise.all(sinks.map((sink) => sink.completion)).then((results) => {
      if (results.every((result) => result.complete) && backendLogOwners.get(key) === owner) backendLogOwners.delete(key);
    });
  }
  child.unref?.();
  return { child, pythonPath, args, spawnError: () => spawnError, logStatus: () => sinks.map((sink) => sink.snapshot()) };
}

// launcherLifecycleSupervisor.beginIntent aborts a superseded lease with an
// Error carrying this marker, and the lease signal is aborted for no other
// reason. Matching the marker (in the caught error or the abort reason) is the
// contract for "this operation was replaced by a newer lifecycle intent".
const SUPERSEDED_LIFECYCLE_INTENT_MARKER = "launcher lifecycle intent superseded for";

// A superseded intent is an intentional hand-off to a newer command, not a
// lifecycle failure; persisting it used to strand a sticky failed state
// (e.g. a preflight-failed phase) after the newer command settled successfully.
function isSupersededLifecycleIntent(error: unknown, signal?: AbortSignal): boolean {
  const messageOf = (value: unknown): string =>
    value instanceof Error ? value.message : String(value ?? "");
  return messageOf(error).includes(SUPERSEDED_LIFECYCLE_INTENT_MARKER)
    || (signal?.aborted === true
      && messageOf(signal.reason).includes(SUPERSEDED_LIFECYCLE_INTENT_MARKER));
}

export async function executeMainLineWorkbench(
  input: ExecuteMainLineWorkbenchInput
): Promise<WorkbenchLifecycleResult> {
  input.signal?.throwIfAborted();
  const fileExists = input.fileExists ?? existsSync;
  const statePath = launcherStatePath(input.workspaceRoot);
  const readState = input.readState ?? (() => readLauncherStateFile(statePath));
  const persistState = input.writeState ?? ((state: WorkbenchBackendState) => writeLauncherStateFile(statePath, state, input.signal));
  const writeState = async (state: WorkbenchBackendState): Promise<void> => {
    input.signal?.throwIfAborted();
    await persistState(state);
    input.signal?.throwIfAborted();
  };
  const host = DEFAULT_WORKBENCH_HOST;
  const helperEnvironment = input.targetEnvironment === undefined ? {} : { env: input.targetEnvironment };
  const shutdownOwner = input.gracefulShutdown
    ?? (input.killPid ? undefined : requestGracefulWorkbenchShutdown);
  const targetControlToken = input.controlToken ?? input.targetEnvironment?.VIBELUTION_WEB_CONTROL_TOKEN ?? "";
  // An explicit empty token makes the canonical owner discover the verified
  // target's token, rather than borrowing the Launcher's current project token.
  const targetGracefulShutdown: typeof requestGracefulWorkbenchShutdown | undefined = shutdownOwner && input.targetEnvironment !== undefined
    ? shutdownInput => shutdownOwner({ ...shutdownInput, controlToken: shutdownInput.controlToken ?? targetControlToken })
    : shutdownOwner;
  const operation = input.operation;
  const commandId = input.command.commandId;
  const trackCommandBackground = (work: Promise<unknown>) => trackMainLineBackgroundWork(input.command, work);
  const pendingRetirement = getBackgroundWorkbenchRetirement(input.workspaceRoot);
  if (pendingRetirement?.status === "pending") {
    trackMainLineBackgroundWork(input.command, pendingRetirement.completion);
    return {
      schemaVersion: 1, accepted: ["stop", "force-stop", "shutdown"].includes(operation), operation, commandId,
      code: "backend_retiring", message: "Owned backend resources are still being reclaimed."
    };
  }
  const captureIdentity = input.captureProcessIdentity
    ?? ((captureInput: { pythonPath: string; workspaceRoot: string; pid: number; env?: NodeJS.ProcessEnv }) =>
      capturePythonProcessIdentity(captureInput));
  const captureCurrentBackendIdentity = async (pid: number): Promise<PythonProcessIdentity | null> => {
    return await captureIdentity({
      pythonPath: input.pythonPath,
      workspaceRoot: input.workspaceRoot,
      pid,
      ...helperEnvironment,
      signal: input.signal
    });
  };
  const resolveIdentityForPort = input.resolvePortOwner
    ?? ((ownerInput: { pythonPath: string; workspaceRoot: string; port: number; env?: NodeJS.ProcessEnv }) =>
      resolveWorkbenchPortOwner(ownerInput));
  const resolveCurrentPortOwner = async (port: number): Promise<WorkbenchPortOwnerResolution | null> => {
    return await resolveIdentityForPort({
      pythonPath: input.pythonPath,
      workspaceRoot: input.workspaceRoot,
      port,
      ...helperEnvironment,
      signal: input.signal
    });
  };

  if (operation === "stop" || operation === "force-stop" || operation === "shutdown") {
    const stopStartedAt = Date.now();
    if ((operation === "stop" || operation === "shutdown") && !input.interruptActiveWork) {
      const blocked = blockLifecycleIfActiveWork(
        "stop",
        (input.listActiveWork ?? (() => listActiveWorkRuns(input.workspaceRoot)))()
      );
      if (blocked) {
        return {
          schemaVersion: 1,
          accepted: false,
          operation,
          commandId,
          code: blocked.code,
          message: blocked.message,
          activeWorkRuns: blocked.activeWorkRuns
        };
      }
    }
    const previous = input.fastCloseTiming?.background
      ? (input.readState ? input.readState() : readLauncherStateFile(statePath, { required: true })) : readState();
    if (input.fastCloseTiming?.background && (!isRecord(previous) || Object.keys(previous).length === 0)) {
      throw new Error("Launcher close admission state is unavailable.");
    }
    const port = preferredWorkbenchPort({
      workspaceRoot: input.workspaceRoot,
      state: previous,
      envPort: input.targetEnvironment === undefined ? undefined : input.targetEnvironment.VIBELUTION_PORT ?? ""
    });
    const hasLiveBackendHandle = [previous.spawnPid, previous.backendLaunchPid, previous.backendPid]
      .some((pid) => (input.pidAlive ?? knownPidIsAlive)(Number(pid || 0)));
    if (input.fastCloseTiming && operation === "force-stop"
      && (input.fastCloseTiming.background || hasTrackedWorkbenchJob(input.workspaceRoot) || hasLiveBackendHandle)) {
      const daemonPid = (input.readDaemonPid ?? readDaemonPid)(input.workspaceRoot);
      if (daemonPid > 0 && (input.pidAlive ?? knownPidIsAlive)(daemonPid)) {
        return { schemaVersion: 1, accepted: false, operation, commandId,
          code: "backend_retire_incomplete", message: "A separate Runtime Manager daemon requires verified retirement." };
      }
      if (input.fastCloseTiming.background) {
        // Capture ownership before the first await. Window and command deadlines
        // must not discard this exact retirement identity or re-discover a PID.
        const ownedPid = getTrackedWorkbenchJobPid(input.workspaceRoot)
          || Number(previous.spawnPid || previous.backendLaunchPid || 0);
        const captured = (input.captureRetirement ?? captureTrackedWorkbenchJobRetirement)(input.workspaceRoot, ownedPid);
        const noRegisteredBackend = !hasTrackedWorkbenchJob(input.workspaceRoot)
          && [previous.spawnPid, previous.backendLaunchPid, previous.backendPid].every((pid) => !Number(pid || 0));
        const owned = captured ?? (noRegisteredBackend ? Object.assign(async () => true, { isCurrent: () => true }) : null);
        if (!owned) return { schemaVersion: 1, accepted: false, operation, commandId,
          code: "backend_retire_incomplete", message: "No captured native retirement identity is available." };
        const retirementId = commandId;
        const identityFields = ["spawnPid", "backendLaunchPid", "backendPid", "spawnCreateTime", "backendLaunchCreateTime",
          "backendCreateTime", "spawnExecutable", "backendLaunchExecutable", "backendExecutable"] as const;
        const readRetirementState = (): WorkbenchBackendState => {
          const current = input.readState ? input.readState() : readLauncherStateFile(statePath, { required: true });
          if (!isRecord(current) || !["closed", "open"].includes(String(current.desiredState || ""))
            || typeof current.phase !== "string" || !current.phase) {
            throw new Error("Launcher retirement observation is unavailable.");
          }
          if (!current.backgroundRetirementId && current.desiredState === "closed" && current.phase === "stopping") {
            throw new Error("Launcher retirement request observation is unavailable.");
          }
          return current;
        };
        const isCurrent = (): boolean => {
          const current = readRetirementState();
          return current.backgroundRetirementId === retirementId && current.phase === "stopping"
            && current.desiredState === "closed"
            && preferredWorkbenchPort({ workspaceRoot: input.workspaceRoot, state: current,
              envPort: input.targetEnvironment?.VIBELUTION_PORT ?? "" }) === port
            && identityFields.every((field) => current[field] === previous[field]);
        };
        await writeState({ ...previous, desiredState: "closed", phase: "stopping",
          backgroundRetirementId: retirementId, lastReason: "electron_background_retirement_pending",
          lastSource: "electron_main", updatedAt: isoNow(input.now) });
        let jobRetired = false;
        let buildsRetired = false;
        let fastAttempted = false;
        const retireBuilds = input.fastCloseTiming.background.retireFrontendBuilds;
        const timing = input.fastCloseTiming;
        const retireCaptured = async (): Promise<boolean> => {
          if (noRegisteredBackend && !captured) return true;
          if (fastAttempted) return await owned();
          fastAttempted = true;
          // Keep the existing save/graceful-shutdown opportunity. After its
          // bounded attempt, only this captured retirement may continue.
          return await closeOwnedWorkbenchFast({ workspaceRoot: input.workspaceRoot, port,
            spawnPid: ownedPid,
            deadlineAt: timing.deadlineAt, forceAt: timing.forceAt,
            controlToken: input.controlToken, captureRetirement: () => owned,
            trackBackground: trackCommandBackground });
        };
        const backgroundRetirement = startBackgroundWorkbenchRetirement({
          workspaceRoot: input.workspaceRoot, requestId: retirementId, isCurrent,
          retireCaptured: async () => {
            [jobRetired, buildsRetired] = await Promise.all([
              jobRetired ? true : retireCaptured(), buildsRetired ? true : retireBuilds()
            ]);
            return jobRetired && buildsRetired;
          },
          portClosed: async () => !(await (input.connect ? input.connect(port, host) : probeTcpConnect(port, host, 100))),
          commitClosed: async () => {
            if (!isCurrent()) return false;
            // Admission proved the recorded daemon pid was dead before this
            // retirement started, so its record files are stale leftovers.
            const daemonRecordCleanup = clearStaleRuntimeManagerDaemonRecords(input.workspaceRoot);
            const closed = { ...readRetirementState(), desiredState: "closed", observedState: "closed", phase: "steady",
              failureMessage: "", lifecycleWarning: daemonRecordCleanup.failedPaths.length > 0
                ? `Runtime Manager daemon records could not be cleared: ${daemonRecordCleanup.failedPaths.join(", ")}`
                : "",
              backgroundRetirementId: "",
              backendPid: 0, backendLaunchPid: 0, spawnPid: 0, backendCreateTime: 0, backendExecutable: "",
              backendLaunchCreateTime: 0, backendLaunchExecutable: "", spawnCreateTime: 0, spawnExecutable: "",
              lastReason: "electron_background_retirement_verified", lastSource: "electron_main", updatedAt: isoNow(input.now) };
            clearWorkbenchLauncherRuntimeState(input.workspaceRoot, { preservePath: statePath });
            if (input.writeState) await input.writeState(closed);
            else await writeLauncherStateFile(statePath, closed, undefined, isCurrent);
            return true;
          }
        });
        trackMainLineBackgroundWork(input.command, backgroundRetirement.completion);
        return { ...accepted(operation, commandId), code: "backend_retiring",
          message: "The window may close; owned backend resources are being reclaimed." };
      }
      const retired = await closeOwnedWorkbenchFast({
        workspaceRoot: input.workspaceRoot,
        port,
        spawnPid: getTrackedWorkbenchJobPid(input.workspaceRoot)
          || Number(previous.spawnPid || previous.backendLaunchPid || 0),
        ...input.fastCloseTiming,
        signal: input.signal,
        controlToken: input.controlToken,
        trackBackground: trackCommandBackground
      });
      input.signal?.throwIfAborted();
      if (!retired) {
        return { schemaVersion: 1, accepted: false, operation, commandId,
          code: "backend_retire_incomplete", message: "Owned backend retirement was not verified within the close deadline." };
      }
      // Admission refused while the recorded daemon pid was still alive, so
      // the pid is dead here and its record files are stale leftovers.
      const daemonRecordCleanup = clearStaleRuntimeManagerDaemonRecords(input.workspaceRoot);
      clearWorkbenchLauncherRuntimeState(input.workspaceRoot);
      await writeState({
        ...previous, desiredState: "closed", observedState: "closed", phase: "steady",
        failureMessage: "",
        lifecycleWarning: daemonRecordCleanup.failedPaths.length > 0
          ? `Runtime Manager daemon records could not be cleared: ${daemonRecordCleanup.failedPaths.join(", ")}`
          : "",
        backendPid: 0, backendLaunchPid: 0, spawnPid: 0,
        backendCreateTime: 0, backendExecutable: "",
        backendLaunchCreateTime: 0, backendLaunchExecutable: "",
        spawnCreateTime: 0, spawnExecutable: "",
        lastReason: "electron_main_force_stop", lastSource: "electron_main", updatedAt: isoNow(input.now)
      });
      return accepted(operation, commandId);
    }
    const daemonPid = (input.readDaemonPid ?? readDaemonPid)(input.workspaceRoot);
    const daemonIdentity = (input.readDaemonIdentity ?? readDaemonIdentity)(input.workspaceRoot);
    const verifiedDaemonPid = daemonIdentity?.pid === daemonPid ? daemonPid : 0;
    // A daemon PID without its captured identity is only a historical hint.
    // It may refer to a terminated process (or a reused PID), so it must never
    // be sent to the owned-tree terminator during shutdown or desktop startup.
    const unverifiedDaemonPid = daemonPid > 0 && !verifiedDaemonPid ? daemonPid : 0;
    const extraPids = verifiedDaemonPid > 0 ? [verifiedDaemonPid] : [];
    const expectedIdentities: Record<string, PythonProcessIdentity> = {
      ...stateProcessIdentities(previous),
      ...(input.expectedIdentities ?? {})
    };
    if (daemonIdentity && extraPids.includes(daemonIdentity.pid)) {
      expectedIdentities[String(daemonIdentity.pid)] = daemonIdentity;
    }
    const backendTreePids = ["backendPid", "backendLaunchPid", "spawnPid"]
      .map((key) => Math.trunc(Number(previous[key] || 0)))
      .filter((pid) => Number.isFinite(pid) && pid > 0);
    const registeredHandles = collectRegisteredHandles(previous, extraPids);
    const deadHandleReconcile = await reconcileDeadRegisteredHandles({
      pids: registeredHandles,
      port,
      host,
      expectedIdentities,
      pidAlive: input.pidAlive,
      connect: input.connect
    });
    input.signal?.throwIfAborted();
    recordBackendRetirementTiming(input.workspaceRoot, "registered_ownership_observation", stopStartedAt);
    const reconciledDeadPids = new Set(deadHandleReconcile.reconciledPids);
    const retainedRegisteredHandles = registeredHandles.filter((pid) => !reconciledDeadPids.has(pid));
    const retainedBackendTreePids = backendTreePids.filter((pid) => !reconciledDeadPids.has(pid));
    const retainedExtraPids = extraPids.filter((pid) => !reconciledDeadPids.has(pid));
    // An injected killPid is a test/host override for the known backend and
    // daemon handles only; browser/window handles remain fail-closed below.
    const injectedOwnedDirectPids = input.killPid
      ? [...retainedBackendTreePids, ...retainedExtraPids]
      : [];
    const terminateProcessTree = input.terminateProcessTree
      ?? (input.killPid
        ? undefined
        : createPythonOwnedProcessTreeTerminator({
            pythonPath: input.pythonPath,
            workspaceRoot: input.workspaceRoot,
            ...helperEnvironment,
            allowedKinds: ["managed_workbench_backend", "runtime_manager_daemon"]
          }));
    const gracefulShutdown = targetGracefulShutdown;
    let staleReclaim: {
      reclaimed: boolean;
      reason: string;
      verifiedPid?: number;
      activeWorkBlocked?: boolean;
      retiredUnregisteredPid?: number;
      foreignReusePids?: number[];
    };
    if (gracefulShutdown && terminateProcessTree) {
      staleReclaim = await reclaimStaleWorkbenchBackend({
        port,
        host,
        workspaceRoot: input.workspaceRoot,
        signal: input.signal,
        connect: input.connect,
        fetchHealth: input.fetchHealth,
        pidAlive: input.pidAlive,
        killPid: input.killPid,
        terminateProcessTree,
        expectedIdentities,
        captureProcessIdentity: captureCurrentBackendIdentity,
        resolvePortOwner: resolveCurrentPortOwner,
        pythonPath: input.pythonPath,
        env: input.targetEnvironment,
        controlToken: input.controlToken,
        gracefulShutdown,
        trackBackground: trackCommandBackground,
        interruptActiveWork: input.interruptActiveWork,
        forceRetireOnActiveWorkRefusal: operation === "force-stop",
        registeredPids: retainedBackendTreePids,
        extraPids: retainedExtraPids
      });
    } else {
      staleReclaim = {
        reclaimed: false,
        reason: "backend retirement is pending registered-handle cleanup"
      };
    }
    if (input.interruptActiveWork && !staleReclaim.reclaimed) {
      return {
        schemaVersion: 1,
        accepted: false,
        operation,
        commandId,
        code: "user_restart_pause_failed",
        message: `explicit user restart shutdown was not confirmed: ${staleReclaim.reason}`
      };
    }
    const unverifiedHandles: number[] = [];
    let postReclaimReconcileReason = "";
    if (!staleReclaim.activeWorkBlocked) {
      // reclaimStaleWorkbenchBackend settles the entire registered backend
      // tree once the health-verified backend process and its owned port are
      // both gone. backendLaunchPid/spawnPid can be a short-lived pythonw
      // wrapper distinct from backendPid; re-running the root-only terminator
      // for that already-exited wrapper turns a successful shutdown into a
      // false failure and prevents Electron from closing the Workbench window.
      const postReclaimReconcile = await reconcileDeadRegisteredHandles({
        pids: retainedRegisteredHandles,
        port,
        host,
        expectedIdentities,
        pidAlive: input.pidAlive,
        connect: input.connect
      });
      for (const pid of postReclaimReconcile.reconciledPids) {
        reconciledDeadPids.add(pid);
      }
      for (const pid of staleReclaim.foreignReusePids ?? []) {
        // A captured foreign executable plus an already-released port proves
        // the registered pid was reused by an unrelated process; clearing it
        // here lets stateWithoutReconciledBackendHandles drop the stale
        // registration instead of wedging every later stop on it.
        reconciledDeadPids.add(pid);
      }
      if (postReclaimReconcile.reconciledPids.length > 0) {
        postReclaimReconcileReason = postReclaimReconcile.reason;
      }
      const pendingBackendTreePids = retainedBackendTreePids.filter((pid) => !reconciledDeadPids.has(pid));
      const pendingExtraPids = retainedExtraPids.filter((pid) => !reconciledDeadPids.has(pid));
      if (
        !staleReclaim.reclaimed
        && pendingBackendTreePids.length === 0
        && pendingExtraPids.length === 0
      ) {
        // The first reclaim can release the backend port before discovering
        // that a persisted daemon/root PID was already dead. Once the existing
        // identity-bound dead-handle reconciler has released every owned tree
        // registration, recompute the reclaim result with those stale roots
        // removed instead of sending a second termination request.
        staleReclaim = await reclaimStaleWorkbenchBackend({
          port,
          host,
          workspaceRoot: input.workspaceRoot,
          signal: input.signal,
          connect: input.connect,
          fetchHealth: input.fetchHealth,
          pidAlive: input.pidAlive,
          killPid: input.killPid,
          terminateProcessTree,
          expectedIdentities,
          captureProcessIdentity: captureCurrentBackendIdentity,
          resolvePortOwner: resolveCurrentPortOwner,
          pythonPath: input.pythonPath,
          env: input.targetEnvironment,
          controlToken: input.controlToken,
          gracefulShutdown,
          trackBackground: trackCommandBackground,
          forceRetireOnActiveWorkRefusal: operation === "force-stop",
          registeredPids: pendingBackendTreePids,
          extraPids: pendingExtraPids
        });
      }
      const pendingRegisteredHandles = postReclaimReconcile.retainedPids
        .filter((pid) => !staleReclaim.reclaimed || !retainedBackendTreePids.includes(pid));
      await retireRegisteredHandles({
        pids: pendingRegisteredHandles,
        port,
        host,
        signal: input.signal,
        pidAlive: input.pidAlive,
        killPid: input.killPid,
        terminateProcessTree,
        // Backend handles were removed above after successful reclaim. The
        // separately owned Runtime Manager daemon still needs normal verified
        // tree retirement.
        treePids: pendingExtraPids,
        expectedIdentities,
        ownedDirectPids: [...(input.ownedDirectPids ?? []), ...injectedOwnedDirectPids],
        reportUnverified: (pids) => unverifiedHandles.push(...pids),
        connect: input.connect
      });
    }
    // A stale same-project backend whose pid was lost from state must not
    // outlive a stop; foreign occupants are intentionally left alone.
    if (!staleReclaim.activeWorkBlocked && (!gracefulShutdown || !terminateProcessTree)) {
      staleReclaim = await reclaimStaleWorkbenchBackend({
        port,
        host,
        workspaceRoot: input.workspaceRoot,
        signal: input.signal,
        connect: input.connect,
        fetchHealth: input.fetchHealth,
        pidAlive: input.pidAlive,
        killPid: input.killPid,
        terminateProcessTree,
        expectedIdentities,
        captureProcessIdentity: captureCurrentBackendIdentity,
        resolvePortOwner: resolveCurrentPortOwner,
        pythonPath: input.pythonPath,
        env: input.targetEnvironment,
        controlToken: input.controlToken,
        trackBackground: trackCommandBackground,
        forceRetireOnActiveWorkRefusal: operation === "force-stop",
        registeredPids: retainedBackendTreePids,
        extraPids: retainedExtraPids
      });
    }
    if (!staleReclaim.reclaimed) {
      const message = `backend retirement remains unverified: ${staleReclaim.reason}`;
      await writeState({
        ...stateWithoutReconciledBackendHandles(previous, reconciledDeadPids),
        desiredState: "closed",
        observedState: "failed",
        phase: "failed",
        lifecycleWarning: message,
        lastReason: `electron_main_${operation.replace("-", "_")}_retirement_pending`,
        lastSource: "electron_main",
        updatedAt: isoNow(input.now)
      });
      return {
        schemaVersion: 1,
        accepted: false,
        operation,
        commandId,
        code: staleReclaim.activeWorkBlocked ? "active_work_blocked" : "backend_retire_incomplete",
        message
      };
    }
    const previousBrowserLaunchPid = Math.trunc(Number(previous.browserLaunchPid || previous.workbenchBrowserLaunchPid || 0));
    const previousBrowserWindowPid = Math.trunc(Number(previous.browserWindowPid || previous.workbenchBrowserWindowPid || 0));
    const retainedBrowserLaunchPid = unverifiedHandles.includes(previousBrowserLaunchPid) ? previousBrowserLaunchPid : 0;
    const retainedBrowserWindowPid = unverifiedHandles.includes(previousBrowserWindowPid) ? previousBrowserWindowPid : 0;
    // Every verified daemon was retired above, so its record files are stale.
    // An unverified record is only dropped when the pid is dead or provably
    // reused by a foreign process; a live python-family pid keeps its records
    // and stays skipped without being terminated.
    const daemonRecordReconciliation = await reconcileStaleRuntimeManagerDaemonRecords({
      workspaceRoot: input.workspaceRoot,
      daemonPid,
      pidAlive: input.pidAlive ?? knownPidIsAlive,
      captureIdentity: captureCurrentBackendIdentity
    });
    const lifecycleWarnings = [
      deadHandleReconcile.reconciledPids.length > 0
        ? `${deadHandleReconcile.reason}; no process was terminated during reconciliation`
        : "",
      postReclaimReconcileReason
        ? `${postReclaimReconcileReason}; no process was terminated during post-reclaim reconciliation`
        : "",
      daemonRecordReconciliation.note,
      !daemonRecordReconciliation.stale && unverifiedDaemonPid > 0
        ? `Skipped unverified Runtime Manager daemon pid ${unverifiedDaemonPid}; no process was terminated.`
        : "",
      unverifiedHandles.length > 0
        ? `unverified browser/window handles retained: ${[...new Set(unverifiedHandles)].join(",")}`
        : ""
    ].filter(Boolean);
    const lifecycleWarning = lifecycleWarnings.join("; ");
    input.signal?.throwIfAborted();
    clearWorkbenchLauncherRuntimeState(input.workspaceRoot);
    await writeState({
      ...previous,
      desiredState: "closed",
      observedState: "closed",
      phase: "steady",
      // A settled lifecycle command must not carry a previous failure's
      // message; a stale failureMessage keeps the branch page in runtime.error.
      failureMessage: "",
      backendPid: 0,
      backendLaunchPid: 0,
      spawnPid: 0,
      backendCreateTime: 0,
      backendExecutable: "",
      backendLaunchCreateTime: 0,
      backendLaunchExecutable: "",
      spawnCreateTime: 0,
      spawnExecutable: "",
      browserLaunchPid: retainedBrowserLaunchPid,
      browserWindowPid: retainedBrowserWindowPid,
      ...(staleReclaim.reclaimed
        ? (staleReclaim.retiredUnregisteredPid
          ? {
              orphanBackendRetirementNote:
                `reclaimed unregistered same-project backend pid ${staleReclaim.retiredUnregisteredPid}: ${staleReclaim.reason}`
            }
          : { staleReclaimNote: staleReclaim.reason })
        : {}),
      ...(lifecycleWarning ? { lifecycleWarning } : {}),
      lastReason: `electron_main_${operation.replace("-", "_")}`,
      lastSource: "electron_main",
      updatedAt: isoNow(input.now)
    });
    return accepted(operation, commandId, lifecycleWarning ? { message: lifecycleWarning } : {});
  }

  if (operation === "restart") {
    const blocked = input.interruptActiveWork
      ? null
      : blockLifecycleIfActiveWork(
          "restart",
          (input.listActiveWork ?? (() => listActiveWorkRuns(input.workspaceRoot)))()
        );
    if (blocked) {
      const intent = queueDeferredRestartIntent(input.workspaceRoot, {
        reason: blocked.message,
        sourceCommandId: commandId,
        requestedBy: "electron_main"
      });
      return {
        schemaVersion: 1,
        accepted: true,
        operation,
        commandId,
        code: "restart_queued",
        message: intent
          ? "有进行中的任务，已登记预约重启：任务结束后自动执行。"
          : blocked.message,
        activeWorkRuns: blocked.activeWorkRuns,
        ...(intent ? { restartIntentId: intent.intentId } : {})
      };
    }
  }

  let previous = readState();
  let reconciledDeadPids: ReadonlySet<number> = new Set();
  const persistStartPreflightFailure = async (error: unknown): Promise<void> => {
    // The error is rethrown by every caller; a superseded intent settles
    // through the supervisor's superseded/ignored outcome instead of a state.
    if (input.signal?.aborted || isSupersededLifecycleIntent(error, input.signal)) {
      return;
    }
    const detail = error instanceof Error ? error.message : String(error);
    await writeState({
      ...stateWithoutReconciledBackendHandles(previous, reconciledDeadPids),
      desiredState: "closed",
      observedState: "failed",
      phase: "failed",
      lifecycleWarning: detail,
      lastReason: `electron_main_${operation.replace(/-/g, "_")}_preflight_failed`,
      lastSource: "electron_main",
      updatedAt: isoNow(input.now)
    });
  };
  try {
    await (input.ensureFrontend ?? ((opts) => defaultEnsureFrontend(
      input.workspaceRoot,
      opts,
      input.pythonPath
    )))({
      force: operation === "rebuild-and-start",
      signal: input.signal,
      ...(input.targetEnvironment === undefined ? {} : { env: input.targetEnvironment })
    });
  } catch (error: unknown) {
    await persistStartPreflightFailure(error);
    throw error;
  }
  input.signal?.throwIfAborted();

  const preferred = preferredWorkbenchPort({
    workspaceRoot: input.workspaceRoot,
    state: previous,
    envPort: input.targetEnvironment === undefined ? undefined : input.targetEnvironment.VIBELUTION_PORT ?? ""
  });
  const daemonPid = (input.readDaemonPid ?? readDaemonPid)(input.workspaceRoot);
  const daemonIdentity = (input.readDaemonIdentity ?? readDaemonIdentity)(input.workspaceRoot);
  const verifiedDaemonPid = daemonIdentity?.pid === daemonPid ? daemonPid : 0;
  const daemonPidIsAlive = daemonPid > 0 && (input.pidAlive ?? knownPidIsAlive)(daemonPid);
  let reusedDaemonRecordNote = "";
  if (daemonPid > 0 && !verifiedDaemonPid && daemonPidIsAlive) {
    // Windows may have handed the recorded pid to an unrelated process after
    // the historical daemon exited. Only when the live executable is provably
    // foreign (not the python family the daemon runs as) is the record stale
    // beyond doubt; then the record files alone are dropped and the start
    // proceeds. A python-family pid, or one whose identity cannot be captured,
    // keeps the conservative refusal.
    const reusedPidIdentity = await captureCurrentBackendIdentity(daemonPid);
    if (!reusedPidIdentity || executableLooksLikePythonDaemon(reusedPidIdentity.executable)) {
      const error = new Error(
        `Runtime Manager daemon pid ${daemonPid} is live but has no verifiable identity; refusing to retire it before starting the workbench.`,
      );
      await persistStartPreflightFailure(error);
      throw error;
    }
    const recordCleanup = clearStaleRuntimeManagerDaemonRecords(input.workspaceRoot);
    if (recordCleanup.failedPaths.length > 0) {
      const error = new Error(
        `Runtime Manager daemon pid ${daemonPid} was reused by ${basename(reusedPidIdentity.executable.trim())} `
        + `but its stale records could not be cleared (${recordCleanup.failedPaths.join(", ")}); refusing to start.`,
      );
      await persistStartPreflightFailure(error);
      throw error;
    }
    reusedDaemonRecordNote = `Ignored stale Runtime Manager daemon pid ${daemonPid}; the pid was reused by `
      + `${basename(reusedPidIdentity.executable.trim())} and its record files were cleared without terminating any process.`;
  }
  // A PID alone is not ownership evidence: Windows can reuse it after the
  // historical Runtime Manager process has exited. Keep the stale record on
  // disk for the owning lifecycle to reconcile, but never let it block a new
  // workbench start or target an unrelated process for termination.
  const ignoredStaleDaemonPid = daemonPid > 0 && !verifiedDaemonPid && !reusedDaemonRecordNote ? daemonPid : 0;
  const extraPids = verifiedDaemonPid > 0 ? [verifiedDaemonPid] : [];
  const expectedIdentities: Record<string, PythonProcessIdentity> = {
    ...stateProcessIdentities(previous),
    ...(input.expectedIdentities ?? {})
  };
  if (daemonIdentity && extraPids.includes(daemonIdentity.pid)) {
    expectedIdentities[String(daemonIdentity.pid)] = daemonIdentity;
  }
  const backendTreePids = ["backendPid", "backendLaunchPid", "spawnPid"]
    .map((key) => Math.trunc(Number(previous[key] || 0)))
    .filter((pid) => Number.isFinite(pid) && pid > 0);
  // A closed built-in browser window leaves its pid handle in state. Falsify
  // provably stale handles (pid exited, or Windows reused it for a non-browser
  // process) before the unverified-handle refusal below, so closing the browser
  // cannot wedge cleanup/restart forever; a live browser keeps the refusal.
  const browserHandleFalsification = await falsifyStaleBrowserWindowHandles({
    state: previous,
    pidAlive: input.pidAlive ?? knownPidIsAlive,
    trustedPids: [...backendTreePids, ...extraPids, ...(input.ownedDirectPids ?? [])],
    captureIdentity: captureCurrentBackendIdentity,
    signal: input.signal
  });
  if (browserHandleFalsification.clearedPids.length > 0) {
    previous = stateWithoutBrowserWindowHandles(previous, new Set(browserHandleFalsification.clearedPids));
  }
  const registeredHandles = collectRegisteredHandles(previous, extraPids);
  const deadHandleReconcile = await reconcileDeadRegisteredHandles({
    pids: registeredHandles,
    port: preferred,
    host,
    expectedIdentities,
    pidAlive: input.pidAlive,
    connect: input.connect
  });
  input.signal?.throwIfAborted();
  reconciledDeadPids = new Set(deadHandleReconcile.reconciledPids);
  const deadHandleReconcileReasons = deadHandleReconcile.reconciledPids.length > 0
    ? [deadHandleReconcile.reason]
    : [];
  const retainedRegisteredHandles = registeredHandles.filter((pid) => !reconciledDeadPids.has(pid));
  const retainedBackendTreePids = backendTreePids.filter((pid) => !reconciledDeadPids.has(pid));
  const retainedExtraPids = extraPids.filter((pid) => !reconciledDeadPids.has(pid));
  const injectedOwnedDirectPids = input.killPid
    ? [...retainedBackendTreePids, ...retainedExtraPids]
    : [];
  const terminateProcessTree = input.terminateProcessTree
    ?? (input.killPid
      ? undefined
      : createPythonOwnedProcessTreeTerminator({
          pythonPath: input.pythonPath,
          workspaceRoot: input.workspaceRoot,
          ...helperEnvironment,
          allowedKinds: ["managed_workbench_backend", "runtime_manager_daemon"]
        }));
  const gracefulShutdownImpl = targetGracefulShutdown;
  let restartPauseConfirmed = false;
  const gracefulShutdown: typeof requestGracefulWorkbenchShutdown | undefined = gracefulShutdownImpl
    ? async (shutdownInput) => {
        const result = await gracefulShutdownImpl(shutdownInput);
        restartPauseConfirmed = result.requested && result.status === 202;
        return result;
      }
    : undefined;
  const unverifiedHandles: number[] = [];
  let resolved: { port: number; note: string };
  let unretiredRegisteredNote = "";
  try {
    const liveUnverifiedBrowserHandles = liveUnverifiedBrowserWindowHandles(
      previous,
      input.pidAlive ?? knownPidIsAlive,
      [...retainedBackendTreePids, ...retainedExtraPids, ...(input.ownedDirectPids ?? [])]
    );
    if (liveUnverifiedBrowserHandles.length > 0) {
      throw new Error(
        `Refusing to start while unverified browser/window handles remain: ${liveUnverifiedBrowserHandles.join(",")}`
      );
    }
    // Classify and, when necessary, gracefully retire the port occupant before
    // touching registered handles. An explicit operator restart can ask the
    // backend to pause and persist active work; any process-tree fallback still
    // requires a 202 pause acknowledgement plus verified process ownership.
    resolved = await resolveBindableWorkbenchPort({
      preferred,
      host,
      workspaceRoot: input.workspaceRoot,
      signal: input.signal,
      connect: input.connect,
      fetchHealth: input.fetchHealth,
      pidAlive: input.pidAlive,
      killPid: input.killPid,
      terminateProcessTree,
      expectedIdentities,
      captureProcessIdentity: captureCurrentBackendIdentity,
      resolvePortOwner: resolveCurrentPortOwner,
      pythonPath: input.pythonPath,
      env: input.targetEnvironment,
      gracefulShutdown,
      trackBackground: trackCommandBackground,
      interruptActiveWork: input.interruptActiveWork,
      forceRetireOnActiveWorkRefusal: false
    });
    if (input.interruptActiveWork && !restartPauseConfirmed
      && (retainedBackendTreePids.length > 0 || retainedExtraPids.length > 0)) {
      throw new Error("explicit user restart shutdown was not confirmed; registered trees were retained before a new backend could start");
    }
    if (resolved.port === preferred && retainedRegisteredHandles.length > 0) {
      // The port reclaim can also retire a distinct pythonw launch wrapper.
      // Release only identity-bound dead registrations on their original port;
      // live or unverifiable trees still require the normal retirement path.
      const postReclaimReconcile = await reconcileDeadRegisteredHandles({
        pids: retainedRegisteredHandles,
        port: preferred,
        host,
        expectedIdentities,
        pidAlive: input.pidAlive,
        connect: input.connect
      });
      input.signal?.throwIfAborted();
      reconciledDeadPids = new Set([...reconciledDeadPids, ...postReclaimReconcile.reconciledPids]);
      if (postReclaimReconcile.reconciledPids.length > 0) {
        deadHandleReconcileReasons.push(postReclaimReconcile.reason);
      }
    }
    try {
      await retireRegisteredHandles({
        pids: retainedRegisteredHandles.filter((pid) => !reconciledDeadPids.has(pid)),
        port: resolved.port,
        host,
        signal: input.signal,
        pidAlive: input.pidAlive,
        killPid: input.killPid,
        terminateProcessTree,
        treePids: [...retainedBackendTreePids, ...retainedExtraPids].filter((pid) => !reconciledDeadPids.has(pid)),
        expectedIdentities,
        ownedDirectPids: [...(input.ownedDirectPids ?? []), ...injectedOwnedDirectPids],
        reportUnverified: (pids) => unverifiedHandles.push(...pids),
        connect: input.connect
      });
    } catch (error: unknown) {
      // A registered handle that cannot be identity-verified while the
      // resolved port has no listener is a stale record whose pid was reused
      // by an unrelated process, not a live backend. Binding authority is the
      // port probe; the kill decision stays with the identity-checked tree
      // terminator. Mirror ignoredStaleDaemonPid: keep the failure visible as
      // a lifecycle warning instead of stranding start/restart.
      const connect = input.connect ?? ((nextPort, nextHost) => probeTcpConnect(nextPort, nextHost));
      if (await connect(resolved.port, host)) {
        throw error;
      }
      unretiredRegisteredNote = `registered handle retirement stayed unverified while port ${resolved.port} was released: ${error instanceof Error ? error.message : String(error)}`;
    }
    if (unverifiedHandles.length > 0) {
      throw new Error(`Refusing to start while unverified browser/window handles remain: ${[...new Set(unverifiedHandles)].join(",")}`);
    }
  } catch (error: unknown) {
    await persistStartPreflightFailure(error);
    throw error;
  }
  input.signal?.throwIfAborted();
  try { input.beforeSpawn?.(); }
  catch (error) { await persistStartPreflightFailure(error); throw error; }
  const spawned = spawnWorkbenchBackend({
    workspaceRoot: input.workspaceRoot,
    baseEnv: input.targetEnvironment,
    pythonPath: input.pythonPath,
    port: resolved.port,
    host,
    spawnImpl: input.spawnImpl,
    fileExists
  });
  const spawnPid = Number(spawned.child.pid || 0);
  const retireOwnedJob = captureTrackedWorkbenchJobRetirement(input.workspaceRoot, spawnPid);
  let backendIdentity: PythonProcessIdentity | null = null;
  let backendOwner: BackendRegistrationOwnership = { ownerPid: 0, ownerIdentity: null, note: "" };
  const persistUnretiredStart = async (message: string): Promise<void> => {
    if (input.signal?.aborted) return;
    await writeState({
      ...stateWithoutReconciledBackendHandles(previous, reconciledDeadPids),
      desiredState: "closed",
      observedState: "failed",
      phase: "failed",
      host,
      backendPort: resolved.port,
      port: resolved.port,
      url: `http://${host}:${resolved.port}`,
      backendPid: spawnPid,
      backendLaunchPid: spawnPid,
      spawnPid,
      ...(backendIdentity
        ? {
            backendCreateTime: backendIdentity.createTime,
            backendExecutable: backendIdentity.executable,
            backendLaunchCreateTime: backendIdentity.createTime,
            backendLaunchExecutable: backendIdentity.executable,
            spawnCreateTime: backendIdentity.createTime,
            spawnExecutable: backendIdentity.executable
          }
        : {}),
      lifecycleWarning: message,
      lastReason: "electron_main_start_retirement_pending",
      lastSource: "electron_main",
      updatedAt: isoNow(input.now)
    });
  };
  const retireSpawnedTree = async (): Promise<void> => {
    const finishLogDrain = async (): Promise<void> => {
      if (!(await waitForWorkbenchBackendLogDrain(input.workspaceRoot, spawnPid, undefined, trackCommandBackground))) {
        throw new Error(`workbench backend log drain remains pending for pid ${spawnPid}`);
      }
    };
    if (spawnPid <= 0) {
      return;
    }
    if (retireOwnedJob) {
      // This cleanup belongs to the captured spawn, never a replacement Job.
      // A stale capture must not fall back to retiring a workspace/PID again.
      if (!retireOwnedJob.isCurrent()) return;
      if (await retireOwnedJob()) {
        await finishLogDrain();
        return;
      }
      throw new Error(`workbench backend owned Job retirement was not verified for pid ${spawnPid}`);
    }
    if (terminateProcessTree) {
      if (!backendIdentity) {
        throw new Error(`workbench backend process identity could not be captured for pid ${spawnPid}`);
      }
      if (!(await terminateProcessTree(spawnPid, backendIdentity))) {
        throw new Error(`workbench backend process-tree retirement was not verified for pid ${spawnPid}`);
      }
      await finishLogDrain();
      return;
    }
    if (input.killPid) {
      await input.killPid(spawnPid);
      await finishLogDrain();
      return;
    }
    throw new Error(`workbench backend process-tree terminator was not configured for pid ${spawnPid}`);
  };
  try {
    if (spawnPid > 0 && captureIdentity) {
      backendIdentity = await captureIdentity({
        pythonPath: spawned.pythonPath,
        workspaceRoot: input.workspaceRoot,
        ...helperEnvironment,
        pid: spawnPid,
        signal: input.signal
      });
      if (!backendIdentity) {
        throw new Error(`workbench backend process identity could not be captured for pid ${spawnPid}`);
      }
    }
    input.signal?.throwIfAborted();
    const healthBody = await waitForBackendHealthy({
      port: resolved.port,
      host,
      readiness: "shell",
      signal: input.signal,
      childError: () => {
        const spawnError = spawned.spawnError();
        return spawnError === null ? null : new Error(`workbench backend failed to spawn: ${spawnError.message}`);
      },
      childAlive: () => {
        return spawned.child.exitCode == null && spawned.child.killed !== true;
      },
      connect: input.connect,
      fetchHealth: input.fetchHealth
    });
    input.signal?.throwIfAborted();
    // Health alone does not prove the registered pid owns the listening
    // socket (pythonw stub delegation, adopted orphan). Verify the socket
    // owner against the spawn registration before settling into steady.
    backendOwner = await adoptBackendRegistrationOwner({
      port: resolved.port,
      spawnPid,
      healthPid: Number(healthBody?.pid || 0),
      resolvePortOwner: resolveCurrentPortOwner,
      captureIdentity: captureCurrentBackendIdentity,
      signal: input.signal
    });
    input.signal?.throwIfAborted();
  } catch (error: unknown) {
    try {
      await retireSpawnedTree();
      // Cleanup must finish even when the startup waiter has been cancelled.
      const released = await waitForPortRelease({ port: resolved.port, host, connect: input.connect });
      if (!released) throw new Error(`workbench backend port ${resolved.port} remains occupied`);
    } catch (retirementError: unknown) {
      const message = `workbench backend startup failed and its process tree remains registered: ${retirementError instanceof Error ? retirementError.message : String(retirementError)}`;
      await persistUnretiredStart(message);
      throw new Error(`${error instanceof Error ? error.message : String(error)}; ${message}`);
    }
    if (input.signal?.aborted) throw error;
    await writeState({
      ...stateWithoutReconciledBackendHandles(previous, reconciledDeadPids),
      desiredState: "closed", observedState: "failed", phase: "failed",
      backendPid: 0, backendLaunchPid: 0, spawnPid: 0,
      backendCreateTime: 0, backendExecutable: "",
      backendLaunchCreateTime: 0, backendLaunchExecutable: "",
      spawnCreateTime: 0, spawnExecutable: "",
      host, backendPort: resolved.port, port: resolved.port,
      failureMessage: error instanceof Error ? error.message : String(error),
      lifecycleWarning: "", lastReason: "electron_main_start_failed_retired",
      lastSource: "electron_main", updatedAt: isoNow(input.now)
    });
    throw error;
  }
  input.signal?.throwIfAborted();
  // The backend registration must point at the process that owns the port so
  // stop/graceful shutdown targets the real server. When the socket owner is
  // a verified managed backend distinct from the spawn pid (pythonw stub
  // delegation or an adopted same-project orphan), backendPid carries the
  // owner's identity while backendLaunchPid/spawnPid keep the launched
  // process's identity for job and tree retirement.
  const adoptedOwnerIdentity = backendOwner.ownerIdentity;
  const adoptedOwnerPid = adoptedOwnerIdentity
    && Math.trunc(Number(adoptedOwnerIdentity.pid)) === backendOwner.ownerPid
    && backendOwner.ownerPid > 0
    ? backendOwner.ownerPid
    : 0;
  const registrationFields: Record<string, unknown> = adoptedOwnerPid && adoptedOwnerIdentity
    ? {
        backendPid: adoptedOwnerPid,
        backendCreateTime: adoptedOwnerIdentity.createTime,
        backendExecutable: adoptedOwnerIdentity.executable,
        backendLaunchPid: spawnPid,
        spawnPid,
        ...(backendIdentity
          ? {
              backendLaunchCreateTime: backendIdentity.createTime,
              backendLaunchExecutable: backendIdentity.executable,
              spawnCreateTime: backendIdentity.createTime,
              spawnExecutable: backendIdentity.executable
            }
          : {})
      }
    : {
        backendPid: spawnPid,
        backendLaunchPid: spawnPid,
        spawnPid,
        ...(backendIdentity
          ? {
              backendCreateTime: backendIdentity.createTime,
              backendExecutable: backendIdentity.executable,
              backendLaunchCreateTime: backendIdentity.createTime,
              backendLaunchExecutable: backendIdentity.executable,
              spawnCreateTime: backendIdentity.createTime,
              spawnExecutable: backendIdentity.executable
            }
          : {})
      };
  await writeState({
    ...previous,
    schemaVersion: 1,
    desiredState: "open",
    observedState: "open",
    phase: "steady",
    // A settled lifecycle command must not carry a previous failure's
    // message; a stale failureMessage keeps the branch page in runtime.error.
    failureMessage: "",
    host,
    backendPort: resolved.port,
    port: resolved.port,
    url: `http://${host}:${resolved.port}`,
    ...registrationFields,
    portRelocationNote: resolved.note,
    lifecycleWarning: [
      deadHandleReconcileReasons.length > 0
        ? `${deadHandleReconcileReasons.join("; ")}; no process was terminated during reconciliation`
        : "",
      unretiredRegisteredNote,
      reusedDaemonRecordNote,
      browserHandleFalsification.note,
      backendOwner.note,
      ignoredStaleDaemonPid > 0
        ? `Ignored stale Runtime Manager daemon pid ${ignoredStaleDaemonPid} without a verifiable identity; no process was terminated.`
        : ""
    ].filter(Boolean).join("; "),
    lastReason: `electron_main_${operation.replace(/-/g, "_")}`,
    lastSource: "electron_main",
    pythonExecutable: spawned.pythonPath,
    updatedAt: isoNow(input.now)
  });
  if (!input.writeState) {
    await writeLauncherStateFile(launcherPortsPath(input.workspaceRoot), {
      schemaVersion: 1,
      backendPort: resolved.port,
      projectRoot: input.workspaceRoot,
      updatedAt: isoNow(input.now)
    }, input.signal);
  }
  return accepted(operation, commandId);
}
