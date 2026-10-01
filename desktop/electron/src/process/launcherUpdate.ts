import type { OrchestratedLifecycleResult } from "../protocol/launcherIpcHost.js";
import type { ActiveWorkStatus } from "../shutdown/shutdownCoordinator.js";
import { ACTIVE_WORK_BLOCK_MESSAGE_RESTART } from "./activeWorkGuard.js";
import type { DesktopShellStatus } from "./desktopShellFreshness.js";

/** A version read is not permission to stop a workspace. Recheck after preparation. */
export async function executeLauncherUpdate(input: {
  activeWork: () => Promise<ActiveWorkStatus>;
  prepare: () => Promise<unknown>;
  stopWorkspaces: () => Promise<void>;
  scheduleReplacement: () => Promise<void>;
}): Promise<OrchestratedLifecycleResult> {
  const check = async (): Promise<OrchestratedLifecycleResult | null> => {
    let status: ActiveWorkStatus;
    try {
      status = await input.activeWork();
    } catch {
      status = { state: "unknown", message: "" };
    }
    if (status.state === "idle") return null;
    return {
      schemaVersion: 1,
      accepted: false,
      operation: "restart-latest-shell",
      code: status.state === "active" ? "active_work_blocked" : "active_work_status_unavailable",
      message: status.state === "active" ? ACTIVE_WORK_BLOCK_MESSAGE_RESTART
        : "暂时无法确认是否有进行中的任务，已取消更新。请重新检测。",
      activeWorkRuns: status.items,
    };
  };
  const before = await check();
  if (before) return before;
  // Build failures stay in the live window; no workspace has been stopped yet.
  await input.prepare();
  const after = await check();
  if (after) return after;
  await input.stopWorkspaces();
  await input.scheduleReplacement();
  return { schemaVersion: 1, accepted: true, operation: "restart-latest-shell", message: "准备完成，正在退出并在后台完成 Launcher 换版。" };
}

export function projectLauncherUpdateFreshness(input: {
  raw: unknown;
  packaged: boolean;
  shell?: DesktopShellStatus;
  activeWork: ActiveWorkStatus;
  updating: boolean;
}): Record<string, unknown> {
  const raw = typeof input.raw === "object" && input.raw !== null ? input.raw as Record<string, unknown> : {};
  const shell = input.shell;
  const known = Boolean(shell && shell.currentElectronTree && shell.reason !== "frontend_inspection_failed" && !shell.reason.endsWith("_unavailable")
    && (shell.stale || shell.reason === "current"));
  const current = input.packaged ? (known ? !shell!.stale : null) : raw.current;
  const shellStale = input.packaged ? (known && shell?.stale === true) : raw.shellStale === true;
  return {
    ...raw,
    current: current === true ? true : current === false ? false : null,
    label: current === true ? "Launcher 已是最新" : current === false || shellStale ? "Launcher 落后本地代码" : "Launcher 版本未知",
    shellStale,
    shellReason: input.packaged ? (shell?.reason ?? "inspection_failed") : raw.shellReason,
    updateAvailable: current === false || shellStale,
    activeWorkState: input.activeWork.state,
    activeWorkCount: input.activeWork.count ?? input.activeWork.items?.length ?? 0,
    updateInProgress: input.updating,
    ...(input.packaged ? {
      runningShort: shell?.packagedSourceCommit?.slice(0, 12) || "",
      headShort: shell?.currentCommit?.slice(0, 12) || "",
      refreshError: shell?.refreshBlocked ? shell.refreshBlockedDetail || "上次 Launcher 更新失败，请重试。" : "",
    } : {}),
  };
}
