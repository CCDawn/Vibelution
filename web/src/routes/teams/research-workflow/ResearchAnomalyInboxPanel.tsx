import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  executeHypothesisFirstInboxExtendBudget,
  fetchHypothesisFirstAnomalyInbox,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import type {
  AnomalyInboxExtendBudgetAction,
  AnomalyInboxItem,
  AnomalySeverity,
} from "../../../api/types/hypothesisFirst";
import {
  VButton,
  VContextualHint,
  VEmbeddedPanel,
  VNativeButton,
  VStateSurface,
  VStatusChip,
  type VStatusTone,
} from "../../../components/vui";
import { useShellI18n } from "../../../i18n/useShellI18n";
import styles from "./ResearchAnomalyInboxPanel.styles";

type Language = "zh" | "en";

export type ResearchAnomalyInboxDeepLink = {
  questionId: string;
  runId: string;
  /** Present only for node-scoped items (e.g. retry_budget_exhausted). */
  nodeId: string;
};

export type ResearchAnomalyInboxPanelProps = {
  teamId: string;
  /** Empty = team scope; the server returns the legal empty inbox then. */
  questionId?: string;
  lang?: Language;
  /** Click-through target; absent means rows render read-only. */
  onOpenItem?: (target: ResearchAnomalyInboxDeepLink) => void;
};

const KIND_LABELS: Record<string, { zh: string; en: string }> = {
  blocked_run: { zh: "运行阻塞", en: "Blocked run" },
  heartbeat_stale: { zh: "心跳超时", en: "Heartbeat stale" },
  needs_human_gate: { zh: "等待人工", en: "Human gate" },
  claim_disputed: { zh: "主张存疑", en: "Disputed claim" },
  review_disagreement_escalation: { zh: "评审分歧升级", en: "Review escalation" },
  drift_sentinel_hit: { zh: "抽样漂移", en: "Drift sentinel" },
  budget_exhausted: { zh: "预算耗尽", en: "Budget exhausted" },
  retry_budget_exhausted: { zh: "重试预算耗尽", en: "Retries exhausted" },
};

const ACTION_LABELS: Record<string, { zh: string; en: string }> = {
  retry_node: { zh: "建议动作：重试节点", en: "Suggested: retry node" },
  reconcile_run: { zh: "建议动作：重建运行", en: "Suggested: reconcile run" },
  archive_run: { zh: "建议动作：归档运行", en: "Suggested: archive run" },
  fork_revision: { zh: "建议动作：分叉修订", en: "Suggested: fork revision" },
};

const SEVERITY_ORDER: AnomalySeverity[] = ["critical", "high", "medium"];

const SEVERITY_META: Record<AnomalySeverity, { tone: VStatusTone; zh: string; en: string }> = {
  critical: { tone: "danger", zh: "严重", en: "Critical" },
  high: { tone: "warning", zh: "高", en: "High" },
  medium: { tone: "neutral", zh: "中", en: "Medium" },
};

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason || "unavailable");
}

function formatTime(value: string, zh: boolean): string {
  if (!value) return zh ? "无时间" : "No time";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(zh ? "zh-CN" : "en-US");
}

function formatTokens(value: number): string {
  return value.toLocaleString("en-US");
}

function kindLabel(kind: string, zh: boolean): string {
  return KIND_LABELS[kind]?.[zh ? "zh" : "en"] ?? kind;
}

function actionLabel(action: string | null, zh: boolean): string {
  if (!action) return "";
  return ACTION_LABELS[action]?.[zh ? "zh" : "en"] ?? `${zh ? "建议动作" : "Suggested"}: ${action}`;
}

/** Human-readable scope line: 题目 / run / node / meeting, whichever exist. */
export function anomalyInboxScopeText(item: AnomalyInboxItem, zh: boolean): string {
  const scope = item.scope;
  const parts: string[] = [];
  if (scope.questionId) parts.push(`${zh ? "题" : "Q"} ${scope.questionId}`);
  if (scope.runId) parts.push(`run ${scope.runId}`);
  if (scope.nodeId) parts.push(`node ${scope.nodeId}`);
  if (scope.meetingRoundId) parts.push(`${zh ? "会议" : "meeting"} ${scope.meetingRoundId}`);
  return parts.join(" · ");
}

/**
 * Click-through target for one inbox row. A run-scoped anomaly lands in the
 * run context (FormalRuntimeActionBody renders only when the URL carries
 * runId); a question-scoped one lands on the question review surface.
 */
export function anomalyInboxDeepLink(
  item: AnomalyInboxItem,
  fallbackQuestionId: string,
): ResearchAnomalyInboxDeepLink | null {
  const questionId = (item.scope.questionId || fallbackQuestionId).trim();
  const runId = item.scope.runId.trim();
  if (!questionId) return null;
  return { questionId, runId, nodeId: item.scope.nodeId.trim() };
}

function anomalyItemKey(item: AnomalyInboxItem): string {
  const scope = item.scope;
  return [item.kind, scope.questionId, scope.runId, scope.nodeId, scope.meetingRoundId].join("|");
}

type AnomalyInboxExtendCtaProps = {
  teamId: string;
  questionId: string;
  action: AnomalyInboxExtendBudgetAction;
  zh: boolean;
  /** Fires after a confirmed execution so the parent refreshes the inbox. */
  onExtended: () => void;
};

/**
 * One-click extend CTA (误触防护): the amount is displayed up front, the
 * first click only arms the confirmation, and the execution itself sends the
 * explicit `confirmed: true` flag — the server refuses anything else (428).
 */
export function AnomalyInboxExtendCta({
  teamId,
  questionId,
  action,
  zh,
  onExtended,
}: AnomalyInboxExtendCtaProps) {
  const [armed, setArmed] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [errorText, setErrorText] = useState("");
  const params = action.params;
  const extension = `+${formatTokens(params.suggestedExtensionTokens)} tokens`;

  async function execute() {
    if (executing) return;
    setExecuting(true);
    setErrorText("");
    try {
      await executeHypothesisFirstInboxExtendBudget(teamId, {
        questionId,
        runId: params.runId,
        nodeId: params.nodeId,
        stageId: params.stageId,
        stageLimitTokens: params.stageLimitTokens,
        suggestedExtensionTokens: params.suggestedExtensionTokens,
        confirmed: true,
      });
      setArmed(false);
      onExtended();
    } catch (reason) {
      setErrorText(errorMessage(reason));
    } finally {
      setExecuting(false);
    }
  }

  return (
    <span className={styles.cta} data-testid="anomaly-extend-cta">
      <span className={styles.ctaAmount}>
        <span className={styles.ctaAmountValue}>{extension}</span>
        <span>
          {zh
            ? `阶段 ${params.stageId} 补预算（新上限 ${formatTokens(params.newStageTokens)}），随后可重试节点`
            : `Top up stage ${params.stageId} (new limit ${formatTokens(params.newStageTokens)}), then retry the node`}
        </span>
      </span>
      {armed ? (
        <span className={styles.ctaAmount}>
          <VButton
            type="button"
            variant="danger"
            density="compact"
            isDisabled={executing}
            data-testid="anomaly-extend-confirm"
            onClick={() => void execute()}
          >
            {zh ? "确认补预算" : "Confirm top-up"}
          </VButton>
          <VButton
            type="button"
            variant="ghost"
            density="compact"
            isDisabled={executing}
            data-testid="anomaly-extend-cancel"
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
          data-testid="anomaly-extend-arm"
          onClick={() => setArmed(true)}
        >
          {zh ? "一键补预算" : "Top up budget"}
        </VButton>
      )}
      <span className={styles.ctaConfirmHint}>
        {action.confirmHint}
      </span>
      {errorText ? (
        <span className={styles.ctaError} data-testid="anomaly-extend-error">
          {zh ? "补预算失败：" : "Top-up failed: "}
          {errorText}
        </span>
      ) : null}
    </span>
  );
}

export function ResearchAnomalyInboxPanel({
  teamId,
  questionId = "",
  lang,
  onOpenItem,
}: ResearchAnomalyInboxPanelProps) {
  const { lang: shellLang } = useShellI18n();
  const resolvedLang = lang ?? shellLang;
  const zh = resolvedLang === "zh";
  const queryClient = useQueryClient();
  const normalizedQuestionId = questionId.trim().toUpperCase();
  const inboxQuery = useQuery({
    queryKey: queryKeys.hypothesisFirstChainAnomalyInbox(teamId, normalizedQuestionId),
    queryFn: ({ signal }) =>
      fetchHypothesisFirstAnomalyInbox(teamId, normalizedQuestionId, { signal }),
    enabled: Boolean(teamId.trim()),
    staleTime: 10_000,
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });
  const items = inboxQuery.data?.inbox.items ?? [];
  const groups = useMemo(() => (
    SEVERITY_ORDER
      .map((severity) => ({
        severity,
        meta: SEVERITY_META[severity],
        items: items.filter((item) => item.severity === severity),
      }))
      .filter((group) => group.items.length > 0)
  ), [items]);

  if (!teamId.trim()) {
    return <VStateSurface tone="empty" density="compact" title={zh ? "异常收件箱待选择团队" : "Select a team for the anomaly inbox"} />;
  }
  if (inboxQuery.isPending) {
    return <VStateSurface tone="loading" density="compact" title={zh ? "读取异常收件箱" : "Loading anomaly inbox"} />;
  }
  if (inboxQuery.isError || !inboxQuery.data) {
    return (
      <VStateSurface
        tone="error"
        density="compact"
        title={zh ? "异常收件箱不可用" : "Anomaly inbox unavailable"}
        actions={(
          <VButton type="button" variant="secondary" onClick={() => void inboxQuery.refetch()}>
            {zh ? "重试" : "Retry"}
          </VButton>
        )}
      >
        {errorMessage(inboxQuery.error)}
      </VStateSurface>
    );
  }

  return (
    <VEmbeddedPanel
      ariaLabel={zh ? "异常收件箱" : "Anomaly inbox"}
      className={styles.root}
      data-testid="research-anomaly-inbox"
    >
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <strong className={styles.title}>{zh ? "异常收件箱" : "Anomaly inbox"}</strong>
          <span className={styles.summary}>
            {normalizedQuestionId
              ? (zh ? `${normalizedQuestionId} 的阻塞 / 风险 / 待人工信号，服务端排序。` : `Blocking / risk / human signals for ${normalizedQuestionId}, server-ranked.`)
              : (zh ? "未选择题目：选择题目后显示该题的异常队列。" : "No question selected: pick a question to see its anomaly queue.")}
          </span>
        </div>
        <div className={styles.headerActions}>
          {groups.map((group) => (
            <VStatusChip key={group.severity} tone={group.meta.tone} data-testid={`anomaly-count-${group.severity}`}>
              {zh ? group.meta.zh : group.meta.en} {group.items.length}
            </VStatusChip>
          ))}
          <VButton type="button" variant="ghost" density="compact" onClick={() => void inboxQuery.refetch()}>
            {zh ? "刷新" : "Refresh"}
          </VButton>
        </div>
      </div>

      {items.length === 0 ? (
        <div className={styles.empty} data-testid="anomaly-inbox-empty">
          <VStateSurface
            tone="empty"
            density="compact"
            title={normalizedQuestionId ? (zh ? "无异常" : "No anomalies") : (zh ? "未选择题目" : "No question selected")}
          >
            {normalizedQuestionId
              ? (zh ? "当前题目没有命中阻塞、心跳、预算或待人工信号。" : "No blocking, heartbeat, budget or human-gate signals hit this question.")
              : (zh ? "异常队列按题目聚合；先在画布或进度面板选择一道题。" : "The queue aggregates per question; select one first.")}
          </VStateSurface>
        </div>
      ) : (
        <div className={styles.groups}>
          {groups.map((group) => (
            <section key={group.severity} className={styles.group} data-testid={`anomaly-group-${group.severity}`}>
              <div className={styles.groupHeader}>
                <VStatusChip tone={group.meta.tone}>
                  {zh ? group.meta.zh : group.meta.en} · {group.items.length}
                </VStatusChip>
              </div>
              <ul className={styles.list}>
                {group.items.map((item) => {
                  const action = item.action ?? null;
                  // A row with an interactive CTA must not nest buttons inside
                  // the row-level click-through button, so it renders plain.
                  const link = onOpenItem && !action ? anomalyInboxDeepLink(item, normalizedQuestionId) : null;
                  const scopeText = anomalyInboxScopeText(item, zh);
                  const key = `${anomalyItemKey(item)}:${item.lastSeenAt}`;
                  const body = (
                    <>
                      <span className={styles.itemTop}>
                        <span className={styles.kindLabel}>{kindLabel(item.kind, zh)}</span>
                        {scopeText ? <span className={styles.scope}>{scopeText}</span> : null}
                        <span className={styles.lastSeen}>{zh ? "最近" : "seen"} {formatTime(item.lastSeenAt, zh)}</span>
                      </span>
                      <span className={styles.itemSummary}>{item.summary}</span>
                      {actionLabel(item.recommendedAction, zh) ? (
                        <span className={styles.recommendation}>{actionLabel(item.recommendedAction, zh)}</span>
                      ) : null}
                      {action ? (
                        <AnomalyInboxExtendCta
                          teamId={teamId}
                          questionId={normalizedQuestionId}
                          action={action}
                          zh={zh}
                          onExtended={() => {
                            void queryClient.invalidateQueries({
                              queryKey: queryKeys.hypothesisFirstChainAnomalyInbox(
                                teamId,
                                normalizedQuestionId,
                              ),
                            });
                          }}
                        />
                      ) : null}
                    </>
                  );
                  return (
                    <li key={key} className={styles.row}>
                      {link ? (
                        <VNativeButton
                          className={styles.rowButton}
                          data-testid="anomaly-inbox-row-link"
                          onClick={() => onOpenItem?.(link)}
                          aria-label={`${kindLabel(item.kind, zh)} · ${scopeText}`}
                        >
                          {body}
                        </VNativeButton>
                      ) : (
                        <div className={styles.rowPlain} data-testid="anomaly-inbox-row-plain">{body}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
      )}

      <div className={styles.footer}>
        <VContextualHint
          label={zh ? "关于严重级排序" : "About severity order"}
          content={zh
            ? "收件箱由服务端投影并冻结排序：critical（无法自行推进）→ high（停滞或结论不可信）→ medium（风险/审计信号）。同一级内按最近活动时间倒序。点击条目跳转到对应题目或运行上下文。"
            : "The inbox is a server-side projection with a frozen order: critical (cannot advance) → high (stalled or untrusted verdict) → medium (risk/audit signals). Within one severity the newest activity comes first. Clicking an item opens its question or run context."}
        />
      </div>
    </VEmbeddedPanel>
  );
}

export default ResearchAnomalyInboxPanel;
