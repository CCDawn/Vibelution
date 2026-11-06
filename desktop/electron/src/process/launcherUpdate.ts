import type { OrchestratedLifecycleResult } from "../protocol/launcherIpcHost.js";
import type { ActiveWorkStatus } from "../shutdown/shutdownCoordinator.js";
import { ACTIVE_WORK_BLOCK_MESSAGE_RESTART } from "./activeWorkGuard.js";
import type { DesktopShellStatus } from "./desktopShellFreshness.js";
import { parseLauncherBuild, type LauncherBuild } from "./launcherBuildIdentity.js";

/** A version read is not permission to stop a workspace. Recheck after preparation. */
export async function executeLauncherUpdate(input: {
  /** Explicit operator refresh saves active tasks through stopWorkspaces. */
  interruptActiveWork?: boolean;
  activeWork: () => Promise<ActiveWorkStatus>;
  prepare: () => Promise<unknown>;
  stopWorkspaces: () => Promise<void>;
  scheduleReplacement: () => Promise<void>;
  /** Hold native assistant admission from the final idle proof through exit. */
  acquireShutdownGuard?: () => Promise<{ release(): Promise<void>; commit?(): void }>;
}): Promise<OrchestratedLifecycleResult> {
  const check = async (): Promise<OrchestratedLifecycleResult | null> => {
    let status: ActiveWorkStatus;
    try {
      status = await input.activeWork();
    } catch {
      status = { state: "unknown", message: "" };
    }
    // An explicit operator update already authorized the interrupt. Unknown is
    // not a reason to cancel: stopWorkspaces still saves records first.
    // "unobservable" is a pure observation failure (lost probe/payload) with no
    // active-work claim, so it belongs in the same operator bypass; the
    // non-operator quit path keeps rejecting it and defers to decideShutdown.
    const operatorUpdate = input.interruptActiveWork === true;
    if (status.state === "idle" || (operatorUpdate
      && (status.state === "active" || status.state === "unknown" || status.state === "unobservable"))) return null;
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
  const guard = await input.acquireShutdownGuard?.();
  try {
    await input.stopWorkspaces();
    guard?.commit?.();
    await input.scheduleReplacement();
  } catch (error) {
    // Failed preparation/stops keep the same live assistant usable. An
    // accepted replacement retains admission until the captured host exits.
    void guard?.release().catch(() => undefined);
    throw error;
  }
  return { schemaVersion: 1, accepted: true, operation: "restart-latest-shell", message: "准备完成，正在退出并在后台完成 Launcher 换版。" };
}

export function desktopShellVersionKnown(shell: DesktopShellStatus | undefined): shell is DesktopShellStatus {
  return Boolean(shell && shell.currentElectronTree && shell.reason !== "frontend_inspection_failed" && !shell.reason.endsWith("_unavailable")
    && (shell.stale || shell.reason === "current"));
}

/** A missed shell read must not erase the last reading that identified a version. */
export function retainKnownDesktopShell(
  previous: DesktopShellStatus | undefined,
  next: DesktopShellStatus | undefined,
): DesktopShellStatus | undefined {
  if (desktopShellVersionKnown(next)) return next;
  if (desktopShellVersionKnown(previous)) return previous;
  return undefined;
}

export function projectLauncherUpdateFreshness(input: {
  raw: unknown;
  packaged: boolean;
  shell?: DesktopShellStatus;
  activeWork: ActiveWorkStatus;
  updating: boolean;
  runningBuild?: LauncherBuild | null;
}): Record<string, unknown> {
  const raw = typeof input.raw === "object" && input.raw !== null ? input.raw as Record<string, unknown> : {};
  const shell = input.shell;
  const known = desktopShellVersionKnown(shell);
  let current = input.packaged ? (known ? !shell.stale : null) : raw.current;
  const shellStale = input.packaged ? (known && shell.stale === true) : raw.shellStale === true;
  const nativeUpdate = current === false || shellStale;
  const hasBuildSnapshot = input.runningBuild !== undefined;
  const availableBuild = parseLauncherBuild(raw.availableBuild, input.packaged ? "packaged" : "unpackaged");
  const availableBuildState = raw.availableBuildState === "not_built" ? "not_built"
    : raw.availableBuildState === "ready" && availableBuild ? "ready" : "unknown";
  const buildsDiffer = Boolean(input.runningBuild && availableBuild && input.runningBuild.id !== availableBuild.id);
  if (hasBuildSnapshot) {
    current = input.runningBuild && availableBuildState === "ready"
      ? (buildsDiffer || nativeUpdate ? false : current === true ? true : null) : null;
  }
  return {
    ...raw,
    current: current === true ? true : current === false ? false : null,
    label: current === true ? "Launcher 已是最新" : current === false || shellStale ? "Launcher 落后本地代码" : "Launcher 版本未知",
    shellStale,
    shellReason: input.packaged ? (shell?.reason ?? "inspection_failed") : raw.shellReason,
    updateAvailable: nativeUpdate || buildsDiffer || (hasBuildSnapshot && availableBuildState === "not_built"),
    activeWorkState: input.activeWork.state,
    activeWorkCount: input.activeWork.count ?? input.activeWork.items?.length ?? 0,
    updateInProgress: input.updating,
    ...(input.packaged ? {
      runningShort: shell?.packagedSourceCommit?.slice(0, 12) || "",
      headShort: shell?.currentCommit?.slice(0, 12) || "",
      refreshError: shell?.refreshBlocked ? shell.refreshBlockedDetail || "上次 Launcher 更新失败，请重试。" : "",
    } : {}),
    ...(hasBuildSnapshot ? {
      runningBuild: input.runningBuild,
      availableBuild: availableBuildState === "ready" ? availableBuild : null,
      availableBuildState,
      // Commit fields remain source metadata; never refill them from a short-lived bridge's HEAD.
      runningCommit: input.runningBuild?.sourceCommit ?? "",
      runningShort: input.runningBuild?.sourceCommit?.slice(0, 12) ?? "",
      headCommit: availableBuild?.sourceCommit ?? "",
      headShort: availableBuild?.sourceCommit?.slice(0, 12) ?? "",
    } : {}),
  };
}
