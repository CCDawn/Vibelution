export type CatalogOverviewStatus = "queued" | "running" | "succeeded" | "failed";
export type CatalogOverviewAction = "continue" | "retry" | "view";
export type CatalogOverviewFilter = "all" | CatalogOverviewStatus;

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

const STATUS_ORDER: Record<CatalogOverviewStatus, number> = {
  failed: 0,
  running: 1,
  queued: 2,
  succeeded: 2,
};

export function sortCatalogOverviewRows(
  rows: readonly CatalogOverviewQuestion[],
): CatalogOverviewQuestion[] {
  return [...rows].sort((left, right) => {
    const rank = STATUS_ORDER[left.status] - STATUS_ORDER[right.status];
    if (rank !== 0) return rank;
    return left.questionId.localeCompare(right.questionId, "en");
  });
}

export function filterCatalogOverviewRows(
  rows: readonly CatalogOverviewQuestion[],
  filter: CatalogOverviewFilter,
): CatalogOverviewQuestion[] {
  if (filter === "all") return [...rows];
  return rows.filter((row) => row.status === filter);
}

export function visibleCatalogOverviewRows(
  rows: readonly CatalogOverviewQuestion[],
  filter: CatalogOverviewFilter,
): CatalogOverviewQuestion[] {
  return sortCatalogOverviewRows(filterCatalogOverviewRows(rows, filter));
}

export function catalogOverviewStatusLabel(status: CatalogOverviewStatus, zh: boolean): string {
  if (status === "failed") return zh ? "失败" : "Failed";
  if (status === "running") return zh ? "进行中" : "Running";
  if (status === "succeeded") return zh ? "已完成" : "Succeeded";
  return zh ? "待开始" : "Queued";
}

export function catalogOverviewStageLabel(stage: string, zh: boolean): string {
  if (stage === "catalog_execution") return zh ? "目录执行" : "Catalog execution";
  if (stage === "complete") return zh ? "完成" : "Complete";
  if (stage === "blocked") return zh ? "阻塞" : "Blocked";
  return zh ? "排队" : "Queued";
}

export function catalogOverviewActionLabel(action: CatalogOverviewAction, zh: boolean): string {
  if (action === "retry") return zh ? "重试" : "Retry";
  if (action === "continue") return zh ? "继续" : "Continue";
  return zh ? "查看" : "View";
}

export function catalogOverviewCountLabel(
  counts: CatalogOverview["counts"],
  zh: boolean,
): string {
  return zh
    ? `${counts.succeeded} 通过 · ${counts.failed} 失败 · ${counts.queued} 排队`
    : `${counts.succeeded} passed · ${counts.failed} failed · ${counts.queued} queued`;
}

export function catalogOverviewProgressPercent(
  counts: CatalogOverview["counts"],
  questionCount: number,
): number {
  if (questionCount <= 0) return 0;
  return Math.round((counts.succeeded / questionCount) * 100);
}
