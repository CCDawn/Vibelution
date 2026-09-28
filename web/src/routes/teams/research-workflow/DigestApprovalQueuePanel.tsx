import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  executeBatchApproveDigests,
  fetchPendingDigestApprovals,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import type {
  BatchDigestApproveItemResult,
  PendingDigestApprovalItem,
} from "../../../api/types/hypothesisFirst";
import {
  VButton,
  VCheckbox,
  VEmbeddedPanel,
  VStateSurface,
  VStatusChip,
} from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import styles from "./DigestApprovalQueuePanel.styles";

type Language = "zh" | "en";

export type DigestApprovalQueuePanelProps = {
  teamId: string;
  lang?: Language;
  /** Recorded as the approver on every batch row (matches operator console). */
  closedBy?: string;
};

export const DIGEST_APPROVAL_DEFAULT_CLOSED_BY = "operator-console";

function formatAge(seconds: number, zh: boolean): string {
  if (seconds <= 0) return zh ? "刚到达" : "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}${zh ? " 分钟前" : " min ago"}`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}${zh ? " 小时前" : " h ago"}`;
  return `${Math.round(seconds / 86_400)}${zh ? " 天前" : " d ago"}`;
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason || "unavailable");
}

function rowKey(item: PendingDigestApprovalItem): string {
  return item.meetingRoundId;
}

/** Human-readable first line for one awaiting digest row. */
export function digestApprovalRowText(item: PendingDigestApprovalItem, zh: boolean): string {
  const question = item.questionId || (zh ? "未知题目" : "unknown question");
  const candidates = item.proposedCandidateCount > 0
    ? `${zh ? "候选" : "candidates"} ${item.proposedCandidateCount}`
    : "";
  const risks = item.riskCount > 0 ? `${zh ? "风险" : "risks"} ${item.riskCount}` : "";
  const meta = [candidates, risks, formatAge(item.ageSeconds, zh)].filter(Boolean).join(" · ");
  return `${question} · ${meta}`;
}

export function DigestApprovalQueuePanel({
  teamId,
  lang,
  closedBy = DIGEST_APPROVAL_DEFAULT_CLOSED_BY,
}: DigestApprovalQueuePanelProps) {
  const { lang: shellLang } = useShellI18n();
  const zh = (lang ?? shellLang) === "zh";
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<BatchDigestApproveItemResult[]>([]);

  const queueQuery = useQuery({
    queryKey: queryKeys.digestApprovals(teamId),
    queryFn: ({ signal }) => fetchPendingDigestApprovals(teamId, { signal }),
    enabled: Boolean(teamId.trim()),
    staleTime: 10_000,
    refetchOnWindowFocus: "always",
  });
  const items = queueQuery.data?.items ?? [];

  const approveMutation = useMutation({
    mutationFn: () => executeBatchApproveDigests(
      teamId,
      items
        .filter((item) => selected.has(rowKey(item)))
        .map((item) => ({
          meetingRoundId: item.meetingRoundId,
          expectedDigestContentHash: item.digestContentHash,
        })),
      closedBy,
    ),
    onSuccess: (response) => {
      setResults(response.results);
      setSelected(new Set());
      void queryClient.invalidateQueries({ queryKey: queryKeys.digestApprovals(teamId) });
    },
  });

  const selectedCount = useMemo(
    () => items.filter((item) => selected.has(rowKey(item))).length,
    [items, selected],
  );
  const resultById = useMemo(() => {
    const map = new Map<string, BatchDigestApproveItemResult>();
    for (const row of results) map.set(row.meetingRoundId, row);
    return map;
  }, [results]);

  function toggleRow(meetingRoundId: string, checked: boolean): void {
    setSelected((previous) => {
      const next = new Set(previous);
      if (checked) next.add(meetingRoundId);
      else next.delete(meetingRoundId);
      return next;
    });
  }

  if (!teamId.trim()) {
    return (
      <VStateSurface
        tone="empty"
        density="compact"
        title={zh ? "批量审批待选择团队" : "Select a team for the approval queue"}
      />
    );
  }
  if (queueQuery.isPending) {
    return (
      <VStateSurface
        tone="loading"
        density="compact"
        title={zh ? "读取待审纪要" : "Loading pending digests"}
      />
    );
  }
  if (queueQuery.isError || !queueQuery.data) {
    return (
      <VStateSurface
        tone="error"
        density="compact"
        title={zh ? "待审纪要不可用" : "Approval queue unavailable"}
        actions={(
          <VButton type="button" variant="secondary" onClick={() => void queueQuery.refetch()}>
            {zh ? "重试" : "Retry"}
          </VButton>
        )}
      >
        {errorMessage(queueQuery.error)}
      </VStateSurface>
    );
  }

  return (
    <VEmbeddedPanel
      ariaLabel={zh ? "纪要批量审批" : "Digest approval queue"}
      className={styles.root}
      data-testid="digest-approval-queue"
    >
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <strong className={styles.title}>{zh ? "纪要批量审批" : "Digest approvals"}</strong>
          <span className={styles.summary}>
            {zh
              ? `全队 ${items.length} 条纪要等待确认；勾选后一次通过，逐条带回结果。`
              : `${items.length} digests await approval team-wide; select rows and approve in one batch.`}
          </span>
        </div>
        <div className={styles.headerActions}>
          {items.some((item) => item.ttlOverdue) ? (
            <VStatusChip tone="warning" data-testid="digest-approval-ttl-count">
              {zh ? "TTL 超时" : "TTL overdue"}{" "}
              {items.filter((item) => item.ttlOverdue).length}
            </VStatusChip>
          ) : null}
          <VButton
            type="button"
            variant="ghost"
            density="compact"
            onClick={() => void queueQuery.refetch()}
          >
            {zh ? "刷新" : "Refresh"}
          </VButton>
        </div>
      </div>

      {items.length === 0 ? (
        <VStateSurface
          tone="empty"
          density="compact"
          title={zh ? "没有待审纪要" : "No pending digests"}
          data-testid="digest-approval-empty"
        >
          {zh ? "所有会议纪要均已确认。" : "Every meeting digest has been confirmed."}
        </VStateSurface>
      ) : (
        <ul className={styles.list}>
          {items.map((item) => {
            const key = rowKey(item);
            const result = resultById.get(key);
            return (
              <li key={key} className={styles.row}>
                <div className={styles.rowBody}>
                  <div className={styles.rowTop}>
                    <span className={styles.selectRow}>
                      <VCheckbox
                        isSelected={selected.has(key)}
                        onChange={(next) => toggleRow(key, next)}
                        aria-label={`${zh ? "选择" : "Select"} ${key}`}
                        data-testid={`digest-approval-select-${key}`}
                      />
                    </span>
                    <span className={styles.questionLabel}>
                      {digestApprovalRowText(item, zh)}
                    </span>
                    {item.ttlOverdue ? (
                      <VStatusChip tone="warning">{zh ? "TTL 超时" : "TTL overdue"}</VStatusChip>
                    ) : null}
                    {result ? (
                      <VStatusChip tone={result.status === "approved" ? "success" : "danger"}>
                        {result.status === "approved"
                          ? (zh ? "已通过" : "approved")
                          : (zh ? "失败" : "failed")}
                      </VStatusChip>
                    ) : null}
                  </div>
                  <span className={styles.digestSummary}>
                    {item.digestSummary || (zh ? "（纪要摘要缺失）" : "(no digest summary)")}
                  </span>
                  {result && result.status === "failed" ? (
                    <span className={styles.rowError}>
                      {result.errorType}: {result.error}
                    </span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <div className={styles.footer}>
        <VButton
          type="button"
          variant="primary"
          isDisabled={selectedCount === 0 || approveMutation.isPending}
          onClick={() => approveMutation.mutate()}
          data-testid="digest-approval-batch-button"
        >
          {approveMutation.isPending
            ? (zh ? "提交中…" : "Approving…")
            : (zh ? `批量通过（${selectedCount}）` : `Approve (${selectedCount})`)}
        </VButton>
        {approveMutation.isError ? (
          <span className={styles.rowError}>{errorMessage(approveMutation.error)}</span>
        ) : null}
        {results.length > 0 ? (
          <span className={styles.resultSummary} data-testid="digest-approval-result-summary">
            {zh
              ? `上一批：通过 ${results.filter((row) => row.status === "approved").length} · 失败 ${results.filter((row) => row.status === "failed").length}`
              : `last batch: ${results.filter((row) => row.status === "approved").length} approved · ${results.filter((row) => row.status === "failed").length} failed`}
          </span>
        ) : null}
      </div>
    </VEmbeddedPanel>
  );
}
