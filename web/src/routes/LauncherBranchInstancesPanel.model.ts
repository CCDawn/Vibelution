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
