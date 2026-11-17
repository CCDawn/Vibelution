import type { OrchestratedLifecycleResult } from "../protocol/launcherIpcHost.js";
import { setTimeout as delay } from "node:timers/promises";
import type { ActiveWorkStatus } from "../shutdown/shutdownCoordinator.js";
import { ACTIVE_WORK_BLOCK_MESSAGE_RESTART } from "./activeWorkGuard.js";
import type { DesktopShellStatus } from "./desktopShellFreshness.js";
import { parseLauncherBuild, type LauncherBuild } from "./launcherBuildIdentity.js";

export type LauncherUpdatePhase = "checking" | "preparing" | "desktop" | "frontend" | "package" | "saving" | "replacing";
export type LauncherUpdateProgress = { phase: LauncherUpdatePhase; startedAt: number };

const CLI_UPDATE_ADMISSION_ATTEMPTS = 3;
const CLI_UPDATE_ADMISSION_RETRY_MS = 250;

/**
 * The ensure step found another refresh helper already staging the package.
 * That helper publishes after this shell exits, so this transaction must not
 * stop the workspace: it could not take the helper's lock afterwards.
 */
function preparationOwnedByAnotherRefresh(prepared: unknown): boolean {
  if (typeof prepared !== "object" || prepared === null) return false;
  const electron = (prepared as { electron?: unknown }).electron;
  if (typeof electron !== "object" || electron === null) return false;
  return (electron as { reason?: unknown }).reason === "refresh_in_progress";
}

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
  /** The caller's guard must finish failed acquisition cleanup before rejecting. */
  retryBusyAdmission?: boolean;
  onPhase?: (phase: LauncherUpdatePhase) => void;
}): Promise<OrchestratedLifecycleResult> {
  const phase = (value: LauncherUpdatePhase) => {
    try { input.onPhase?.(value); } catch { /* Status observers cannot change update admission. */ }
  };
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
  phase("checking");
  const before = await check();
  if (before) return before;
  // Build failures stay in the live window; no workspace has been stopped yet.
  phase("preparing");
  const prepared = await input.prepare();
  if (preparationOwnedByAnotherRefresh(prepared)) {
    return {
      schemaVersion: 1,
      accepted: false,
      operation: "restart-latest-shell",
      code: "launcher_update_in_progress",
      message: "桌面壳正在由另一个进程更新，当前窗口保持打开。",
      activeWorkRuns: [],
    };
  }
  let guard: Awaited<ReturnType<NonNullable<typeof input.acquireShutdownGuard>>> | undefined;
  for (let attempt = 1; ; attempt += 1) {
    const after = await check();
    if (after) return after;
    try {
      guard = await input.acquireShutdownGuard?.();
      break;
    } catch (error: unknown) {
      if (!input.retryBusyAdmission || !(error instanceof Error) || error.message !== "ASSISTANT_LIFECYCLE_BUSY") {
        throw error;
      }
      if (attempt >= CLI_UPDATE_ADMISSION_ATTEMPTS) {
        return {
          schemaVersion: 1,
          accepted: false,
          operation: "restart-latest-shell",
          code: "assistant_lifecycle_busy",
          message: "无法确认个人助理已空闲，未重启。请稍后再试。"
        };
      }
      await delay(CLI_UPDATE_ADMISSION_RETRY_MS);
    }
  }
  try {
    phase("saving");
    await input.stopWorkspaces();
    guard?.commit?.();
    phase("replacing");
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
  progress?: LauncherUpdateProgress | null;
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
    updatePhase: input.updating ? input.progress?.phase : undefined,
    updateStartedAt: input.updating ? input.progress?.startedAt : undefined,
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
      // Keep the launcher's disk HEAD under separate names: a pending build has
      // no artifact commit yet, but callers still need to tell a frontend-only
      // build from a stale backend.
      runningCommit: input.runningBuild?.sourceCommit ?? "",
      runningShort: input.runningBuild?.sourceCommit?.slice(0, 12) ?? "",
      headCommit: availableBuild?.sourceCommit ?? "",
      headShort: availableBuild?.sourceCommit?.slice(0, 12) ?? "",
      diskHeadCommit: String(raw.headCommit ?? "").trim(),
      diskHeadShort: String(raw.headShort ?? "").trim(),
    } : {}),
  };
}
