import type { LauncherBranchInstance } from "../api/launcher";

export const BRANCH_INSTANCE_PAGE_SIZE = 8;

export const CLEANUP_RISK_LABELS_ZH: Record<string, string> = {
  discard_dirty: "将丢弃未提交改动",
  stop_then_remove: "将先停止再拆除运行中的实例",
  delete_unmerged: "将删除尚未合入 main 的本地提交",
};

export const CLEANUP_RISK_LABELS_EN: Record<string, string> = {
  discard_dirty: "Uncommitted changes will be discarded",
  stop_then_remove: "The running instance will be stopped, then removed",
  delete_unmerged: "Local commits not merged into main will be deleted",
};

export function isCleanupEligible(item: LauncherBranchInstance): boolean {
  if (item.cleanupEligible === false) {
    return false;
  }
  if (item.cleanupEligible === true) {
    return true;
  }
  return item.kind !== "main" && !item.current && item.branch !== "main" && item.id !== "main";
}

export function inferCleanupRisks(item: LauncherBranchInstance): string[] {
  if (item.cleanupRisks && item.cleanupRisks.length > 0) {
    return item.cleanupRisks;
  }
  const risks: string[] = [];
  if (item.dirty) {
    risks.push("discard_dirty");
  }
  if (item.alive) {
    risks.push("stop_then_remove");
  }
  if (item.mergedToMain === false) {
    risks.push("delete_unmerged");
  }
  return risks;
}

export function cleanupRiskLabels(item: LauncherBranchInstance, isZh: boolean): string[] {
  const labels = isZh ? CLEANUP_RISK_LABELS_ZH : CLEANUP_RISK_LABELS_EN;
  return inferCleanupRisks(item).map((code) => labels[code] || code);
}

export type InstanceRuntimeState = "starting" | "running" | "partial" | "stopping" | "restarting" | "failed" | "stopped";

export type InstancePendingOperation = {
  instanceId: string;
  operation: "start" | "stop" | "restart";
};

export type BranchInstanceGroups = {
  running: LauncherBranchInstance[];
  startable: LauncherBranchInstance[];
  maintenance: LauncherBranchInstance[];
};

export function instanceWindowOpen(item: LauncherBranchInstance): boolean {
  return Boolean(item.runtime.window.open);
}

export function instanceRuntimeState(
  item: LauncherBranchInstance,
  pending?: InstancePendingOperation,
): InstanceRuntimeState {
  if (pending?.instanceId === item.id) {
    if (pending.operation === "stop") {
      return "stopping";
    }
    return pending.operation === "restart" ? "restarting" : "starting";
  }
  const states: Record<LauncherBranchInstance["runtime"]["lifecycleState"], InstanceRuntimeState> = {
    closed: "stopped",
    starting: "starting",
    running: "running",
    stopping: "stopping",
    restarting: "restarting",
    partial: "partial",
    error: "failed",
  };
  return states[item.runtime.lifecycleState];
}

export function instanceRuntimeStateLabel(state: InstanceRuntimeState, isZh: boolean): string {
  if (isZh) {
    return {
      starting: "启动中",
      running: "正常运行",
      partial: "部分运行",
      stopping: "停止中",
      restarting: "重启中",
      failed: "需要处理",
      stopped: "已停止",
    }[state];
  }
  return {
    starting: "Starting",
    running: "Running",
    partial: "Partially running",
    stopping: "Stopping",
    restarting: "Restarting",
    failed: "Needs attention",
    stopped: "Stopped",
  }[state];
}

export function isOperableInstance(item: LauncherBranchInstance): boolean {
  return Boolean(item.checkedOut && (item.kind === "main" || item.kind === "worktree"));
}

export function isStartableInstance(item: LauncherBranchInstance, pending?: InstancePendingOperation): boolean {
  return Boolean(item.startable && isOperableInstance(item) && instanceRuntimeState(item, pending) === "stopped");
}

function compareInstances(a: LauncherBranchInstance, b: LauncherBranchInstance): number {
  if (a.current !== b.current) {
    return a.current ? -1 : 1;
  }
  if (a.alive !== b.alive) {
    return a.alive ? -1 : 1;
  }
  return String(a.shortName || a.branch || a.id).localeCompare(String(b.shortName || b.branch || b.id));
}

export function groupBranchInstances(
  items: readonly LauncherBranchInstance[],
  pending?: InstancePendingOperation,
): BranchInstanceGroups {
  const groups: BranchInstanceGroups = { running: [], startable: [], maintenance: [] };
  items.forEach((item) => {
    if (instanceRuntimeState(item, pending) !== "stopped") {
      groups.running.push(item);
    } else if (isStartableInstance(item, pending)) {
      groups.startable.push(item);
    } else {
      groups.maintenance.push(item);
    }
  });
  groups.running.sort(compareInstances);
  groups.startable.sort(compareInstances);
  groups.maintenance.sort(compareInstances);
  return groups;
}

function withPort(label: string, port: number): string {
  return port > 0 ? `${label} · :${port}` : label;
}

export function formatBackendStatus(item: LauncherBranchInstance, isZh: boolean): string {
  const backend = item.runtime.backend;
  const port = Number(backend.port || 0);
  if (backend.portConflict) {
    return withPort(isZh ? "端口冲突" : "Port conflict", port);
  }
  if (!backend.alive && !backend.listening) {
    return isZh ? "未运行" : "Not running";
  }
  if (backend.alive && backend.healthy && backend.listening) {
    return withPort(isZh ? "健康" : "Healthy", port);
  }
  return withPort(isZh ? "需检查" : "Check required", port);
}

export function formatFrontendStatus(item: LauncherBranchInstance, isZh: boolean): string {
  const frontend = item.runtime.frontend;
  const stopped = item.runtime.lifecycleState === "closed";
  if (String(frontend.mode).includes("dev")) {
    if (stopped) {
      return isZh ? "Dev Server 模式" : "Dev server mode";
    }
    return frontend.ready
      ? (isZh ? "Dev Server 就绪" : "Dev server ready")
      : (isZh ? "Dev Server 异常" : "Dev server unavailable");
  }
  if (stopped) {
    return frontend.ready
      ? (isZh ? "内置模式 · 已构建" : "Bundled · Built")
      : (isZh ? "内置模式 · 启动时构建" : "Bundled · Build on start");
  }
  return frontend.ready
    ? (isZh ? "内置资源就绪" : "Bundled assets ready")
    : (isZh ? "内置资源缺失" : "Bundled assets missing");
}

export function formatWorkbenchStatus(item: LauncherBranchInstance, isZh: boolean): string {
  const title = String(item.runtime.window.title || item.workbenchTitle || `${item.shortName || item.branch || item.id}${isZh ? " 台" : " Workbench"}`);
  return `${title} · ${instanceWindowOpen(item) ? (isZh ? "已打开" : "Open") : (isZh ? "未打开" : "Closed")}`;
}

export function formatGitStatus(item: LauncherBranchInstance, isZh: boolean): string {
  const states: string[] = [];
  if (item.dirty) {
    states.push(isZh ? "有未提交" : "Uncommitted");
  }
  if (item.mergedToMain === false) {
    states.push(isZh ? "未合入 main" : "Not merged to main");
  }
  return states.length > 0 ? states.join(" · ") : (isZh ? "干净" : "Clean");
}

export function canRequestOpenInstance(item: LauncherBranchInstance, pending?: InstancePendingOperation): boolean {
  if (!isOperableInstance(item)) {
    return false;
  }
  return !["starting", "stopping", "restarting"].includes(instanceRuntimeState(item, pending));
}

export function canStartInstance(item: LauncherBranchInstance, pending?: InstancePendingOperation): boolean {
  return isStartableInstance(item, pending)
    || (canRequestOpenInstance(item, pending) && !instanceWindowOpen(item));
}

export function canStopInstance(item: LauncherBranchInstance, pending?: InstancePendingOperation): boolean {
  const backend = item.runtime.backend;
  return isOperableInstance(item)
    && !["starting", "stopping", "restarting"].includes(instanceRuntimeState(item, pending))
    && Boolean(backend.alive || backend.listening || instanceWindowOpen(item));
}

export function paginateItems<T>(items: readonly T[], page: number, pageSize = BRANCH_INSTANCE_PAGE_SIZE) {
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(Math.max(1, page), pageCount);
  const start = (safePage - 1) * pageSize;
  const slice = items.slice(start, start + pageSize);
  return {
    page: safePage,
    pageCount,
    start,
    end: start + slice.length,
    items: slice,
  };
}
