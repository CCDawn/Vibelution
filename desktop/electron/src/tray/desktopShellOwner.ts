import { existsSync, mkdirSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { resolveDesktopShellOwnerPaths } from "../lifecycle/projectStoragePaths.js";

export const DESKTOP_SHELL_OWNER_RELATIVE_PATH = ".runtime/launcher/desktop_shell_owner.json";
export const DESKTOP_SHELL_OWNER_KIND = "electron" as const;
const CREATE_TIME_TOLERANCE_SECONDS = 2;

export type DesktopShellOwnerIdentity = {
  pid: number;
  createTime: number;
  executable: string;
};

export type DesktopShellOwnerRecord = {
  schemaVersion: 1;
  owner: "electron" | "winforms";
  pid: number;
  createTime?: number;
  executable?: string;
  updatedAt?: string;
};

export function captureElectronOwnerIdentity(
  pid = process.pid,
  executable = process.execPath,
  nowSeconds = Date.now() / 1000,
  uptimeSeconds = process.uptime(),
): DesktopShellOwnerIdentity {
  return {
    pid,
    createTime: nowSeconds - uptimeSeconds,
    executable,
  };
}

export function desktopShellOwnerPath(workspaceRoot: string): string {
  const paths = resolveDesktopShellOwnerPaths(workspaceRoot);
  return paths.canonical ?? paths.checkout;
}

export function readDesktopShellOwner(workspaceRoot: string): DesktopShellOwnerRecord | null {
  const paths = resolveDesktopShellOwnerPaths(workspaceRoot);
  const candidates = [paths.canonical, paths.checkout].filter((path): path is string => Boolean(path));
  for (const path of candidates) {
    if (paths.canonical && path === paths.canonical && !existsSync(path)) {
      continue;
    }
    const record = readOwnerFile(path);
    if (record) {
      return record;
    }
  }
  return null;
}

export function claimElectronDesktopShellOwner(
  workspaceRoot: string,
  identityOrPid: number | DesktopShellOwnerIdentity = process.pid,
): DesktopShellOwnerRecord | null {
  const identity = normalizeIdentity(identityOrPid);
  const paths = resolveDesktopShellOwnerPaths(workspaceRoot);
  if (!paths.canonical) {
    return null;
  }
  const current = readDesktopShellOwner(workspaceRoot);
  if (current && !canReplaceOwner(current, identity)) {
    return current;
  }
  const record: DesktopShellOwnerRecord = {
    schemaVersion: 1,
    owner: DESKTOP_SHELL_OWNER_KIND,
    pid: identity.pid,
    ...(identity.createTime > 0 ? { createTime: identity.createTime } : {}),
    ...(identity.executable ? { executable: identity.executable } : {}),
    updatedAt: new Date().toISOString(),
  };
  atomicWriteJson(paths.canonical, record);
  return record;
}

export function releaseElectronDesktopShellOwner(
  workspaceRoot: string,
  identityOrPid: number | DesktopShellOwnerIdentity = process.pid,
): void {
  const identity = normalizeIdentity(identityOrPid);
  const paths = resolveDesktopShellOwnerPaths(workspaceRoot);
  const current = readDesktopShellOwner(workspaceRoot);
  if (!current || !ownerIdentityMatches(current, identity)) {
    return;
  }
  for (const path of [paths.canonical, paths.checkout]) {
    if (!path) {
      continue;
    }
    try {
      unlinkSync(path);
    } catch {
      // Missing owner file is not fatal during quit.
    }
  }
}

function normalizeIdentity(identityOrPid: number | DesktopShellOwnerIdentity): DesktopShellOwnerIdentity {
  if (typeof identityOrPid === "number") {
    return identityOrPid === process.pid
      ? captureElectronOwnerIdentity(identityOrPid)
      : { pid: identityOrPid, createTime: 0, executable: "" };
  }
  return {
    pid: Number(identityOrPid.pid) || 0,
    createTime: Number(identityOrPid.createTime) || 0,
    executable: String(identityOrPid.executable || "").trim(),
  };
}

function canReplaceOwner(current: DesktopShellOwnerRecord, next: DesktopShellOwnerIdentity): boolean {
  if (ownerIdentityMatches(current, next)) {
    return true;
  }
  if (!isPidAlive(current.pid)) {
    return true;
  }
  if (!hasCompleteIdentity(current)) {
    return false;
  }
  return current.pid === next.pid && !identitiesAlign(current, next);
}

function isPidAlive(pid: number): boolean {
  if (pid <= 0) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function ownerIdentityMatches(current: DesktopShellOwnerRecord, identity: DesktopShellOwnerIdentity): boolean {
  if (current.owner !== "electron" || Number(current.pid) !== Number(identity.pid)) {
    return false;
  }
  if (hasCompleteIdentity(current)) {
    return identitiesAlign(current, identity);
  }
  return identity.pid > 0;
}

function hasCompleteIdentity(record: DesktopShellOwnerRecord): boolean {
  return Number(record.createTime) > 0 && Boolean(String(record.executable || "").trim());
}

function identitiesAlign(current: DesktopShellOwnerRecord, identity: DesktopShellOwnerIdentity): boolean {
  if (identity.createTime <= 0 || !identity.executable) {
    return false;
  }
  if (Math.abs(Number(current.createTime) - identity.createTime) > CREATE_TIME_TOLERANCE_SECONDS) {
    return false;
  }
  return normalizeExecutable(current.executable) === normalizeExecutable(identity.executable);
}

function normalizeExecutable(value: unknown): string {
  return String(value || "").trim().replace(/\\/g, "/").toLowerCase();
}

function readOwnerFile(path: string): DesktopShellOwnerRecord | null {
  try {
    const payload = JSON.parse(readFileSync(path, "utf8")) as unknown;
    if (typeof payload !== "object" || payload === null) {
      return null;
    }
    const record = payload as DesktopShellOwnerRecord;
    const owner = record.owner === "electron" || record.owner === "winforms" ? record.owner : "";
    const pid = Number(record.pid);
    if (!owner || !Number.isFinite(pid) || pid <= 0) {
      return null;
    }
    return {
      schemaVersion: 1,
      owner,
      pid,
      ...(Number(record.createTime) > 0 ? { createTime: Number(record.createTime) } : {}),
      ...(String(record.executable || "").trim() ? { executable: String(record.executable).trim() } : {}),
      ...(String(record.updatedAt || "").trim() ? { updatedAt: String(record.updatedAt).trim() } : {}),
    };
  } catch {
    return null;
  }
}

function atomicWriteJson(path: string, payload: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  try {
    renameSync(temporary, path);
  } catch {
    try {
      unlinkSync(path);
    } catch {
      // Replace by deleting the previous owner file, then moving the temp file.
    }
    renameSync(temporary, path);
  }
}
