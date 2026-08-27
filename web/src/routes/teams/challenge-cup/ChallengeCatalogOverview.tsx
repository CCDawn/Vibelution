import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../../api/queryKeys";
import {
  fetchChallengeCupCatalogOverview,
  runChallengeCupDevBatch,
} from "../../../api/teamExperiment";
import { trackDevBatchRun } from "../challengeCupTelemetry";
import {
  VButton,
  VConfirmDialog,
  VDenseTable,
  VEmptyState,
  VListDetailPage,
  VMetricStrip,
  VSelect,
  VStateSurface,
  VStatusChip,
  type VStatusTone,
} from "../../../components/vui";
import { resolvePollingInterval, usePageVisibility } from "../../../app/pollingPolicy";
import styles from "./ChallengeCatalogOverview.styles";
import {
  catalogOverviewActionLabel,
  catalogOverviewAwaitingApprovalCount,
  catalogOverviewCountLabel,
  catalogOverviewDisplayStatus,
  catalogOverviewProgressPercent,
  catalogOverviewStageLabel,
  catalogOverviewStatusLabel,
  failedQuestionIdsInPlan,
  visibleCatalogOverviewRows,
  type CatalogOverview,
  type CatalogOverviewAction,
  type CatalogOverviewFilter,
  type CatalogOverviewQuestion,
  type CatalogOverviewDisplayStatus,
  type CatalogOverviewStatus,
} from "./challengeCatalogOverviewModel";

export type ChallengeCatalogOverviewProps = {
  teamId: string;
  lang?: "zh" | "en";
  onOpenQuestion: (questionId: string) => void;
  onRegisterQuestion?: () => void;
  /** DEV-only capability for fixture batch retry/continue mutations. */
  devBatchControlsEnabled?: boolean;
};

function statusTone(status: CatalogOverviewDisplayStatus): VStatusTone {
  if (status === "failed") return "danger";
  if (status === "succeeded") return "success";
  if (status === "running") return "accent";
  if (status === "awaiting_approval") return "warning";
  return "neutral";
}

function isCatalogOverview(value: unknown): value is CatalogOverview {
  if (!value || typeof value !== "object") return false;
  const record = value as CatalogOverview;
  return Array.isArray(record.questions) && typeof record.questionCount === "number";
}

export function isDevBatchCatalogAction(
  row: CatalogOverviewQuestion,
  devBatchControlsEnabled: boolean,
): boolean {
  return devBatchControlsEnabled
    && Boolean(row.planId)
    && (row.action === "retry" || row.action === "continue");
}

export function ChallengeCatalogOverviewView({
  overview,
  lang = "zh",
  selectedId,
  filter,
  actionPending = false,
  actionError = "",
  onSelect,
  onFilterChange,
  onAction,
  devBatchControlsEnabled = false,
}: {
  overview: CatalogOverview;
  lang?: "zh" | "en";
  selectedId: string;
  filter: CatalogOverviewFilter;
  actionPending?: boolean;
  actionError?: string;
  onSelect: (questionId: string) => void;
  onFilterChange: (filter: CatalogOverviewFilter) => void;
  onAction: (row: CatalogOverviewQuestion) => void;
  devBatchControlsEnabled?: boolean;
}) {
  const zh = lang === "zh";
  const visible = useMemo(
    () => visibleCatalogOverviewRows(overview.questions, filter),
    [overview.questions, filter],
  );
  const selected = visible.find((row) => row.questionId === selectedId) ?? visible[0] ?? null;
  const percent = catalogOverviewProgressPercent(overview.counts, overview.questionCount);
  const counts = overview.counts;
  const awaitingApprovalCount = catalogOverviewAwaitingApprovalCount(overview.questions);

  return (
    <VListDetailPage
      ariaLabel={zh ? "125 题批量总览" : "125-question catalog overview"}
      className={styles.root}
      fill={false}
      title={zh ? "125 题批次总览" : "125-question batch overview"}
      meta={catalogOverviewCountLabel(counts, zh, awaitingApprovalCount)}
      toolbar={(
        <div className={styles.toolbar}>
          <div
            className={styles.progressTrack}
            data-testid="catalog-overview-progress"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent}
            aria-label={zh ? "已完成比例" : "Completed share"}
          >
            <div className={styles.progressFill} style={{ width: `${percent}%` }} />
          </div>
          <VMetricStrip
            ariaLabel={zh ? "批次计数" : "Batch counts"}
            metrics={[
              { id: "succeeded", label: zh ? "通过" : "Passed", value: counts.succeeded, tone: "success" },
              { id: "failed", label: zh ? "失败" : "Failed", value: counts.failed, tone: "danger" },
              { id: "running", label: zh ? "进行中" : "Running", value: counts.running, tone: "accent" },
              { id: "queued", label: zh ? "排队" : "Queued", value: counts.queued },
              { id: "awaiting-approval", label: zh ? "待审批" : "Awaiting approval", value: awaitingApprovalCount, tone: "warning" },
            ]}
          />
          <VSelect
            aria-label={zh ? "按状态过滤" : "Filter by status"}
            className={styles.filter}
            data-vui="catalog-overview-filter"
            selectedKey={filter}
            onSelectionChange={(key) => onFilterChange(String(key || "all") as CatalogOverviewFilter)}
            options={[
              { id: "all", label: zh ? "全部" : "All" },
              { id: "failed", label: catalogOverviewStatusLabel("failed", zh) },
              { id: "running", label: catalogOverviewStatusLabel("running", zh) },
              { id: "queued", label: catalogOverviewStatusLabel("queued", zh) },
              { id: "succeeded", label: catalogOverviewStatusLabel("succeeded", zh) },
              { id: "awaiting_approval", label: catalogOverviewStatusLabel("awaiting_approval", zh) },
            ]}
          />
        </div>
      )}
      list={(
        <div className={styles.listPane} data-testid="catalog-overview" data-vui="challenge-catalog-overview">
          {visible.length === 0 ? (
            <VEmptyState title={zh ? "没有匹配的题目" : "No matching questions"} align="start" />
          ) : (
            <VDenseTable
              ariaLabel={zh ? "题目列表" : "Question list"}
              getRowKey={(row) => row.questionId}
              rows={visible}
              onRowClick={(row) => onSelect(row.questionId)}
              getRowState={(row) => ({
                selected: row.questionId === selected?.questionId,
                tone: catalogOverviewDisplayStatus(row) === "failed"
                  ? "warning"
                  : catalogOverviewDisplayStatus(row) === "succeeded"
                    ? "success"
                    : "neutral",
              })}
              columns={[
                {
                  id: "questionId",
                  header: zh ? "题号" : "ID",
                  width: 88,
                  render: (row) => (
                    <span className={styles.questionId} data-testid={`catalog-overview-row-${row.questionId}`}>
                      {row.questionId}
                    </span>
                  ),
                },
                {
                  id: "title",
                  header: zh ? "问题" : "Question",
                  fill: true,
                  render: (row) => <span className={styles.title}>{row.title}</span>,
                },
                {
                  id: "status",
                  header: zh ? "状态" : "Status",
                  width: 88,
                  render: (row) => (
                    <VStatusChip tone={statusTone(catalogOverviewDisplayStatus(row))}>
                      {catalogOverviewStatusLabel(catalogOverviewDisplayStatus(row), zh)}
                    </VStatusChip>
                  ),
                },
                {
                  id: "stage",
                  header: zh ? "阶段" : "Stage",
                  width: 108,
                  render: (row) => catalogOverviewStageLabel(row.currentStage, zh),
                },
                {
                  id: "checkpoint",
                  header: zh ? "检查点" : "Checkpoint",
                  width: 88,
                  render: (row) => row.checkpointProgress,
                },
              ]}
            />
          )}
        </div>
      )}
      detail={selected ? (
        <div className={styles.detail} data-testid="catalog-overview-detail">
          <div className={styles.detailTitle}>{selected.questionId} · {selected.title}</div>
          <div className={styles.detailMeta}>
            {catalogOverviewStageLabel(selected.currentStage, zh)} · {selected.checkpointProgress} · attempts={selected.attempts}
          </div>
          <VStatusChip tone={statusTone(catalogOverviewDisplayStatus(selected))}>
            {catalogOverviewStatusLabel(catalogOverviewDisplayStatus(selected), zh)}
          </VStatusChip>
          {selected.blocker ? (
            <div className={styles.blocker} data-testid="catalog-overview-blocker">
              <div className={styles.blockerMessage}>{selected.blocker.message}</div>
              <div className={styles.blockerRemediation}>{selected.blocker.remediationLabel}</div>
            </div>
          ) : null}
          {actionError ? (
            <div className={styles.blocker} role="alert" data-testid="catalog-overview-action-error">
              <div className={styles.blockerMessage}>{actionError}</div>
            </div>
          ) : null}
          <VButton
            type="button"
            variant="secondary"
            isPending={actionPending}
            isDisabled={actionPending}
            data-dev-batch-action={devBatchControlsEnabled ? selected.action : "view"}
            onClick={() => onAction(selected)}
          >
            {devBatchControlsEnabled
              ? catalogOverviewActionLabel(selected.action, zh)
              : (zh ? "查看详情" : "View details")}
          </VButton>
        </div>
      ) : (
        <VEmptyState title={zh ? "选择一道题查看详情" : "Select a question"} align="start" />
      )}
    />
  );
}

export function ChallengeCatalogOverview({
  teamId,
  lang = "zh",
  onOpenQuestion,
  onRegisterQuestion,
  devBatchControlsEnabled = import.meta.env.DEV,
}: ChallengeCatalogOverviewProps) {
  const zh = lang === "zh";
  const pageVisible = usePageVisibility();
  const queryClient = useQueryClient();
  const overviewKey = queryKeys.challengeCupCatalogOverview(teamId);
  const overviewQuery = useQuery({
    queryKey: overviewKey,
    queryFn: () => fetchChallengeCupCatalogOverview(teamId),
    enabled: Boolean(teamId.trim()),
    staleTime: 15_000,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!isCatalogOverview(data)) return false;
      const hasActiveWork = data.counts.running > 0 || data.counts.queued > 0;
      return hasActiveWork
        ? resolvePollingInterval(pageVisible, 5_000, { backgroundMs: 15_000 })
        : false;
    },
  });
  const [filter, setFilter] = useState<CatalogOverviewFilter>("all");
  const [selectedId, setSelectedId] = useState("");
  const [pendingRetry, setPendingRetry] = useState<{ planId: string; failedIds: string[] } | null>(null);

  const batchMutation = useMutation({
    onMutate: (input: { planId: string; retryFailed: boolean }) => ({
      telemetry: trackDevBatchRun({
        teamId,
        planId: input.planId,
        retryFailed: input.retryFailed,
        maxItems: null,
        source: "catalog_overview",
      }),
    }),
    mutationFn: (input: { planId: string; retryFailed: boolean }) =>
      runChallengeCupDevBatch(teamId, input.planId, {
        maxItems: null,
        retryFailed: input.retryFailed,
      }),
    onSuccess: async (_data, _vars, ctx) => {
      ctx?.telemetry?.succeeded();
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: overviewKey }),
        queryClient.invalidateQueries({ queryKey: queryKeys.challengeCupDevControlsSnapshot(teamId) }),
      ]);
    },
    onError: (reason: unknown, _vars, ctx) => {
      ctx?.telemetry?.failed(reason);
    },
  });
  const batchErrorText = batchMutation.error instanceof Error
    ? batchMutation.error.message
    : batchMutation.error
      ? String(batchMutation.error)
      : "";

  const handleAction = (row: CatalogOverviewQuestion) => {
    const action: CatalogOverviewAction = row.action;
    if (isDevBatchCatalogAction(row, devBatchControlsEnabled) && action === "retry") {
      // retryFailed is plan-scoped: confirm the full failed set before mutating
      // so a per-row button never silently re-runs other questions.
      const failedIds = isCatalogOverview(overviewQuery.data)
        ? failedQuestionIdsInPlan(overviewQuery.data.questions, row.planId)
        : [];
      setPendingRetry({ planId: row.planId, failedIds });
      return;
    }
    if (isDevBatchCatalogAction(row, devBatchControlsEnabled) && action === "continue") {
      batchMutation.mutate({ planId: row.planId, retryFailed: false });
      return;
    }
    onOpenQuestion(row.questionId);
  };

  if (overviewQuery.isPending) {
    return <VStateSurface tone="loading" title={zh ? "读取 125 题总览" : "Loading catalog overview"} />;
  }
  if (overviewQuery.isError || !isCatalogOverview(overviewQuery.data)) {
    return (
      <VStateSurface
        tone="error"
        title={zh ? "题目总览不可用" : "Catalog overview unavailable"}
        actions={(
          <VButton type="button" variant="secondary" onClick={() => void overviewQuery.refetch()}>
            {zh ? "重试" : "Retry"}
          </VButton>
        )}
      />
    );
  }
  if (overviewQuery.data.questions.length === 0) {
    return (
      <VEmptyState
        title={zh ? "暂无题目" : "No questions"}
        align="start"
        actions={onRegisterQuestion ? (
          <VButton type="button" variant="primary" onClick={onRegisterQuestion}>
            {zh ? "登记第一道题" : "Register the first question"}
          </VButton>
        ) : undefined}
      >
        {zh ? "先登记一道题，题目总览会在这里显示运行状态。" : "Register a question to start tracking its run here."}
      </VEmptyState>
    );
  }

  return (
    <>
      <ChallengeCatalogOverviewView
        overview={overviewQuery.data}
        lang={lang}
        selectedId={selectedId}
        filter={filter}
        actionPending={devBatchControlsEnabled && batchMutation.isPending}
        actionError={devBatchControlsEnabled ? batchErrorText : ""}
        onSelect={setSelectedId}
        onFilterChange={setFilter}
        onAction={handleAction}
        devBatchControlsEnabled={devBatchControlsEnabled}
      />
      <VConfirmDialog
        open={pendingRetry !== null}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setPendingRetry(null);
        }}
        title={zh ? "重试该批次的全部失败题目？" : "Retry every failed question in this batch?"}
        description={zh
          ? "重试作用于整个批次：该批次中所有失败题目都会重新运行，不只是当前这一题。"
          : "Retry is plan-scoped: every failed question in this batch re-runs, not only the current row."}
        tone="danger"
        confirmLabel={zh
          ? `重试全部 ${pendingRetry?.failedIds.length ?? 0} 道失败题`
          : `Retry all ${pendingRetry?.failedIds.length ?? 0} failed`}
        cancelLabel={zh ? "取消" : "Cancel"}
        confirmPending={batchMutation.isPending}
        confirmDisabled={(pendingRetry?.failedIds.length ?? 0) === 0 || batchMutation.isPending}
        onConfirm={() => {
          const planId = pendingRetry?.planId;
          setPendingRetry(null);
          if (planId) {
            batchMutation.mutate({ planId, retryFailed: true });
          }
        }}
      >
        <div>
          <p>{zh ? "受影响题目：" : "Affected questions:"}</p>
          <p>{(pendingRetry?.failedIds ?? []).slice(0, 12).join("、")
            || (zh ? "（无失败题目）" : "(none)")}</p>
          {(pendingRetry?.failedIds.length ?? 0) > 12 ? (
            <p>{zh
              ? `…以及其余 ${(pendingRetry?.failedIds.length ?? 0) - 12} 道`
              : `…and ${(pendingRetry?.failedIds.length ?? 0) - 12} more`}</p>
          ) : null}
        </div>
      </VConfirmDialog>
    </>
  );
}
