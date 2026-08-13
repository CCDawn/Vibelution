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
  if (item.kind !== "retired" && !item.mergedToMain && (item.head || item.branch)) {
    risks.push("delete_unmerged");
  }
  return risks;
}

export function cleanupRiskLabels(item: LauncherBranchInstance, isZh: boolean): string[] {
  const labels = isZh ? CLEANUP_RISK_LABELS_ZH : CLEANUP_RISK_LABELS_EN;
  return inferCleanupRisks(item).map((code) => labels[code] || code);
}

export type InstanceHealth = "running" | "stopped" | "dirty" | "not_open";

export type InstanceLiveOverlay = {
  currentId?: string;
  backendPid?: number;
  windowPid?: number;
  port?: number;
  alive?: boolean;
  windowOpen?: boolean;
};

export function applyLiveOverlay(item: LauncherBranchInstance, live?: InstanceLiveOverlay): LauncherBranchInstance {
  if (!live || !(item.current || item.id === live.currentId)) {
    return item;
  }
  return {
    ...item,
    alive: live.alive ?? item.alive,
    port: live.port && live.port > 0 ? live.port : item.port,
    pids: {
      backend: live.backendPid && live.backendPid > 0 ? live.backendPid : item.pids?.backend || 0,
      window: live.windowPid && live.windowPid > 0 ? live.windowPid : item.pids?.window || 0,
      manager: item.pids?.manager || 0,
    },
  };
}

export function instanceHealth(item: LauncherBranchInstance, live?: InstanceLiveOverlay): InstanceHealth {
  const merged = applyLiveOverlay(item, live);
  if (item.kind === "local_branch" || item.kind === "retired" || !item.checkedOut) {
    return "not_open";
  }
  if (merged.alive) {
    return "running";
  }
  if (item.dirty) {
    return "dirty";
  }
  return "stopped";
}

export function instanceHealthLabel(health: InstanceHealth, isZh: boolean): string {
  if (isZh) {
    return {
      running: "运行中",
      stopped: "已停止",
      dirty: "有未提交",
      not_open: "未打开",
    }[health];
  }
  return {
    running: "Running",
    stopped: "Stopped",
    dirty: "Uncommitted",
    not_open: "Not opened",
  }[health];
}

export function formatBackendCell(item: LauncherBranchInstance, live?: InstanceLiveOverlay): string {
  const merged = applyLiveOverlay(item, live);
  const pid = Number(merged.pids?.backend || 0);
  const port = Number(merged.port || 0);
  if (pid <= 0 && port <= 0) {
    return "-";
  }
  if (pid > 0 && port > 0) {
    return `${pid} · ${port}`;
  }
  return pid > 0 ? String(pid) : String(port);
}

export function instanceWindowOpen(item: LauncherBranchInstance, live?: InstanceLiveOverlay): boolean {
  const merged = applyLiveOverlay(item, live);
  if (Number(merged.pids?.window || 0) > 0) {
    return true;
  }
  return Boolean(item.current && live?.windowOpen);
}

export function canStartInstance(item: LauncherBranchInstance, live?: InstanceLiveOverlay): boolean {
  const health = instanceHealth(item, live);
  return item.checkedOut && item.kind !== "retired" && item.kind !== "local_branch" && health !== "running";
}

export function canStopInstance(item: LauncherBranchInstance, live?: InstanceLiveOverlay): boolean {
  return instanceHealth(item, live) === "running";
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
