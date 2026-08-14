import type { LauncherBranchInstance } from "../api/launcher";
import type { InstanceRuntimeState } from "./LauncherBranchInstancesPanel.model";

export type CleanupRecommendationLevel = "recommended" | "review" | "avoid";

export type CleanupRecommendation = {
  level: CleanupRecommendationLevel;
  label: string;
  reason: string;
};

export function runtimeStatusExplanation(state: InstanceRuntimeState, isZh: boolean): string {
  const zh: Record<InstanceRuntimeState, string> = {
    starting: "Launcher 正在启动该实例的运行组件。",
    running: "该实例的后端或 Workbench 窗口仍在运行。",
    partial: "该实例只有部分运行组件就绪，需要先检查运行状态。",
    stopping: "Launcher 正在停止该实例，请等待操作结束。",
    restarting: "Launcher 正在重启该实例，请等待操作结束。",
    failed: "该实例启动或运行失败，需要先处理异常状态。",
    stopped: "该实例当前没有运行中的组件。",
  };
  const en: Record<InstanceRuntimeState, string> = {
    starting: "Launcher is starting the runtime components for this instance.",
    running: "The backend or Workbench window for this instance is still running.",
    partial: "Only some runtime components are ready; inspect the runtime state first.",
    stopping: "Launcher is stopping this instance. Wait for the operation to finish.",
    restarting: "Launcher is restarting this instance. Wait for the operation to finish.",
    failed: "This instance failed to start or run and needs attention first.",
    stopped: "This instance currently has no running components.",
  };
  return (isZh ? zh : en)[state];
}

export function gitStatusExplanation(item: LauncherBranchInstance, isZh: boolean): string {
  if (item.dirty) {
    return isZh
      ? "工作区有尚未提交的文件；强制清理会丢弃这些改动。"
      : "The worktree has uncommitted files; force cleanup will discard them.";
  }
  if (item.mergedToMain === false) {
    return isZh
      ? "工作区干净，但当前提交尚未合入 main；强制清理会删除这些本地提交。"
      : "The worktree is clean, but its commits are not merged into main; force cleanup will delete them.";
  }
  if (item.mergedToMain === true) {
    return isZh
      ? "工作区没有未提交改动，当前提交也已包含在 main 中。"
      : "The worktree has no uncommitted changes and its current commit is included in main.";
  }
  return isZh
    ? "工作区没有未提交改动，但 Launcher 尚未确认当前提交是否已合入 main。"
    : "The worktree has no uncommitted changes, but Launcher has not confirmed whether its commit is merged into main.";
}

export function cleanupRecommendation(
  item: LauncherBranchInstance,
  state: InstanceRuntimeState,
  isZh: boolean,
): CleanupRecommendation {
  const protectedInstance = item.cleanupEligible === false
    || item.kind === "main"
    || item.current
    || item.branch === "main"
    || item.id === "main";
  if (protectedInstance) {
    return {
      level: "avoid",
      label: isZh ? "不可清理" : "Cleanup unavailable",
      reason: isZh ? "main 和当前工作区受保护。" : "main and the current worktree are protected.",
    };
  }
  const blockingReasons: string[] = [];
  if (state !== "stopped" || item.alive) {
    blockingReasons.push(isZh ? "先停止实例并等待状态变为“已停止”" : "stop the instance and wait until its status is Stopped");
  }
  if (item.dirty) {
    blockingReasons.push(isZh ? "先提交、暂存或备份未提交改动" : "commit, stash, or back up the uncommitted changes");
  }
  if (item.mergedToMain === false) {
    blockingReasons.push(isZh ? "先确认本地提交无需保留，或将它们合入 main" : "confirm the local commits are disposable or merge them into main");
  }
  if (blockingReasons.length > 0) {
    return {
      level: "avoid",
      label: isZh ? "不建议清理" : "Cleanup not recommended",
      reason: `${blockingReasons.join(isZh ? "；" : "; ")}${isZh ? "。" : "."}`,
    };
  }
  if (item.mergedToMain !== true) {
    return {
      level: "review",
      label: isZh ? "清理前确认" : "Review before cleanup",
      reason: isZh ? "尚无法确认提交是否已合入 main。" : "It is not yet confirmed that the commit is merged into main.",
    };
  }
  return {
    level: "recommended",
    label: isZh ? "可以清理" : "Cleanup recommended",
    reason: isZh ? "实例已停止、工作区干净且提交已合入 main。" : "The instance is stopped, clean, and merged into main.",
  };
}
