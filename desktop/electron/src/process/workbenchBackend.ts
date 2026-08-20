import { spawn as nodeSpawn } from "node:child_process";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { pythonBridgeEnv } from "./pythonBridgeEnv.js";
import { resolveLauncherRuntimeDir, resolveRuntimeManagerDir } from "../lifecycle/projectStoragePaths.js";
import { probeTcpConnect } from "../lifecycle/mainLine/observation.js";
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

export type WorkbenchBackendSpawnChild = {
  pid?: number;
  killed?: boolean;
  exitCode?: number | null;
  unref?: () => void;
  kill: (signal?: NodeJS.Signals) => boolean;
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
  ensureFrontend?: (input: { force: boolean }) => Promise<void>;
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

export function writeLauncherStateFile(path: string, state: WorkbenchBackendState): void {
  mkdirSync(dirname(path), { recursive: true });
  const tmp = `${path}.tmp`;
  writeFileSync(tmp, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  renameSync(tmp, path);
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

async function defaultEnsureFrontend(workspaceRoot: string, force: boolean, fileExists: (path: string) => boolean): Promise<void> {
  const distIndex = join(workspaceRoot, "web", "dist", "index.html");
  if (!shouldRebuildFrontend({ distExists: fileExists(distIndex), force })) {
    return;
  }
  const webDir = join(workspaceRoot, "web");
  const tsc = join(webDir, "node_modules", "typescript", "bin", "tsc");
  const vite = join(webDir, "node_modules", "vite", "bin", "vite.js");
  const node = resolveNodeExecutable(fileExists);
  await runWaitable(node, [tsc, "-b"], webDir);
  await runWaitable(node, [vite, "build"], webDir);
}

function runWaitable(command: string, args: string[], cwd: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = nodeSpawn(command, args, {
      cwd,
      windowsHide: true,
      stdio: "ignore",
      env: pythonBridgeEnv()
    });
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${command} ${args.join(" ")} exited with code ${code ?? "null"}`));
    });
  });
}

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
}): { child: WorkbenchBackendSpawnChild; pythonPath: string; args: string[] } {
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
    child.unref?.();
    return { child, pythonPath, args };
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

  await (input.ensureFrontend ?? ((opts) => defaultEnsureFrontend(input.workspaceRoot, opts.force, fileExists)))({
    force: operation === "rebuild-and-start"
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
      childAlive: () => spawned.child.exitCode == null && spawned.child.killed !== true,
      connect: input.connect,
      fetchHealth: input.fetchHealth
    });
  } catch (error: unknown) {
    if (spawnPid > 0) {
      input.killPid?.(spawnPid) ?? spawned.child.kill();
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
