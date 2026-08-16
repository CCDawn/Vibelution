import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

import type { TrayBranchInstance } from "./desktopTray.js";

export const TRAY_RESTART_ALL_PENDING_FILENAME = "tray-restart-all-pending.json";

export type TrayRestartAllPending = {
  schemaVersion: 1;
  capturedAt: string;
  instanceIds: string[];
  interruptedActiveWorkCount: number;
  shellRefreshScheduled: boolean;
};

export type TrayRestartAllRestoreResult = {
  restored: string[];
  failed: Array<{ instanceId: string; message: string }>;
  skipped: string[];
};

export function trayRestartAllPendingPath(workspaceRoot: string): string {
  return resolve(workspaceRoot, ".runtime", "launcher", TRAY_RESTART_ALL_PENDING_FILENAME);
}

export function captureRunningInstanceIds(instances: TrayBranchInstance[]): string[] {
  const running = instances.filter((item) => item.stoppable).map((item) => item.id.trim()).filter(Boolean);
  return Array.from(new Set(running));
}

export function writeTrayRestartAllPending(
  workspaceRoot: string,
  payload: Omit<TrayRestartAllPending, "schemaVersion" | "capturedAt"> & { capturedAt?: string }
): TrayRestartAllPending {
  const path = trayRestartAllPendingPath(workspaceRoot);
  mkdirSync(dirname(path), { recursive: true });
  const record: TrayRestartAllPending = {
    schemaVersion: 1,
    capturedAt: payload.capturedAt ?? new Date().toISOString(),
    instanceIds: Array.from(new Set(payload.instanceIds.map((item) => String(item || "").trim()).filter(Boolean))),
    interruptedActiveWorkCount: Math.max(0, Math.round(payload.interruptedActiveWorkCount || 0)),
    shellRefreshScheduled: Boolean(payload.shellRefreshScheduled)
  };
  writeFileSync(path, JSON.stringify(record, null, 2), "utf8");
  return record;
}

export function readTrayRestartAllPending(workspaceRoot: string): TrayRestartAllPending | null {
  const path = trayRestartAllPendingPath(workspaceRoot);
  if (!existsSync(path)) {
    return null;
  }
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as TrayRestartAllPending;
    if (!parsed || parsed.schemaVersion !== 1 || !Array.isArray(parsed.instanceIds)) {
      return null;
    }
    return {
      schemaVersion: 1,
      capturedAt: String(parsed.capturedAt || ""),
      instanceIds: parsed.instanceIds.map((item) => String(item || "").trim()).filter(Boolean),
      interruptedActiveWorkCount: Math.max(0, Number(parsed.interruptedActiveWorkCount || 0)),
      shellRefreshScheduled: Boolean(parsed.shellRefreshScheduled)
    };
  } catch {
    return null;
  }
}

export function clearTrayRestartAllPending(workspaceRoot: string): void {
  const path = trayRestartAllPendingPath(workspaceRoot);
  if (!existsSync(path)) {
    return;
  }
  try {
    unlinkSync(path);
  } catch {
    // Best-effort cleanup only.
  }
}

export function summarizeTrayRestartAllRestore(result: TrayRestartAllRestoreResult): string {
  const parts: string[] = [];
  if (result.restored.length) {
    parts.push(`已恢复 ${result.restored.length} 个工作区`);
  }
  if (result.failed.length) {
    parts.push(`${result.failed.length} 个恢复失败`);
  }
  if (!parts.length) {
    return "全部重启完成。";
  }
  return `全部重启完成：${parts.join("，")}。`;
}
