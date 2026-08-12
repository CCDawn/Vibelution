import { mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

export const DESKTOP_SHELL_OWNER_RELATIVE_PATH = ".runtime/launcher/desktop_shell_owner.json";
export const DESKTOP_SHELL_OWNER_KIND = "electron" as const;

export type DesktopShellOwnerRecord = {
  schemaVersion: 1;
  owner: "electron" | "winforms";
  pid: number;
};

export function desktopShellOwnerPath(workspaceRoot: string): string {
  return resolve(workspaceRoot, DESKTOP_SHELL_OWNER_RELATIVE_PATH);
}

export function claimElectronDesktopShellOwner(workspaceRoot: string, pid = process.pid): DesktopShellOwnerRecord {
  const path = desktopShellOwnerPath(workspaceRoot);
  mkdirSync(dirname(path), { recursive: true });
  const record: DesktopShellOwnerRecord = {
    schemaVersion: 1,
    owner: DESKTOP_SHELL_OWNER_KIND,
    pid
  };
  writeFileSync(path, `${JSON.stringify(record, null, 2)}\n`, "utf8");
  return record;
}

export function releaseElectronDesktopShellOwner(workspaceRoot: string, pid = process.pid): void {
  const path = desktopShellOwnerPath(workspaceRoot);
  try {
    const current = JSON.parse(readFileSync(path, "utf8")) as DesktopShellOwnerRecord;
    if (current.owner !== "electron" || Number(current.pid) !== Number(pid)) {
      return;
    }
    unlinkSync(path);
  } catch {
    // Missing or unreadable owner file is not fatal during quit.
  }
}
