import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, RotateCcw, TriangleAlert, Wrench } from "lucide-react";

import {
  executeHypothesisRoundFailureRetry,
  fetchHypothesisRoundFailures,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import type { HypothesisRoundFailureRecord } from "../../../api/types/hypothesisFirst";
import {
  VButton,
  VContextualHint,
  VEmbeddedPanel,
  VStateSurface,
  VStatusChip,
} from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import styles from "./ResearchWorkflowRecoveryPanel.styles";

type Language = "zh" | "en";

export type ResearchWorkflowRecoveryPanelProps = {
  teamId: string;
  lang?: Language;
};

export type ResearchWorkflowRecoveryEntryProps = {
  teamId: string;
  lang?: Language;
  /** Opens the operations pane that hosts the recovery list. */
  onOpen: () => void;
};

/**
 * Failure-code → one-line human label.  Unmapped codes fall back to the
 * stored reason (clamped by CSS), so a new backend code never renders an
 * empty row; the raw reason/code live in the per-row detail disclosure.
 */
const FAILURE_LABELS: Record<string, { zh: string; en: string }> = {
  hypothesis_round_precondition_failed: {
    zh: "轮生成前置条件未满足",
    en: "Round precondition failed",
  },
  hypothesis_round_generation_error: {
    zh: "上轮评审未完成，轮生成失败",
    en: "Review step did not finish",
  },
  hypothesis_round_validation_failed: {
    zh: "轮生成内容校验未通过",
    en: "Round content validation failed",
  },
  hypothesis_round_persistence_failed: {
    zh: "轮生成结果未能落盘",
    en: "Round persistence failed",
  },
  fan_in_waiting_for_sibling_reviews: {
    zh: "等待兄弟评审收敛",
    en: "Waiting for sibling reviews",
  },
};

function zhFrom(lang: Language | undefined, shellLang: Language): boolean {
  return (lang ?? shellLang) === "zh";
}

function failureLabel(record: HypothesisRoundFailureRecord, zh: boolean): string {
  const mapped = FAILURE_LABELS[record.failureCode];
  if (mapped) {
    return mapped[zh ? "zh" : "en"];
  }
  return record.reason || record.failureCode;
}

function formatTime(value: string, zh: boolean): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(zh ? "zh-CN" : "en-US");
}

function FailureDetails({
  record,
  zh,
}: {
  record: HypothesisRoundFailureRecord;
  zh: boolean;
}) {
  return (
    <dl className={styles.detail} data-testid={`recovery-detail-${record.failureId}`}>
      <div className={styles.detailLine}>
        <dt className={styles.detailLabel}>{zh ? "失败码" : "Code"}</dt>
        <dd className={styles.detailCode}>{record.failureCode}</dd>
      </div>
      <div className={styles.detailLine}>
        <dt className={styles.detailLabel}>{zh ? "原始信息" : "Raw"}</dt>
        <dd className={styles.detailValue}>{record.reason || "-"}</dd>
      </div>
      <div className={styles.detailLine}>
        <dt className={styles.detailLabel}>{zh ? "时间" : "Time"}</dt>
        <dd className={styles.detailValue}>{formatTime(record.createdAt, zh)}</dd>
      </div>
      <div className={styles.detailLine}>
        <dt className={styles.detailLabel}>{zh ? "处理提示" : "Hint"}</dt>
        <dd className={styles.detailValue}>{record.retryHint || "-"}</dd>
      </div>
    </dl>
  );
}

function RecoveryRowAction({
  teamId,
  record,
  zh,
  pending,
  onAccepted,
}: {
  teamId: string;
  record: HypothesisRoundFailureRecord;
  zh: boolean;
  pending: boolean;
  onAccepted: (failureId: string) => void;
}) {
  const [armed, setArmed] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [errorText, setErrorText] = useState("");
  const retryable = record.status !== "blocked";

  async function execute() {
    if (executing) return;
    setExecuting(true);
    setErrorText("");
    try {
      await executeHypothesisRoundFailureRetry(teamId, record.failureId);
    } catch (reason) {
      setErrorText(reason instanceof Error ? reason.message : String(reason));
      setExecuting(false);
      return;
    }
    setArmed(false);
    setExecuting(false);
    onAccepted(record.failureId);
  }

  if (!retryable) {
    return (
      <span className={styles.actionWait} data-testid="recovery-action-wait">
        {zh ? "无需操作，等待自动推进" : "No action; advances automatically"}
      </span>
    );
  }
  if (pending) {
    return (
      <span className={styles.actionWait} data-testid="recovery-action-pending">
        {zh ? "已排队重试，完成后自动消失" : "Retry queued; the row clears when done"}
      </span>
    );
  }
  return (
    <span className={styles.rowAction} data-testid="recovery-action">
      {armed ? (
        <span className={styles.actionConfirm}>
          <VButton
            type="button"
            variant="danger"
            density="compact"
            isDisabled={executing}
            data-testid="recovery-confirm"
            onClick={() => void execute()}
          >
            {executing ? (zh ? "提交中…" : "Submitting…") : (zh ? "确认执行" : "Confirm")}
          </VButton>
          <VButton
            type="button"
            variant="ghost"
            density="compact"
            isDisabled={executing}
            data-testid="recovery-cancel"
            onClick={() => setArmed(false)}
          >
            {zh ? "取消" : "Cancel"}
          </VButton>
        </span>
      ) : (
        <VButton
          type="button"
          variant="secondary"
          density="compact"
          icon={<Wrench size={14} aria-hidden="true" />}
          data-testid="recovery-arm"
          onClick={() => setArmed(true)}
        >
          {record.failureCode === "fan_in_waiting_for_sibling_reviews"
            ? (zh ? "重新派发评审" : "Re-dispatch review")
            : (zh ? "重新生成轮" : "Regenerate round")}
        </VButton>
      )}
      {errorText ? (
        <span className={styles.actionError} data-testid="recovery-error">
          {zh ? "执行失败：" : "Failed: "}
          {errorText}
        </span>
      ) : null}
    </span>
  );
}

export function ResearchWorkflowRecoveryPanel({
  teamId,
  lang,
}: ResearchWorkflowRecoveryPanelProps) {
  const { lang: shellLang } = useShellI18n();
  const zh = zhFrom(lang, shellLang);
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set());
  const [batchArmed, setBatchArmed] = useState(false);
  const [batchExecuting, setBatchExecuting] = useState(false);
  const [batchError, setBatchError] = useState("");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const failuresQuery = useQuery({
    queryKey: queryKeys.hypothesisFirstChainRoundFailures(teamId),
    queryFn: ({ signal }) => fetchHypothesisRoundFailures(teamId, { signal }),
    enabled: Boolean(teamId.trim()),
    staleTime: 5_000,
    refetchInterval: 5_000,
    refetchOnWindowFocus: "always",
  });
  const failures = useMemo(
    () => failuresQuery.data?.failures ?? [],
    [failuresQuery.data],
  );

  // A queued retry keeps the row pending until the ledger resolves it and the
  // row disappears — no manual dismissal, no second click.
  useEffect(() => {
    setPending((current) => {
      if (current.size === 0) return current;
      const openIds = new Set(failures.map((record) => record.failureId));
      const next = new Set([...current].filter((id) => openIds.has(id)));
      return next.size === current.size ? current : next;
    });
  }, [failures]);

  const retryable = useMemo(
    () => failures.filter((record) => record.status !== "blocked"),
    [failures],
  );
  const waiting = useMemo(
    () => failures.filter((record) => record.status === "blocked"),
    [failures],
  );

  function acceptFailure(failureId: string) {
    setPending((current) => new Set([...current, failureId]));
    void queryClient.invalidateQueries({
      queryKey: queryKeys.hypothesisFirstChainRoundFailures(teamId),
    });
  }

  async function executeBatch() {
    if (batchExecuting) return;
    setBatchExecuting(true);
    setBatchError("");
    try {
      for (const record of retryable) {
        await executeHypothesisRoundFailureRetry(teamId, record.failureId);
        acceptFailure(record.failureId);
      }
      setBatchArmed(false);
    } catch (reason) {
      setBatchError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBatchExecuting(false);
    }
  }

  if (!teamId.trim()) {
    return (
      <VStateSurface
        tone="empty"
        density="compact"
        title={zh ? "恢复面板待选择团队" : "Select a team for the recovery panel"}
      />
    );
  }
  if (failuresQuery.isPending) {
    return (
      <VStateSurface
        tone="loading"
        density="compact"
        title={zh ? "读取失败账本" : "Loading failure ledger"}
      />
    );
  }
  if (failuresQuery.isError || !failuresQuery.data) {
    return (
      <VStateSurface
        tone="error"
        density="compact"
        title={zh ? "恢复面板不可用" : "Recovery panel unavailable"}
        actions={(
          <VButton type="button" variant="secondary" onClick={() => void failuresQuery.refetch()}>
            {zh ? "重试" : "Retry"}
          </VButton>
        )}
      >
        {failuresQuery.error instanceof Error ? failuresQuery.error.message : null}
      </VStateSurface>
    );
  }

  return (
    <VEmbeddedPanel
      ariaLabel={zh ? "待人工恢复" : "Recovery queue"}
      className={styles.root}
      data-testid="research-recovery-panel"
    >
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <strong className={styles.title}>{zh ? "待人工恢复" : "Recovery queue"}</strong>
          <span className={styles.summary}>
            {zh
              ? "自动重试结束后仍未解决的项目；执行需二次确认。"
              : "Unresolved after automatic retries; execution needs confirmation."}
          </span>
        </div>
        <div className={styles.headerActions}>
          <VStatusChip tone="warning" data-testid="recovery-count-retryable">
            {zh ? "可重试" : "Retryable"} {retryable.length}
          </VStatusChip>
          <VStatusChip tone="neutral" data-testid="recovery-count-waiting">
            {zh ? "等待中" : "Waiting"} {waiting.length}
          </VStatusChip>
          {retryable.length > 0 && !batchArmed ? (
            <VButton
              type="button"
              variant="secondary"
              density="compact"
              icon={<RotateCcw size={14} aria-hidden="true" />}
              data-testid="recovery-batch-arm"
              onClick={() => setBatchArmed(true)}
            >
              {zh ? "一键重试全部可重试项" : "Retry all retryable"}
            </VButton>
          ) : null}
          {batchArmed ? (
            <span className={styles.actionConfirm}>
              <VButton
                type="button"
                variant="danger"
                density="compact"
                isDisabled={batchExecuting}
                data-testid="recovery-batch-confirm"
                onClick={() => void executeBatch()}
              >
                {batchExecuting
                  ? (zh ? "提交中…" : "Submitting…")
                  : (zh ? `确认重试全部 ${retryable.length} 项` : `Confirm retry all ${retryable.length}`)}
              </VButton>
              <VButton
                type="button"
                variant="ghost"
                density="compact"
                isDisabled={batchExecuting}
                data-testid="recovery-batch-cancel"
                onClick={() => setBatchArmed(false)}
              >
                {zh ? "取消" : "Cancel"}
              </VButton>
            </span>
          ) : null}
        </div>
      </div>

      {batchError ? (
        <span className={styles.batchError} data-testid="recovery-batch-error">
          {batchError}
        </span>
      ) : null}

      {failures.length === 0 ? (
        <VStateSurface
          tone="empty"
          density="compact"
          title={zh ? "无待人工项" : "Nothing to recover"}
        >
          {zh
            ? "失败账本与等待项均已清空；有新失败会自动出现在这里。"
            : "The failure ledger is empty; new failures will surface here automatically."}
        </VStateSurface>
      ) : (
        <ul className={styles.list}>
          {failures.map((record) => {
            const open = Boolean(expanded[record.failureId]);
            const isWaiting = record.status === "blocked";
            return (
              <li
                key={record.failureId}
                className={styles.row}
                data-testid={`recovery-row-${record.failureId}`}
              >
                <div className={styles.rowMain}>
                  <div className={styles.rowTop}>
                    <VStatusChip
                      tone={isWaiting ? "neutral" : "warning"}
                      data-testid="recovery-kind-chip"
                    >
                      {isWaiting
                        ? (zh ? "等待中" : "Waiting")
                        : (zh ? "轮生成失败" : "Round failed")}
                    </VStatusChip>
                    <span className={styles.scope}>
                      {record.questionId || (zh ? "未知题目" : "Unknown question")}
                      {record.roundIndex !== null
                        ? (zh ? ` · 第 ${record.roundIndex} 轮` : ` · Round ${record.roundIndex}`)
                        : ""}
                    </span>
                  </div>
                  <div className={styles.reasonLine}>
                    <span className={styles.reason} data-testid="recovery-reason">
                      {failureLabel(record, zh)}
                    </span>
                    <VButton
                      type="button"
                      variant="ghost"
                      density="compact"
                      className="!h-6 !min-h-0 px-1.5 [font-size:var(--vui-font-xs)]"
                      icon={open
                        ? <ChevronUp size={12} aria-hidden="true" />
                        : <ChevronDown size={12} aria-hidden="true" />}
                      aria-expanded={open}
                      data-testid={`recovery-details-${record.failureId}`}
                      onClick={() => setExpanded((current) => ({
                        ...current,
                        [record.failureId]: !current[record.failureId],
                      }))}
                    >
                      {zh ? "详情" : "Details"}
                    </VButton>
                  </div>
                  {open ? <FailureDetails record={record} zh={zh} /> : null}
                </div>
                <RecoveryRowAction
                  teamId={teamId}
                  record={record}
                  zh={zh}
                  pending={pending.has(record.failureId)}
                  onAccepted={acceptFailure}
                />
              </li>
            );
          })}
        </ul>
      )}

      <div className={styles.footer}>
        <VContextualHint
          label={zh ? "关于恢复语义" : "About recovery semantics"}
          content={zh
            ? "自动推进结束仍未解决的项目才进入面板；重试走与自动恢复同一条命令路径并需二次确认；等待中项目不提供按钮，兄弟评审关闭后会自动推进。"
            : "Items reach this panel only after automatic progress is exhausted; retries reuse the same command path and require a confirm step; waiting items carry no button and advance when the sibling reviews close."}
        />
      </div>
    </VEmbeddedPanel>
  );
}

export function ResearchWorkflowRecoveryEntry({
  teamId,
  lang,
  onOpen,
}: ResearchWorkflowRecoveryEntryProps) {
  const { lang: shellLang } = useShellI18n();
  const zh = zhFrom(lang, shellLang);
  const failuresQuery = useQuery({
    queryKey: queryKeys.hypothesisFirstChainRoundFailures(teamId),
    queryFn: ({ signal }) => fetchHypothesisRoundFailures(teamId, { signal }),
    enabled: Boolean(teamId.trim()),
    staleTime: 10_000,
    refetchInterval: 10_000,
    refetchOnWindowFocus: "always",
  });
  const openCount = failuresQuery.data?.openFailureCount ?? 0;
  if (!teamId.trim() || openCount <= 0) {
    return null;
  }
  return (
    <div className={styles.entryWrap} data-testid="research-recovery-entry">
      <VButton
        type="button"
        variant="secondary"
        density="compact"
        icon={<TriangleAlert size={14} aria-hidden="true" />}
        onClick={onOpen}
        data-testid="research-recovery-entry-open"
      >
        {zh ? `待恢复 ${openCount} 项 · 查看处理` : `${openCount} recoverable · review`}
      </VButton>
    </div>
  );
}

export default ResearchWorkflowRecoveryPanel;
