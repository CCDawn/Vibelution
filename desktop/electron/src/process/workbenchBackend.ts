import { execFileSync, spawn as nodeSpawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  unlinkSync,
  writeFileSync
} from "node:fs";
import { dirname, join } from "node:path";

import { pythonBridgeEnv } from "./pythonBridgeEnv.js";
import { resolveLauncherRuntimeDir, resolveRuntimeManagerDir } from "../lifecycle/projectStoragePaths.js";
import { observeMainLineWorkbench, probeTcpConnect } from "../lifecycle/mainLine/observation.js";
import { waitForBackendHealthy } from "./workbenchBackendHealth.js";
import {
  collectRegisteredHandles,
  retireRegisteredHandles
} from "./workbenchBackendRetire.js";
import {
  blockLifecycleIfActiveWork,
  listActiveWorkRuns,
  type ActiveWorkRun
} from "./activeWorkGuard.js";
import type { WorkbenchLifecycleOperation, WorkbenchLifecycleResult } from "./workbenchLifecycle.js";
import type { MainLineQueuedCommand } from "../lifecycle/mainLine/commandQueue.js";

export const DEFAULT_WORKBENCH_HOST = "127.0.0.1";
export const DEFAULT_WORKBENCH_PORT = 8000;
export const WEB_WORKBENCH_SCRIPT = ["scripts", "web_workbench.py"] as const;
export const RUNNING_CODE_FINGERPRINT_RELATIVE = [".runtime", "running-code-fingerprint.json"] as const;
export const FRONTEND_BUILD_TIMEOUT_MS = 120_000;

export type WorkbenchFrontendBuildErrorCode =
  | "frontend_build_timeout"
  | "frontend_build_aborted"
  | "frontend_build_failed";

export type WorkbenchFrontendBuildPhase = "tsc" | "vite";

export class WorkbenchFrontendBuildError extends Error {
  readonly code: WorkbenchFrontendBuildErrorCode;
  readonly phase: WorkbenchFrontendBuildPhase;
  readonly command: string;
  readonly args: string[];
  readonly timeoutMs: number;
  readonly cause?: unknown;

  constructor(
    code: WorkbenchFrontendBuildErrorCode,
    message: string,
    options: {
      phase: WorkbenchFrontendBuildPhase;
      command: string;
      args: string[];
      timeoutMs: number;
      cause?: unknown;
    }
  ) {
    super(message);
    this.name = "WorkbenchFrontendBuildError";
    this.code = code;
    this.phase = options.phase;
    this.command = options.command;
    this.args = [...options.args];
    this.timeoutMs = options.timeoutMs;
    this.cause = options.cause;
  }
}

export type WorkbenchFrontendBuildChild = {
  kill: (signal?: NodeJS.Signals) => boolean;
  once(event: "error", listener: (error: Error) => void): unknown;
  once(event: "close", listener: (code: number | null, signal: NodeJS.Signals | null) => void): unknown;
};

export type WorkbenchFrontendBuildSpawn = (
  command: string,
  args: string[],
  options: {
    cwd: string;
    env: NodeJS.ProcessEnv;
    windowsHide: boolean;
    stdio: ["ignore", "ignore", "ignore"];
  }
) => WorkbenchFrontendBuildChild;

export type WorkbenchBackendSpawnChild = {
  pid?: number;
  killed?: boolean;
  exitCode?: number | null;
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
    stdio: ["ignore", number, number] | ["ignore", "ignore", "ignore"];
  }
) => WorkbenchBackendSpawnChild;

export type WorkbenchBackendState = Record<string, unknown>;

export type ExecuteMainLineWorkbenchInput = {
  workspaceRoot: string;
  pythonPath: string;
  operation: WorkbenchLifecycleOperation;
  command: MainLineQueuedCommand;
  signal?: AbortSignal;
  spawnImpl?: WorkbenchBackendSpawn;
  fileExists?: (path: string) => boolean;
  readState?: () => WorkbenchBackendState;
  writeState?: (state: WorkbenchBackendState) => void;
  listActiveWork?: () => ActiveWorkRun[];
  ensureFrontend?: (input: { force: boolean; signal?: AbortSignal }) => Promise<void>;
  now?: () => string;
  connect?: (port: number, host: string) => Promise<boolean>;
  fetchHealth?: (url: string) => Promise<{ status: number }>;
  pidAlive?: (pid: number) => boolean;
  killPid?: (pid: number) => void;
  readDaemonPid?: (workspaceRoot: string) => number;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function resolveNoConsolePython(
  pythonPath: string,
  fileExists: (path: string) => boolean = existsSync
): string {
  const raw = String(pythonPath || "").trim();
  if (!raw) {
    return "";
  }
  if (raw.toLowerCase().endsWith("pythonw.exe")) {
    return raw;
  }
  if (raw.toLowerCase().endsWith("python.exe")) {
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
  host?: string;
  dataHome?: string;
  configHome?: string;
  controlPort?: number;
  allowDirty?: boolean;
  allowNonMain?: boolean;
  extra?: NodeJS.ProcessEnv;
}): NodeJS.ProcessEnv {
  const env = pythonBridgeEnv({
    ...process.env,
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

export function readDaemonPid(workspaceRoot: string): number {
  try {
    const raw = readFileSync(runtimeManagerDaemonPidPath(workspaceRoot), "utf8").trim();
    const pid = Number(raw.split(/\s+/)[0] || 0);
    return Number.isFinite(pid) && pid > 0 ? Math.trunc(pid) : 0;
  } catch {
    return 0;
  }
}

export function readLauncherStateFile(path: string): WorkbenchBackendState {
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as unknown;
    return isRecord(parsed) ? parsed : {};
  } catch {
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

export function runningCodeFingerprintPath(workspaceRoot: string): string {
  return join(workspaceRoot, ...RUNNING_CODE_FINGERPRINT_RELATIVE);
}

export function sameProjectRoot(left: string, right: string): boolean {
  const normalize = (value: string): string => value.trim().replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  const a = normalize(left);
  const b = normalize(right);
  return Boolean(a) && a === b;
}

export function readRunningCodeFingerprint(workspaceRoot: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(readFileSync(runningCodeFingerprintPath(workspaceRoot), "utf8")) as unknown;
    return isRecord(parsed) ? parsed : null;
  } catch {
    return null;
  }
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

export function writeLauncherStateFile(path: string, state: WorkbenchBackendState): void {
  mkdirSync(dirname(path), { recursive: true });
  // State is published by more than one lifecycle writer. A fixed sibling
  // temp name lets concurrent writers overwrite each other's in-progress
  // document before either rename, which can publish torn or stale JSON.
  const tmp = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    writeFileSync(tmp, `${JSON.stringify(state, null, 2)}\n`, "utf8");
    renameSync(tmp, path);
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

export async function resolveBindableWorkbenchPort(input: {
  preferred: number;
  host?: string;
  connect?: (port: number, host: string) => Promise<boolean>;
}): Promise<{ port: number; note: string }> {
  const host = input.host?.trim() || DEFAULT_WORKBENCH_HOST;
  const connect = input.connect ?? ((port, nextHost) => probeTcpConnect(port, nextHost));
  const preferred = Math.trunc(input.preferred) > 0 ? Math.trunc(input.preferred) : DEFAULT_WORKBENCH_PORT;
  if (!(await connect(preferred, host))) {
    return { port: preferred, note: "" };
  }
  for (let offset = 1; offset <= 48; offset += 1) {
    const candidate = preferred + offset;
    if (candidate >= 65536) {
      continue;
    }
    if (!(await connect(candidate, host))) {
      return {
        port: candidate,
        note: `port ${preferred} occupied; auto-bound this project to ${candidate}`
      };
    }
  }
  throw new Error(`No free workbench backend port found near ${preferred}`);
}

export function shouldRebuildFrontend(input: { distExists: boolean; force: boolean }): boolean {
  return input.force || !input.distExists;
}

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

export function resolveNodeExecutable(
  fileExists: (path: string) => boolean,
  execPath = String(process.execPath || ""),
  envNode = String(process.env.NODE || "")
): string {
  const explicit = envNode.trim();
  if (explicit && fileExists(explicit)) {
    return explicit;
  }
  const resolvedExec = execPath.trim();
  const execName = resolvedExec.replace(/\\/g, "/").toLowerCase();
  const electronLike = execName.endsWith("/electron.exe")
    || execName.endsWith("/electron")
    || execName.endsWith("/vibelution.exe")
    || execName.includes("/electron/");
  if (resolvedExec && !electronLike && fileExists(resolvedExec)) {
    return resolvedExec;
  }
  const localAppData = String(process.env.LOCALAPPDATA || "").trim();
  const programFiles = String(process.env.ProgramFiles || "").trim();
  const programFilesX86 = String(process.env["ProgramFiles(x86)"] || "").trim();
  const candidates = [
    ...(localAppData ? [join(localAppData, "Programs", "nodejs", "node.exe")] : []),
    ...(programFiles ? [join(programFiles, "nodejs", "node.exe")] : []),
    ...(programFilesX86 ? [join(programFilesX86, "nodejs", "node.exe")] : [])
  ];
  for (const candidate of candidates) {
    if (fileExists(candidate)) {
      return candidate;
    }
  }
  return "node";
}

export async function ensureFrontendBuild(input: {
  workspaceRoot: string;
  force: boolean;
  fileExists?: (path: string) => boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
  spawnImpl?: WorkbenchFrontendBuildSpawn;
}): Promise<void> {
  const fileExists = input.fileExists ?? existsSync;
  const distIndex = join(input.workspaceRoot, "web", "dist", "index.html");
  if (!shouldRebuildFrontend({ distExists: fileExists(distIndex), force: input.force })) {
    return;
  }
  const webDir = join(input.workspaceRoot, "web");
  const tsc = join(webDir, "node_modules", "typescript", "bin", "tsc");
  const vite = join(webDir, "node_modules", "vite", "bin", "vite.js");
  const node = resolveNodeExecutable(fileExists);
  await runWaitable(node, [tsc, "-b"], webDir, {
    phase: "tsc",
    signal: input.signal,
    timeoutMs: input.timeoutMs,
    spawnImpl: input.spawnImpl
  });
  await runWaitable(node, [vite, "build"], webDir, {
    phase: "vite",
    signal: input.signal,
    timeoutMs: input.timeoutMs,
    spawnImpl: input.spawnImpl
  });
}

function defaultEnsureFrontend(
  workspaceRoot: string,
  options: { force: boolean; signal?: AbortSignal },
  fileExists: (path: string) => boolean
): Promise<void> {
  return ensureFrontendBuild({
    workspaceRoot,
    force: options.force,
    signal: options.signal,
    fileExists
  });
}

export function runWaitable(
  command: string,
  args: string[],
  cwd: string,
  options: {
    phase?: WorkbenchFrontendBuildPhase;
    signal?: AbortSignal;
    timeoutMs?: number;
    spawnImpl?: WorkbenchFrontendBuildSpawn;
  } = {}
): Promise<void> {
  const phase = options.phase ?? "tsc";
  const timeoutMs = options.timeoutMs ?? FRONTEND_BUILD_TIMEOUT_MS;
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return Promise.reject(new RangeError("frontend build timeoutMs must be a positive finite number"));
  }
  const roundedTimeoutMs = Math.max(1, Math.round(timeoutMs));
  const spawnImpl = options.spawnImpl ?? (nodeSpawn as unknown as WorkbenchFrontendBuildSpawn);
  const commandLabel = [command, ...args].join(" ");
  const createError = (
    code: WorkbenchFrontendBuildErrorCode,
    detail: string,
    cause?: unknown
  ): WorkbenchFrontendBuildError => new WorkbenchFrontendBuildError(
    code,
    `frontend ${phase} ${detail}: ${commandLabel}`,
    {
      phase,
      command,
      args,
      timeoutMs: roundedTimeoutMs,
      cause
    }
  );

  if (options.signal?.aborted) {
    return Promise.reject(createError("frontend_build_aborted", "was aborted before spawn"));
  }

  return new Promise((resolve, reject) => {
    let child: WorkbenchFrontendBuildChild | null = null;
    let settled = false;
    let timeoutTimer: ReturnType<typeof setTimeout> | null = null;

    const cleanup = (): void => {
      if (timeoutTimer !== null) {
        clearTimeout(timeoutTimer);
        timeoutTimer = null;
      }
      options.signal?.removeEventListener("abort", onAbort);
    };
    const resolveOnce = (): void => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolve();
    };
    const rejectOnce = (error: WorkbenchFrontendBuildError): void => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      reject(error);
    };
    const terminate = (): void => {
      try {
        child?.kill();
      } catch {
        // Keep the timeout/abort/failure as the authoritative error.
      }
    };
    const onAbort = (): void => {
      terminate();
      rejectOnce(createError("frontend_build_aborted", "was aborted"));
    };

    try {
      child = spawnImpl(command, args, {
        cwd,
        windowsHide: true,
        stdio: ["ignore", "ignore", "ignore"],
        env: pythonBridgeEnv()
      });
    } catch (error: unknown) {
      rejectOnce(createError("frontend_build_failed", "failed to start", error));
      return;
    }

    child.once("error", (error) => {
      rejectOnce(createError("frontend_build_failed", "failed to start or communicate with the child process", error));
    });
    child.once("close", (code, signal) => {
      if (code === 0) {
        resolveOnce();
        return;
      }
      const status = code === null ? `signal ${signal ?? "unknown"}` : `code ${code}`;
      rejectOnce(createError("frontend_build_failed", `exited with ${status}`));
    });
    options.signal?.addEventListener("abort", onAbort, { once: true });
    timeoutTimer = setTimeout(() => {
      terminate();
      rejectOnce(createError("frontend_build_timeout", `timed out after ${roundedTimeoutMs}ms`));
    }, roundedTimeoutMs);
    if (options.signal?.aborted) {
      onAbort();
    }
  });
}

export type SpawnedWorkbenchBackend = {
  child: WorkbenchBackendSpawnChild;
  pythonPath: string;
  args: string[];
  spawnError: () => Error | null;
};

export function spawnWorkbenchBackend(input: {
  workspaceRoot: string;
  pythonPath: string;
  port: number;
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
}): SpawnedWorkbenchBackend {
  const host = input.host?.trim() || DEFAULT_WORKBENCH_HOST;
  const fileExists = input.fileExists ?? existsSync;
  const pythonPath = resolveNoConsolePython(input.pythonPath, fileExists);
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
  let stdio: ["ignore", number, number] | ["ignore", "ignore", "ignore"] = ["ignore", "ignore", "ignore"];
  let stdoutFd: number | undefined;
  let stderrFd: number | undefined;
  if (!input.spawnImpl) {
    const runtimeDir = resolveLauncherRuntimeDir(input.workspaceRoot);
    mkdirSync(runtimeDir, { recursive: true });
    stdoutFd = openSync(join(runtimeDir, "backend.stdout.log"), "a");
    stderrFd = openSync(join(runtimeDir, "backend.stderr.log"), "a");
    stdio = ["ignore", stdoutFd, stderrFd];
  }
  try {
    const child = spawnImpl(pythonPath, args, {
      cwd: input.workspaceRoot,
      env,
      windowsHide: true,
      detached: true,
      stdio
    });
    let spawnError: Error | null = null;
    child.once?.("error", (error) => {
      spawnError = error instanceof Error ? error : new Error(String(error));
    });
    child.unref?.();
    return { child, pythonPath, args, spawnError: () => spawnError };
  } finally {
    if (stdoutFd !== undefined) {
      closeSync(stdoutFd);
    }
    if (stderrFd !== undefined) {
      closeSync(stderrFd);
    }
  }
}

export async function executeMainLineWorkbench(
  input: ExecuteMainLineWorkbenchInput
): Promise<WorkbenchLifecycleResult> {
  input.signal?.throwIfAborted();
  const fileExists = input.fileExists ?? existsSync;
  const statePath = launcherStatePath(input.workspaceRoot);
  const readState = input.readState ?? (() => readLauncherStateFile(statePath));
  const writeState = input.writeState ?? ((state) => writeLauncherStateFile(statePath, state));
  const host = DEFAULT_WORKBENCH_HOST;
  const operation = input.operation;
  const commandId = input.command.commandId;

  if (operation === "stop" || operation === "force-stop" || operation === "shutdown") {
    if (operation === "stop") {
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
    const previous = readState();
    const port = preferredWorkbenchPort({ workspaceRoot: input.workspaceRoot, state: previous });
    const extraPids = operation === "shutdown"
      ? [(input.readDaemonPid ?? readDaemonPid)(input.workspaceRoot)]
      : [];
    await retireRegisteredHandles({
      pids: collectRegisteredHandles(previous, extraPids),
      port,
      host,
      signal: input.signal,
      pidAlive: input.pidAlive,
      killPid: input.killPid,
      connect: input.connect
    });
    writeState({
      ...previous,
      desiredState: "closed",
      observedState: "closed",
      phase: "steady",
      backendPid: 0,
      backendLaunchPid: 0,
      browserLaunchPid: 0,
      browserWindowPid: 0,
      lastReason: `electron_main_${operation.replace("-", "_")}`,
      lastSource: "electron_main",
      updatedAt: isoNow(input.now)
    });
    return accepted(operation, commandId);
  }

  if (operation === "restart") {
    const blocked = blockLifecycleIfActiveWork(
      "restart",
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

  await (input.ensureFrontend ?? ((opts) => defaultEnsureFrontend(input.workspaceRoot, opts, fileExists)))({
    force: operation === "rebuild-and-start",
    signal: input.signal
  });

  const previous = readState();
  const preferred = preferredWorkbenchPort({ workspaceRoot: input.workspaceRoot, state: previous });
  await retireRegisteredHandles({
    pids: collectRegisteredHandles(previous),
    port: preferred,
    host,
    signal: input.signal,
    pidAlive: input.pidAlive,
    killPid: input.killPid,
    connect: input.connect
  });
  const resolved = await resolveBindableWorkbenchPort({
    preferred,
    host,
    connect: input.connect
  });
  const spawned = spawnWorkbenchBackend({
    workspaceRoot: input.workspaceRoot,
    pythonPath: input.pythonPath,
    port: resolved.port,
    host,
    spawnImpl: input.spawnImpl,
    fileExists
  });
  const spawnPid = Number(spawned.child.pid || 0);
  try {
    await waitForBackendHealthy({
      port: resolved.port,
      host,
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
  } catch (error: unknown) {
    if (spawnPid > 0) {
      if (input.killPid) {
        input.killPid(spawnPid);
      } else {
        spawned.child.kill();
      }
    }
    throw error;
  }
  writeState({
    ...previous,
    schemaVersion: 1,
    desiredState: "open",
    observedState: "open",
    phase: "steady",
    host,
    backendPort: resolved.port,
    port: resolved.port,
    url: `http://${host}:${resolved.port}`,
    backendPid: spawnPid,
    backendLaunchPid: spawnPid,
    portRelocationNote: resolved.note,
    lastReason: `electron_main_${operation.replace(/-/g, "_")}`,
    lastSource: "electron_main",
    pythonExecutable: spawned.pythonPath,
    updatedAt: isoNow(input.now)
  });
  if (!input.writeState) {
    writeLauncherStateFile(launcherPortsPath(input.workspaceRoot), {
      schemaVersion: 1,
      backendPort: resolved.port,
      projectRoot: input.workspaceRoot,
      updatedAt: isoNow(input.now)
    });
  }
  return accepted(operation, commandId);
}
