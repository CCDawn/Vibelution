export type CatalogOverviewStatus = "queued" | "running" | "succeeded" | "failed";
export type CatalogOverviewAction = "continue" | "retry" | "view";
export type CatalogOverviewFilter = "all" | CatalogOverviewStatus | "awaiting_approval";
export type CatalogOverviewDisplayStatus = CatalogOverviewStatus | "awaiting_approval";

export type CatalogOverviewBlocker = {
  code: string;
  message: string;
  remediationLabel: string;
};

export type CatalogOverviewQuestion = {
  questionId: string;
  title: string;
  domain: string;
  status: CatalogOverviewStatus;
  executionStatus: string;
  currentStage: string;
  checkpointProgress: string;
  attempts: number;
  planId: string;
  action: CatalogOverviewAction;
  blocker: CatalogOverviewBlocker | null;
};

export type CatalogOverview = {
  schemaVersion: number;
  teamId: string;
  generatedAt: string;
  questionCount: number;
  counts: {
    queued: number;
    running: number;
    succeeded: number;
    failed: number;
  };
  questions: CatalogOverviewQuestion[];
};

const STATUS_ORDER: Record<CatalogOverviewDisplayStatus, number> = {
  failed: 0,
  awaiting_approval: 1,
  running: 2,
  queued: 3,
  succeeded: 3,
};

const AWAITING_APPROVAL_EXECUTION_STATUSES = new Set([
  "awaiting_human_approval",
  "awaiting_approval",
  "pending_review",
  "review_required",
]);

/**
 * The catalog endpoint keeps its stable four-way execution status while the
 * real batch may expose a more specific human-gate status in executionStatus
 * (or in the persisted blocker). Derive the display bucket from that same
 * server projection so the filter never creates a second client lifecycle.
 */
export function isCatalogOverviewAwaitingApproval(row: CatalogOverviewQuestion): boolean {
  const executionStatus = String(row.executionStatus || "").trim().toLowerCase();
  if (AWAITING_APPROVAL_EXECUTION_STATUSES.has(executionStatus)) return true;
  const blockerText = `${row.blocker?.code || ""} ${row.blocker?.message || ""}`.toLowerCase();
  return blockerText.includes("awaiting_human_approval")
    || blockerText.includes("awaiting human approval");
}

export function catalogOverviewDisplayStatus(row: CatalogOverviewQuestion): CatalogOverviewDisplayStatus {
  return isCatalogOverviewAwaitingApproval(row) ? "awaiting_approval" : row.status;
}

export function catalogOverviewAwaitingApprovalCount(rows: readonly CatalogOverviewQuestion[]): number {
  return rows.filter(isCatalogOverviewAwaitingApproval).length;
}

export function sortCatalogOverviewRows(
  rows: readonly CatalogOverviewQuestion[],
): CatalogOverviewQuestion[] {
  return [...rows].sort((left, right) => {
    const rank = STATUS_ORDER[catalogOverviewDisplayStatus(left)] - STATUS_ORDER[catalogOverviewDisplayStatus(right)];
    if (rank !== 0) return rank;
    return left.questionId.localeCompare(right.questionId, "en");
  });
}

export function filterCatalogOverviewRows(
  rows: readonly CatalogOverviewQuestion[],
  filter: CatalogOverviewFilter,
): CatalogOverviewQuestion[] {
  if (filter === "all") return [...rows];
  if (filter === "awaiting_approval") return rows.filter(isCatalogOverviewAwaitingApproval);
  return rows.filter((row) => row.status === filter);
}

export function visibleCatalogOverviewRows(
  rows: readonly CatalogOverviewQuestion[],
  filter: CatalogOverviewFilter,
): CatalogOverviewQuestion[] {
  return sortCatalogOverviewRows(filterCatalogOverviewRows(rows, filter));
}

export function catalogOverviewStatusLabel(status: CatalogOverviewDisplayStatus, zh: boolean): string {
  if (status === "failed") return zh ? "失败" : "Failed";
  if (status === "running") return zh ? "进行中" : "Running";
  if (status === "succeeded") return zh ? "已完成" : "Succeeded";
  if (status === "awaiting_approval") return zh ? "待审批" : "Awaiting approval";
  return zh ? "待开始" : "Queued";
}

export function catalogOverviewStageLabel(stage: string, zh: boolean): string {
  if (stage === "catalog_execution") return zh ? "目录执行" : "Catalog execution";
  if (stage === "complete") return zh ? "完成" : "Complete";
  if (stage === "blocked") return zh ? "阻塞" : "Blocked";
  return zh ? "排队" : "Queued";
}

export function catalogOverviewActionLabel(action: CatalogOverviewAction, zh: boolean): string {
  // The retry mutation is plan-scoped (retryFailed re-runs every failed
  // question in the plan), so the label must not read as "retry this row".
  if (action === "retry") return zh ? "重试失败题" : "Retry failed";
  if (action === "continue") return zh ? "继续" : "Continue";
  return zh ? "查看" : "View";
}

export function failedQuestionIdsInPlan(
  rows: readonly CatalogOverviewQuestion[],
  planId: string,
): string[] {
  return rows
    .filter((row) => row.planId === planId && row.status === "failed")
    .map((row) => row.questionId)
    .sort((left, right) => left.localeCompare(right, "en"));
}

export function catalogOverviewCountLabel(
  counts: CatalogOverview["counts"],
  zh: boolean,
  awaitingApprovalCount = 0,
): string {
  const base = zh
    ? `${counts.succeeded} 通过 · ${counts.failed} 失败 · ${counts.running} 进行中 · ${counts.queued} 排队`
    : `${counts.succeeded} passed · ${counts.failed} failed · ${counts.running} running · ${counts.queued} queued`;
  if (awaitingApprovalCount <= 0) return base;
  return `${base} · ${zh ? `${awaitingApprovalCount} 待审批` : `${awaitingApprovalCount} awaiting approval`}`;
}

export function catalogOverviewProgressPercent(
  counts: CatalogOverview["counts"],
  questionCount: number,
): number {
  if (questionCount <= 0) return 0;
  return Math.round((counts.succeeded / questionCount) * 100);
}
