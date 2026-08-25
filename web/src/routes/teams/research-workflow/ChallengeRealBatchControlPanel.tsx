import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  authorizeChallengeCupRealBatch,
  cancelChallengeCupRealBatch,
  fetchChallengeCupRealBatchStatus,
  pollChallengeCupRealBatch,
  startChallengeCupRealBatch,
} from "../../../api/teamExperiment";
import { queryKeys } from "../../../api/queryKeys";
import type {
  ChallengeCupRealBatchAuthorization,
  ChallengeCupRealBatchPlanId,
  ChallengeCupRealBatchPollResponse,
  ChallengeCupRealBatchProjection,
  ChallengeCupRealBatchStartResponse,
} from "../../../api/types/challengeCup";
import {
  VButton,
  VConfirmDialog,
  VEmbeddedPanel,
  VMetricStrip,
  VStateSurface,
  VStatusChip,
  VStringSelect,
  type VStatusTone,
} from "../../../components/vui";
import styles from "./ChallengeRealBatchControlPanel.styles";

type Language = "zh" | "en";
type ConfirmAction = "authorize" | "start" | "cancel";

const REAL_BATCH_PLANS: readonly {
  planId: ChallengeCupRealBatchPlanId;
  gateId: string;
  labelZh: string;
  labelEn: string;
}[] = [
  { planId: "real-1", gateId: "G1", labelZh: "G1 · 1 题", labelEn: "G1 · 1 question" },
  { planId: "real-5", gateId: "G5", labelZh: "G5 · 5 题", labelEn: "G5 · 5 questions" },
  { planId: "real-12", gateId: "G12", labelZh: "G12 · 12 题", labelEn: "G12 · 12 questions" },
  { planId: "real-125", gateId: "G125", labelZh: "G125 · 125 题", labelEn: "G125 · 125 questions" },
];

type RecentEvent = {
  id: string;
  label: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isProjection(value: unknown, planId: ChallengeCupRealBatchPlanId): value is ChallengeCupRealBatchProjection {
  if (!isRecord(value) || value.schemaVersion !== 1) return false;
  if (value.planId !== planId || typeof value.gateId !== "string" || typeof value.exists !== "boolean") return false;
  if (value.exists === false) return true;
  const summary = value.statusSummary;
  const arrays = [value.completedQuestionIds, value.pendingQuestionIds, value.awaitingApprovalQuestionIds];
  if (
    !isNonNegativeInteger(value.questionCount)
    || !isRecord(summary)
    || [summary.pending, summary.running, summary.succeeded, summary.failed, summary.blocked].some((item) => !isNonNegativeInteger(item))
    || [value.pendingCount, value.succeededCount, value.failedCount, value.blockedCount, value.totalAttempts, value.consecutiveFailures, value.failureBudget].some((item) => !isNonNegativeInteger(item))
    || arrays.some((item) => !Array.isArray(item) || item.some((entry) => typeof entry !== "string"))
    || !isRecord(value.runRefs)
    || typeof value.circuitBreakerOpen !== "boolean"
    || typeof value.cancelled !== "boolean"
    || typeof value.gateComplete !== "boolean"
    || typeof value.lastUpdatedAt !== "string"
    || typeof value.canResume !== "boolean"
  ) {
    return false;
  }
  return Object.values(value.runRefs).every((ref) => (
    isRecord(ref) && typeof ref.runId === "string" && isNonNegativeInteger(ref.attempt)
  ));
}

function normalizeProjection(
  value: unknown,
  planId: ChallengeCupRealBatchPlanId,
): ChallengeCupRealBatchProjection | null {
  if (!isProjection(value, planId)) return null;
  if (value.exists) return value;
  return {
    schemaVersion: value.schemaVersion,
    planId: value.planId,
    gateId: value.gateId,
    exists: false,
    questionCount: 0,
    statusSummary: { pending: 0, running: 0, succeeded: 0, failed: 0, blocked: 0 },
    pendingCount: 0,
    succeededCount: 0,
    failedCount: 0,
    blockedCount: 0,
    totalAttempts: 0,
    completedQuestionIds: [],
    pendingQuestionIds: [],
    runRefs: {},
    awaitingApprovalQuestionIds: [],
    consecutiveFailures: 0,
    failureBudget: 0,
    circuitBreakerOpen: false,
    cancelled: false,
    gateComplete: false,
    lastUpdatedAt: "",
    canResume: false,
  };
}

function isAuthorization(value: unknown, planId: ChallengeCupRealBatchPlanId): value is ChallengeCupRealBatchAuthorization {
  if (!isRecord(value)) return false;
  return value.planId === planId
    && typeof value.authorizationId === "string"
    && Boolean(value.authorizationId.trim())
    && typeof value.teamId === "string"
    && typeof value.scopeHash === "string"
    && typeof value.readinessReportSha256 === "string"
    && typeof value.recordHash === "string"
    && Boolean(value.scopeHash.trim())
    && Boolean(value.readinessReportSha256.trim())
    && Boolean(value.recordHash.trim());
}

function errorText(reason: unknown, fallback: string): string {
  if (reason instanceof Error && reason.message.trim()) return reason.message;
  const text = String(reason || "").trim();
  return text || fallback;
}

function statusLabel(status: ChallengeCupRealBatchProjection, zh: boolean): string {
  if (!status.exists) return zh ? "未创建" : "Not created";
  if (status.cancelled) return zh ? "已取消" : "Cancelled";
  if (status.circuitBreakerOpen) return zh ? "熔断阻塞" : "Circuit breaker";
  if (status.gateComplete) return zh ? "Gate 已完成" : "Gate complete";
  if (status.statusSummary.running > 0) return zh ? "运行中" : "Running";
  if (status.statusSummary.failed > 0 || status.statusSummary.blocked > 0) return zh ? "失败/阻塞" : "Failed/blocked";
  if (status.canResume) return zh ? "可继续" : "Resumable";
  return zh ? "等待启动" : "Awaiting start";
}

function statusTone(status: ChallengeCupRealBatchProjection): VStatusTone {
  if (!status.exists) return "neutral";
  if (status.cancelled || status.circuitBreakerOpen || status.failedCount > 0) return "danger";
  if (status.gateComplete) return "success";
  if (status.statusSummary.running > 0) return "accent";
  if (status.blockedCount > 0 || status.canResume) return "warning";
  return "neutral";
}

function shortHash(value: string): string {
  const normalized = value.trim();
  return normalized ? `${normalized.slice(0, 12)}…` : "—";
}

function formatTime(value: string, zh: boolean): string {
  if (!value) return zh ? "尚无更新时间" : "No update yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(zh ? "zh-CN" : "en-US");
}

export type ChallengeRealBatchControlPanelProps = {
  teamId: string;
  lang?: Language;
};

/**
 * Controlled UI for the server-owned real catalog batches.
 *
 * The panel never treats readiness as authorization. A successful authorize
 * response is held as the local capability fence, while every mutation still
 * remains guarded by the server's durable scope/hash checks.
 */
export function ChallengeRealBatchControlPanel({
  teamId,
  lang = "zh",
}: ChallengeRealBatchControlPanelProps) {
  const zh = lang === "zh";
  const [selectedPlanId, setSelectedPlanId] = useState<ChallengeCupRealBatchPlanId>("real-125");
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const [authorization, setAuthorization] = useState<ChallengeCupRealBatchAuthorization | null>(null);
  const [pollingEnabled, setPollingEnabled] = useState(false);
  const pollingEnabledRef = useRef(false);
  const [events, setEvents] = useState<RecentEvent[]>([]);
  const selectedPlan = REAL_BATCH_PLANS.find((item) => item.planId === selectedPlanId) ?? REAL_BATCH_PLANS[3];
  const statusKey = queryKeys.challengeCupRealBatchStatus(teamId, selectedPlanId);
  const statusQuery = useQuery({
    queryKey: statusKey,
    queryFn: ({ signal }: { signal?: AbortSignal }) => fetchChallengeCupRealBatchStatus(teamId, selectedPlanId, { signal }),
    enabled: Boolean(teamId.trim()),
    staleTime: 15_000,
    retry: false,
  });
  const queryClient = useQueryClient();
  const status = normalizeProjection(statusQuery.data, selectedPlanId);
  const malformed = !statusQuery.isPending && !statusQuery.isError && statusQuery.data !== undefined && !status;

  function addEvent(label: string) {
    setEvents((current) => [
      { id: `${Date.now()}-${current.length}`, label },
      ...current,
    ].slice(0, 5));
  }

  function updateProjection(next: ChallengeCupRealBatchProjection) {
    queryClient.setQueryData(statusKey, next);
  }

  function setPollingState(enabled: boolean) {
    pollingEnabledRef.current = enabled;
    setPollingEnabled(enabled);
  }

  const authorizeMutation = useMutation({
    mutationFn: ({ teamId: mutationTeamId, planId }: { teamId: string; planId: ChallengeCupRealBatchPlanId }) =>
      authorizeChallengeCupRealBatch(mutationTeamId, planId),
    onSuccess: (result: unknown) => {
      if (!isAuthorization(result, selectedPlanId)) {
        setAuthorization(null);
        setConfirmAction(null);
        addEvent(zh ? "授权响应异常 · 状态保持关闭" : "Authorization response invalid · state remains closed");
        return;
      }
      setAuthorization(result);
      setConfirmAction(null);
      addEvent(zh ? `已写入 durable 授权 · scope ${shortHash(result.scopeHash)}` : `Durable authorization recorded · scope ${shortHash(result.scopeHash)}`);
    },
    onError: (reason: unknown) => {
      setAuthorization(null);
      addEvent(zh ? `授权失败 · ${errorText(reason, "服务端拒绝")}` : `Authorization failed · ${errorText(reason, "Rejected by server")}`);
    },
  });

  const startMutation = useMutation({
    mutationFn: ({ teamId: mutationTeamId, planId }: { teamId: string; planId: ChallengeCupRealBatchPlanId }) =>
      startChallengeCupRealBatch(mutationTeamId, planId, {
        confirmed: true,
        concurrency: null,
        maxItems: null,
        failureBudget: null,
      }),
    onSuccess: (result: ChallengeCupRealBatchStartResponse) => {
      const next = normalizeProjection(result, selectedPlanId);
      if (!next) {
        setAuthorization(null);
        setPollingState(false);
        setConfirmAction(null);
        addEvent(zh ? "启动响应异常 · 状态保持关闭" : "Start response invalid · state remains closed");
        return;
      }
      updateProjection(next);
      setConfirmAction(null);
      setPollingState(!next.gateComplete && !next.cancelled && next.canResume);
      const launched = result.launched ?? [];
      addEvent(zh ? `启动完成 · 新派遣 ${launched.length} 个问题` : `Start completed · launched ${launched.length} questions`);
    },
    onError: (reason: unknown) => {
      // A failed start cannot prove the local authorization is still current.
      setAuthorization(null);
      addEvent(zh ? `启动失败 · ${errorText(reason, "服务端拒绝")}` : `Start failed · ${errorText(reason, "Rejected by server")}`);
    },
  });

  const pollMutation = useMutation({
    mutationFn: ({ teamId: mutationTeamId, planId }: { teamId: string; planId: ChallengeCupRealBatchPlanId }) =>
      pollChallengeCupRealBatch(mutationTeamId, planId),
    onSuccess: (result: ChallengeCupRealBatchPollResponse) => {
      const next = normalizeProjection(result, selectedPlanId);
      if (!next) {
        setPollingState(false);
        addEvent(zh ? "后台刷新响应异常 · 状态保持关闭" : "Background poll response invalid · state remains closed");
        return;
      }
      updateProjection(next);
      if (next.gateComplete || next.cancelled || !next.canResume) setPollingState(false);
      const harvested = result.harvested ?? [];
      const launched = result.launched ?? [];
      if (harvested.length || launched.length) {
        addEvent(zh
          ? `后台刷新 · 收获 ${harvested.length} · 新派遣 ${launched.length}`
          : `Background poll · harvested ${harvested.length} · launched ${launched.length}`);
      }
    },
    onError: (reason: unknown) => {
      setPollingState(false);
      addEvent(zh ? `后台刷新失败 · ${errorText(reason, "状态不可用")}` : `Background poll failed · ${errorText(reason, "Status unavailable")}`);
    },
  });

  const cancelMutation = useMutation({
    mutationFn: ({ teamId: mutationTeamId, planId }: { teamId: string; planId: ChallengeCupRealBatchPlanId }) =>
      cancelChallengeCupRealBatch(mutationTeamId, planId, { confirmed: true }),
    onSuccess: (result: ChallengeCupRealBatchProjection) => {
      const next = normalizeProjection(result, selectedPlanId);
      if (!next) {
        setPollingState(false);
        setConfirmAction(null);
        addEvent(zh ? "取消响应异常 · 状态保持关闭" : "Cancel response invalid · state remains closed");
        return;
      }
      updateProjection(next);
      setConfirmAction(null);
      setPollingState(false);
      addEvent(zh ? "批次已取消 · 运行中的问题未被强制终止" : "Batch cancelled · running questions were not force-stopped");
    },
    onError: (reason: unknown) => {
      addEvent(zh ? `取消失败 · ${errorText(reason, "服务端拒绝")}` : `Cancel failed · ${errorText(reason, "Rejected by server")}`);
    },
  });

  useEffect(() => {
    setAuthorization(null);
    setConfirmAction(null);
    setPollingState(false);
    setEvents([]);
  }, [selectedPlanId, teamId]);

  useEffect(() => {
    if (!pollingEnabled || !teamId.trim()) return undefined;
    let disposed = false;
    let timer: number | undefined;

    const scheduleNextPoll = () => {
      if (disposed || !pollingEnabledRef.current) return;
      timer = window.setTimeout(() => {
        timer = undefined;
        if (disposed || !pollingEnabledRef.current) return;
        void (async () => {
          try {
            await pollMutation.mutateAsync({ teamId, planId: selectedPlanId });
          } catch {
            // onError closes the polling loop; the rejection is already surfaced there.
          } finally {
            scheduleNextPoll();
          }
        })();
      }, 15_000);
    };

    scheduleNextPoll();
    return () => {
      disposed = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [pollingEnabled, selectedPlanId, teamId]);

  const anyMutationPending = authorizeMutation.isPending || startMutation.isPending || pollMutation.isPending || cancelMutation.isPending;
  const canAuthorize = Boolean(status && !authorization && !anyMutationPending);
  const canStart = Boolean(
    status
    && authorization
    && !status.cancelled
    && !status.gateComplete
    && !status.circuitBreakerOpen
    && !anyMutationPending,
  );
  const canCancel = Boolean(status?.exists && !status.cancelled && !status.gateComplete && !anyMutationPending);
  const gateOptions = useMemo(
    () => REAL_BATCH_PLANS.map((item) => ({
      value: item.planId,
      label: zh ? item.labelZh : item.labelEn,
    })),
    [zh],
  );

  if (!teamId.trim()) {
    return <VStateSurface tone="empty" density="compact" title={zh ? "真实批次待选择团队" : "Select a team for real batches"} />;
  }
  if (statusQuery.isPending) {
    return <VStateSurface tone="loading" density="compact" title={zh ? "读取真实批次状态" : "Loading real batch state"} />;
  }
  if (statusQuery.isError) {
    return (
      <VStateSurface
        tone="error"
        density="compact"
        title={zh ? "真实批次状态不可用" : "Real batch state unavailable"}
        actions={(
          <VButton type="button" variant="secondary" onClick={() => void statusQuery.refetch()}>
            {zh ? "重试" : "Retry"}
          </VButton>
        )}
      >
        {errorText(statusQuery.error, zh ? "服务端没有返回状态。" : "The server did not return a state projection.")}
      </VStateSurface>
    );
  }
  if (malformed || !status) {
    return (
      <VStateSurface
        tone="unavailable"
        density="compact"
        title={zh ? "真实批次数据格式异常" : "Real batch payload is invalid"}
        actions={(
          <VButton type="button" variant="secondary" onClick={() => void statusQuery.refetch()}>
            {zh ? "重新读取" : "Reload"}
          </VButton>
        )}
      >
        {zh ? "未识别的服务端状态不会被当作成功，也不会开放真实动作。" : "Unknown server state is not treated as success and real actions stay closed."}
      </VStateSurface>
    );
  }

  const confirmationTitle = confirmAction === "authorize"
    ? (zh ? "确认写入科研授权" : "Confirm research authorization")
    : confirmAction === "start"
      ? (zh ? `确认启动真实批次 ${selectedPlan.gateId}` : `Confirm start of ${selectedPlan.gateId} real batch`)
      : (zh ? `确认取消真实批次 ${selectedPlan.gateId}` : `Confirm cancellation of ${selectedPlan.gateId} real batch`);
  const confirmationDescription = confirmAction === "authorize"
    ? (zh ? "授权会绑定当前服务端就绪报告、模型策略和题目范围；realCampaignAllowed=false 仍不会被伪装成已授权。" : "Authorization binds the server readiness report, model policy and question scope; realCampaignAllowed=false is never presented as authorized.")
    : confirmAction === "start"
      ? (zh ? "这会在服务端校验 durable 授权/hash 后派遣真实科研运行。请确认当前 Gate、题目范围和安全边界。" : "The server will verify the durable authorization/hash before dispatching real research runs. Confirm the gate, question scope and safety boundary.")
      : (zh ? "取消会阻止未启动题目继续派遣；已经运行中的问题不会被强制终止。" : "Cancellation stops new launches; already-running questions are not force-stopped.");
  const confirmPending = confirmAction === "authorize"
    ? authorizeMutation.isPending
    : confirmAction === "start"
      ? startMutation.isPending
      : cancelMutation.isPending;
  const confirmDisabled = confirmAction === "authorize"
    ? !canAuthorize
    : confirmAction === "start"
      ? !canStart
      : !canCancel;

  return (
    <VEmbeddedPanel
      ariaLabel={zh ? "挑战杯真实批次控制" : "Challenge Cup real batch controls"}
      className={styles.root}
      data-testid="challenge-real-batch-control"
    >
      <div className={styles.header}>
        <div className={styles.titleBlock}>
          <strong className={styles.title}>{zh ? "真实批次控制" : "Real batch controls"}</strong>
          <span className={styles.summary}>
            {zh ? "只允许服务端持久化授权后的 G1 → G5 → G12 → G125 逐级运行。" : "Only server-authorized progressive G1 → G5 → G12 → G125 runs are allowed."}
          </span>
        </div>
        <div className={styles.headerActions}>
          <VStatusChip tone={statusTone(status)}>{statusLabel(status, zh)}</VStatusChip>
          <VButton type="button" variant="ghost" density="compact" onClick={() => void statusQuery.refetch()}>
            {zh ? "读取状态" : "Refresh state"}
          </VButton>
        </div>
      </div>

      <div className={styles.gateToolbar}>
        <VStringSelect
          ariaLabel={zh ? "选择真实批次 Gate" : "Select real batch gate"}
          className={styles.gateSelect}
          value={selectedPlanId}
          options={gateOptions}
          onValueChange={(next) => setSelectedPlanId(next as ChallengeCupRealBatchPlanId)}
        />
        <span className={styles.gateSequence} aria-label={zh ? "Gate 顺序" : "Gate sequence"}>
          {REAL_BATCH_PLANS.map((item, index) => (
            <span key={item.planId} className={item.planId === selectedPlanId ? styles.gateActive : styles.gateItem}>
              {item.gateId}{index < REAL_BATCH_PLANS.length - 1 ? " → " : ""}
            </span>
          ))}
        </span>
      </div>

      {!status.exists ? (
        <div className={styles.empty} data-testid="real-batch-empty">
          <strong>{selectedPlan.gateId} {zh ? "尚未创建真实批次" : "real batch has not been created"}</strong>
          <span>{zh ? "先完成明确授权；授权成功后才能启动，当前不会自动触发任何运行。" : "Record explicit authorization first; nothing starts automatically."}</span>
        </div>
      ) : (
        <>
          <VMetricStrip
            ariaLabel={zh ? "真实批次进度" : "Real batch progress"}
            className={styles.metrics}
            metrics={[
              { id: "progress", label: zh ? "已完成" : "Completed", value: `${status.succeededCount} / ${status.questionCount}`, tone: status.gateComplete ? "success" : "accent" },
              { id: "pending", label: zh ? "待处理" : "Pending", value: status.pendingCount, tone: status.pendingCount ? "warning" : "neutral" },
              { id: "running", label: zh ? "运行中" : "Running", value: status.statusSummary.running, tone: status.statusSummary.running ? "accent" : "neutral" },
              { id: "blocked", label: zh ? "阻塞" : "Blocked", value: status.blockedCount + status.failedCount, tone: status.blockedCount + status.failedCount ? "danger" : "success" },
            ]}
          />
          <div className={styles.progressMeta}>
            <span>{zh ? `总尝试 ${status.totalAttempts} 次 · 失败预算 ${status.failureBudget}` : `${status.totalAttempts} attempts · failure budget ${status.failureBudget}`}</span>
            <span>{zh ? `最近更新 ${formatTime(status.lastUpdatedAt, zh)}` : `Updated ${formatTime(status.lastUpdatedAt, zh)}`}</span>
          </div>
        </>
      )}

      <div className={styles.boundary} role="note">
        <strong>{zh ? "授权边界" : "Authorization boundary"}</strong>
        <span>{zh ? "readiness 的 realCampaignAllowed=false 只表示尚未放行真实 Campaign；它不等于授权成功，当前授权/hash 仍以服务端响应为准。" : "readiness realCampaignAllowed=false means the real Campaign is not open; it is not authorization. The server response remains authoritative."}</span>
        {authorization ? <span className={styles.authorizationMeta}>{zh ? `本次会话已取得授权 · record ${shortHash(authorization.recordHash)}` : `Authorized in this session · record ${shortHash(authorization.recordHash)}`}</span> : <span className={styles.authorizationMeta}>{zh ? "当前尚未视为已授权。" : "Not authorized yet."}</span>}
      </div>

      {status.exists && (status.failedCount > 0 || status.blockedCount > 0 || status.awaitingApprovalQuestionIds.length > 0 || status.circuitBreakerOpen) ? (
        <div className={styles.blockers} role="status" data-testid="real-batch-blockers">
          <strong>{zh ? "当前阻塞" : "Current blockers"}</strong>
          {status.failedCount > 0 ? <span>{zh ? `失败 ${status.failedCount} 个问题` : `${status.failedCount} failed question(s)`}</span> : null}
          {status.blockedCount > 0 ? <span>{zh ? `阻塞 ${status.blockedCount} 个问题` : `${status.blockedCount} blocked question(s)`}</span> : null}
          {status.awaitingApprovalQuestionIds.length > 0 ? <span>{zh ? `待人工审核 ${status.awaitingApprovalQuestionIds.length} 个问题` : `${status.awaitingApprovalQuestionIds.length} awaiting human approval`}</span> : null}
          {status.circuitBreakerOpen ? <span>{zh ? "连续失败已触发熔断，禁止继续派遣。" : "The circuit breaker is open; new launches are blocked."}</span> : null}
        </div>
      ) : null}

      <div className={styles.actions} aria-live="polite">
        <VButton
          type="button"
          variant="secondary"
          isDisabled={!canAuthorize}
          onClick={() => setConfirmAction("authorize")}
          disabledReason={zh ? "需先由服务端确认就绪边界；授权动作仍需确认。" : "The server must accept the readiness boundary; authorization still requires confirmation."}
        >
          {authorization ? (zh ? "已取得授权" : "Authorized") : (zh ? "申请科研授权" : "Request authorization")}
        </VButton>
        <VButton
          type="button"
          variant="primary"
          isDisabled={!canStart}
          onClick={() => setConfirmAction("start")}
          disabledReason={zh ? "必须先取得当前 Gate 的 durable 授权/hash。" : "A current durable authorization/hash is required first."}
        >
          {status.canResume ? (zh ? "继续真实批次" : "Resume real batch") : (zh ? "开始真实批次" : "Start real batch")}
        </VButton>
        {status.exists && !status.gateComplete && !status.cancelled ? (
          <VButton
            type="button"
            variant="danger"
            isDisabled={!canCancel}
            onClick={() => setConfirmAction("cancel")}
          >
            {zh ? "取消批次" : "Cancel batch"}
          </VButton>
        ) : null}
        {pollingEnabled ? <span className={styles.pollingHint} role="status">{zh ? "后台每 15 秒刷新，不会重复点击主动作。" : "Background polling every 15s; no repeated primary click."}</span> : null}
      </div>

      <div className={styles.events} data-testid="real-batch-events">
        <div className={styles.eventsHeader}>
          <strong>{zh ? "最近事件" : "Recent events"}</strong>
          <span>{zh ? "仅显示本次页面会话的有界操作反馈" : "Bounded feedback from this page session"}</span>
        </div>
        {events.length === 0 ? (
          <span className={styles.eventEmpty}>{status.exists ? (zh ? "暂无本次会话操作；状态已从持久化存储读取。" : "No page-session action yet; state was read from durable storage.") : (zh ? "暂无事件；挂载不会触发 mutation。" : "No events; mounting does not trigger mutations.")}</span>
        ) : (
          <ul className={styles.eventList}>
            {events.map((event) => <li key={event.id}>{event.label}</li>)}
          </ul>
        )}
      </div>

      <VConfirmDialog
        open={confirmAction !== null}
        onOpenChange={(open) => { if (!open) setConfirmAction(null); }}
        title={confirmationTitle}
        description={confirmationDescription}
        tone={confirmAction === "cancel" ? "danger" : "neutral"}
        confirmLabel={confirmAction === "authorize" ? (zh ? "确认授权" : "Confirm authorization") : confirmAction === "start" ? (zh ? "确认启动" : "Confirm start") : (zh ? "确认取消" : "Confirm cancellation")}
        cancelLabel={zh ? "返回" : "Back"}
        confirmPending={confirmPending}
        confirmDisabled={confirmDisabled}
        onConfirm={() => {
          if (confirmAction === "authorize") authorizeMutation.mutate({ teamId, planId: selectedPlanId });
          if (confirmAction === "start") startMutation.mutate({ teamId, planId: selectedPlanId });
          if (confirmAction === "cancel") cancelMutation.mutate({ teamId, planId: selectedPlanId });
        }}
      >
        <div className={styles.confirmBody}>
          <span>{zh ? `目标 Gate：${selectedPlan.gateId} · 计划：${selectedPlanId}` : `Target gate: ${selectedPlan.gateId} · plan: ${selectedPlanId}`}</span>
          {status.exists ? <span>{zh ? `当前进度：${status.succeededCount}/${status.questionCount}，运行中 ${status.statusSummary.running}` : `Progress: ${status.succeededCount}/${status.questionCount}, running ${status.statusSummary.running}`}</span> : null}
          {confirmAction === "start" && !authorization ? <span role="alert">{zh ? "缺少本次会话取得的 durable 授权，启动保持关闭。" : "No durable authorization from this session; start remains closed."}</span> : null}
        </div>
      </VConfirmDialog>
    </VEmbeddedPanel>
  );
}

export default ChallengeRealBatchControlPanel;
