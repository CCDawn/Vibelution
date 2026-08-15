import { resolve } from "node:path";

import { runPythonJsonBridge, type PythonJsonBridgeSpawn } from "./pythonJsonBridge.js";

const REFRESH_BEFORE_LIFECYCLE = new Set(["start", "restart", "rebuild-and-start"]);
const FIRST_INSTANCE_LIFECYCLE = new Set(["start", "stop", "force-stop", "restart", "rebuild-and-start", "open"]);

export type DesktopShellStatus = {
  schemaVersion: 1;
  stale: boolean;
  reason: string;
  packagedElectronTree?: string;
  currentElectronTree?: string;
  packagedExe?: string;
  sourceNewerThanAsar?: boolean;
};

export type DesktopShellRefreshSchedule = {
  schemaVersion: 1;
  scheduled: boolean;
  helperPid: number;
  waitPid: number;
  thenLifecycle: string;
};

export function decidePackagedDesktopShellRefresh(input: {
  isPackaged: boolean;
  smoke: boolean;
  stale: boolean;
}): "skip" | "refresh" {
  if (!input.isPackaged || input.smoke || !input.stale) {
    return "skip";
  }
  return "refresh";
}

export function decideLauncherShellRestart(input: {
  isPackaged: boolean;
  stale: boolean;
}): "relaunch" | "rebuild-and-exit" {
  if (input.isPackaged && input.stale) {
    return "rebuild-and-exit";
  }
  return "relaunch";
}

export function thenLifecycleFromDesktopCli(input: {
  lifecycleCommand: string;
  openWorkbench: boolean;
}): string {
  const command = String(input.lifecycleCommand || "").trim().toLowerCase();
  if (FIRST_INSTANCE_LIFECYCLE.has(command)) {
    return command;
  }
  if (input.openWorkbench) {
    return "open";
  }
  return "";
}

export function shouldRefreshBeforeLifecycle(
  operation: string,
  input: { isPackaged: boolean; stale: boolean }
): boolean {
  return Boolean(input.isPackaged && input.stale && REFRESH_BEFORE_LIFECYCLE.has(String(operation || "").trim().toLowerCase()));
}

export function parseDesktopShellStatus(raw: string): DesktopShellStatus {
  const parsed = JSON.parse(raw) as DesktopShellStatus;
  if (!parsed || parsed.schemaVersion !== 1 || typeof parsed.stale !== "boolean") {
    throw new Error("invalid desktop shell status");
  }
  return {
    schemaVersion: 1,
    stale: Boolean(parsed.stale),
    reason: String(parsed.reason || ""),
    ...(typeof parsed.packagedElectronTree === "string" ? { packagedElectronTree: parsed.packagedElectronTree } : {}),
    ...(typeof parsed.currentElectronTree === "string" ? { currentElectronTree: parsed.currentElectronTree } : {}),
    ...(typeof parsed.packagedExe === "string" ? { packagedExe: parsed.packagedExe } : {}),
    ...(typeof parsed.sourceNewerThanAsar === "boolean" ? { sourceNewerThanAsar: parsed.sourceNewerThanAsar } : {})
  };
}

export function parseDesktopShellRefreshSchedule(raw: string): DesktopShellRefreshSchedule {
  const parsed = JSON.parse(raw) as DesktopShellRefreshSchedule;
  if (!parsed || parsed.schemaVersion !== 1 || parsed.scheduled !== true) {
    throw new Error("invalid desktop shell refresh schedule");
  }
  return {
    schemaVersion: 1,
    scheduled: true,
    helperPid: Number(parsed.helperPid || 0),
    waitPid: Number(parsed.waitPid || 0),
    thenLifecycle: String(parsed.thenLifecycle || "")
  };
}

export async function inspectDesktopShell(input: {
  workspaceRoot: string;
  pythonPath: string;
  spawnImpl?: PythonJsonBridgeSpawn;
}): Promise<DesktopShellStatus> {
  const raw = await runPythonJsonBridge({
    pythonPath: input.pythonPath,
    args: desktopShellBridgeArgs(input.workspaceRoot, input.pythonPath, "desktop-shell-status"),
    cwd: input.workspaceRoot,
    spawnImpl: input.spawnImpl,
    failureLabel: "desktop shell status"
  });
  return parseDesktopShellStatus(raw);
}

export async function scheduleDesktopShellRefresh(input: {
  workspaceRoot: string;
  pythonPath: string;
  waitPid: number;
  thenLifecycle?: string;
  spawnImpl?: PythonJsonBridgeSpawn;
}): Promise<DesktopShellRefreshSchedule> {
  const extra = ["--wait-pid", String(Math.max(0, Math.round(input.waitPid)))];
  const lifecycle = String(input.thenLifecycle || "").trim().toLowerCase();
  if (lifecycle) {
    extra.push("--then-lifecycle", lifecycle);
  }
  const raw = await runPythonJsonBridge({
    pythonPath: input.pythonPath,
    args: desktopShellBridgeArgs(input.workspaceRoot, input.pythonPath, "schedule-desktop-shell-refresh", extra),
    cwd: input.workspaceRoot,
    spawnImpl: input.spawnImpl,
    failureLabel: "desktop shell refresh schedule"
  });
  return parseDesktopShellRefreshSchedule(raw);
}

function desktopShellBridgeArgs(
  workspaceRoot: string,
  pythonPath: string,
  action: string,
  extra: string[] = []
): string[] {
  return [
    resolve(workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
    "--action",
    action,
    "--output",
    "json",
    "--workspace",
    workspaceRoot,
    "--python-exe",
    pythonPath,
    "--no-browser",
    ...extra
  ];
}
