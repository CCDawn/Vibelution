import "../design/route-css/evolution.tailwind.css";

import { useQuery } from "@tanstack/react-query";
import { Check, GitCommitHorizontal, RotateCcw, Square, Target, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type {
  EvolutionWorkflowStep,
  SelfEvolutionAutonomousLoopRun,
  SelfEvolutionOverview,
  SelfObservationRun,
  SelfObservationRunStartRequest,
  SessionDetail,
  SupervisedWorktreeRun,
} from "../api/types";
import { queryKeys } from "../api/queryKeys";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import {
  VButton,
  VDialog,
  VNativeInput,
  VNativeTextarea,
  VStateSurface,
  VStatusChip,
} from "../components/vui";
import { avatarImageUrlFrom, avatarInitials } from "./chat/chatRoutePresentation";
import { fetchSessionDetailWindow } from "./chat/chatSessionDetailHelpers";
import { ChatReadOnlySessionWorkspace } from "./chat/ChatReadOnlySessionWorkspace";
import { mergeSessionDetailMessageWindow } from "./chatSessionState";
import {
  SELF_EVOLUTION_AUTONOMOUS_PHASES,
  selfEvolutionAutonomousPhaseIndex,
} from "./SelfEvolutionAutonomousLoopPanel";
import {
  SupervisedConversationWorkspace,
  type SupervisedConversationWorkspaceProps,
  type SupervisedConversationWorkspaceStep,
} from "./SupervisedConversationWorkspace";
import styles from "./SelfEvolutionConversationWorkspace.styles";

export type SelfEvolutionRunKind = "autonomous" | "observation" | "worktree";

type WorkspaceNavigation = Pick<
  SupervisedConversationWorkspaceProps,
  "activeTrack" | "onTrackChange" | "trackAvailability" | "runGroups"
>;

type Props = {
  lang: "zh" | "en";
  workspaceNavigation: WorkspaceNavigation;
  selectedRunKind: SelfEvolutionRunKind | null;
  overview?: SelfEvolutionOverview;
  autonomousRun?: SelfEvolutionAutonomousLoopRun | null;
  observationRun?: SelfObservationRun | null;
  worktreeRun?: SupervisedWorktreeRun | null;
  phaseSelections?: Record<string, string>;
  onPhaseSelect: (runKey: string, phaseId: string) => void;
  goalInput: string;
  onGoalInputChange: (value: string) => void;
  onStartRun: () => void;
  onAutonomousAction: (runId: string, action: "approve" | "reject" | "retry_cleanup", comment?: string) => void;
  onStartObservation: (payload: SelfObservationRunStartRequest) => void;
  onTerminateObservation: (runId: string) => void;
  onWorktreeAction: (runId: string, action: string) => void;
  onHistory: () => void;
  onSettings: () => void;
  onLibrary: () => void;
  startPending: boolean;
  observationStartPending: boolean;
  observationActionPending: boolean;
  worktreeActionPending: boolean;
  autonomousActionPending: boolean;
  startWorktreeError: string;
  observationStartError: string;
  observationActionError: string;
  worktreeActionError: string;
  autonomousActionError: string;
  actionFeedback: string;
  runLocked: boolean;
  worktreeRunLocked: boolean;
  loading: boolean;
  loadError?: string;
  onRetry?: () => void;
};

export type SelfEvolutionWorkspacePhase = {
  id: string;
  label: string;
  statusLabel: string;
  current: boolean;
  disabled: boolean;
  sessionId: string;
  summary: string;
};

type Confirmation =
  | { kind: "start-autonomous" }
  | { kind: "start-observation" }
  | { kind: "autonomous-action"; runId: string; action: "approve" | "reject" | "retry_cleanup" }
  | { kind: "terminate-observation"; runId: string }
  | { kind: "worktree-action"; runId: string; action: string };

function text(value: unknown) {
  return String(value ?? "").trim();
}

function statusLabel(status: string | null | undefined, lang: "zh" | "en") {
  const key = text(status).toLowerCase();
  const labels: Record<string, [string, string]> = {
    queued: ["排队中", "Queued"], running: ["运行中", "Running"], stopping: ["停止中", "Stopping"],
    awaiting_user_approval: ["等待审查", "Awaiting review"], completed: ["已完成", "Completed"],
    done: ["已完成", "Done"], failed: ["已中断", "Interrupted"], cancelled: ["已取消", "Cancelled"],
    pending: ["待开始", "Pending"], approved: ["已批准", "Approved"], rejected: ["已拒绝", "Rejected"],
  };
  return labels[key]?.[lang === "zh" ? 0 : 1] || text(status) || (lang === "zh" ? "未知" : "Unknown");
}

function formatEvidence(value: unknown) {
  if (typeof value === "string") return value;
  try { return JSON.stringify(value, null, 2); } catch { return String(value ?? ""); }
}

function phaseState(done: boolean, current: boolean, interrupted: boolean, lang: "zh" | "en") {
  if (interrupted && current) return lang === "zh" ? "中断" : "Interrupted";
  if (done) return lang === "zh" ? "已完成" : "Done";
  if (current) return lang === "zh" ? "当前" : "Current";
  return lang === "zh" ? "未开始" : "Not started";
}

export function buildSelfEvolutionConversationPhases(
  kind: SelfEvolutionRunKind | null,
  run: SelfEvolutionAutonomousLoopRun | SelfObservationRun | SupervisedWorktreeRun | null,
  lang: "zh" | "en",
): SelfEvolutionWorkspacePhase[] {
  if (!kind || !run) return [];
  if (kind === "autonomous") {
    const autonomous = run as SelfEvolutionAutonomousLoopRun;
    const currentIndex = selfEvolutionAutonomousPhaseIndex(autonomous.phase);
    const failed = autonomous.status === "failed";
    const completed = autonomous.status === "completed" && autonomous.phase === "completed";
    const sessionByPhase: Record<string, string> = {
      observing: text(autonomous.observation?.conversationSessionId),
      planning: text(autonomous.plan?.conversationSessionId),
      evolving: text(autonomous.candidate?.conversationSessionId),
    };
    const summaryByPhase: Record<string, string> = {
      observing: text(autonomous.observation?.summary),
      planning: text(autonomous.plan?.summary),
      evolving: text(autonomous.candidate?.summary),
      reporting: text(autonomous.resultReport?.summary),
      integrating: text(autonomous.integration?.commitSha),
      completed: text(autonomous.integration?.commitSha),
    };
    return SELF_EVOLUTION_AUTONOMOUS_PHASES.map((phase, index) => {
      const current = index === currentIndex;
      const sessionId = sessionByPhase[phase.id] || "";
      return {
        id: phase.id,
        label: lang === "zh" ? phase.zh : phase.en,
        statusLabel: phaseState(completed || index < currentIndex, current, failed, lang),
        current,
        disabled: !sessionId,
        sessionId,
        summary: summaryByPhase[phase.id] || "",
      };
    });
  }
  if (kind === "observation") {
    const observation = run as SelfObservationRun;
    const sessionId = text(observation.conversationSessionId);
    return [{
      id: "observation",
      label: lang === "zh" ? "观察会话" : "Observation conversation",
      statusLabel: statusLabel(observation.status, lang),
      current: ["queued", "running"].includes(text(observation.status).toLowerCase()),
      disabled: !sessionId,
      sessionId,
      summary: text(observation.report || observation.latestMessage),
    }];
  }

  const worktree = run as SupervisedWorktreeRun;
  const workflowSteps: EvolutionWorkflowStep[] = worktree.workflowSteps?.length
    ? worktree.workflowSteps
    : [{
        id: "self_evolution",
        label: lang === "zh" ? "自进化" : "Self-evolution",
        ownerKind: "agent",
        role: "candidate",
        status: worktree.status,
        current: !["done", "completed", "failed", "cancelled"].includes(text(worktree.status).toLowerCase()),
        summary: worktree.latestMessage || "",
        livePreview: worktree.latestMessage || "",
        metrics: {},
        conversationSessionId: "",
        chatRoute: "",
        conversationMessages: [],
      }];
  return workflowSteps.map((step) => ({
    id: String(step.id),
    label: step.label || String(step.id),
    statusLabel: statusLabel(step.status, lang),
    current: Boolean(step.current),
    disabled: step.ownerKind === "human" || !text(step.conversationSessionId),
    sessionId: text(step.conversationSessionId),
    summary: text(step.summary),
  }));
}

function runTitle(run: SupervisedWorktreeRun) {
  return text(run.selfEvolutionOrigin?.goal) || text(run.latestMessage) || run.runId;
}

function actionEnabled(run: SupervisedWorktreeRun | null, key: string) {
  return Boolean(run?.actionStates?.[key]?.enabled);
}

export function canConfirmAutonomousAction(input: {
  action: "approve" | "reject" | "retry_cleanup";
  requestedRunId: string;
  selectedRun: SelfEvolutionAutonomousLoopRun | null | undefined;
  pending: boolean;
}) {
  const { action, requestedRunId, selectedRun, pending } = input;
  if (!selectedRun || selectedRun.runId !== requestedRunId || pending) return false;
  if (action === "approve") {
    return selectedRun.status === "awaiting_user_approval"
      || selectedRun.status === "failed" && selectedRun.phase === "integration_failed";
  }
  if (action === "reject") return selectedRun.status === "awaiting_user_approval";
  return selectedRun.phase === "cleanup_failed";
}

function EvidenceList({ rows, empty }: { rows: Array<{ label: string; value: unknown }>; empty: string }) {
  return rows.length ? <div className={styles.evidenceList}>
    {rows.map((row, index) => <article className={styles.evidenceRow} key={row.label + ":" + index}>
      <span className={styles.evidenceLabel}>{row.label}</span>
      <pre className={styles.evidenceValue}>{formatEvidence(row.value)}</pre>
    </article>)}
  </div> : <p className={styles.emptyEvidence}>{empty}</p>;
}

export function SelfEvolutionConversationWorkspace({
  lang, workspaceNavigation, selectedRunKind, overview,
  autonomousRun = null, observationRun = null, worktreeRun = null,
  phaseSelections = {}, onPhaseSelect,
  goalInput, onGoalInputChange, onStartRun, onAutonomousAction,
  onStartObservation, onTerminateObservation, onWorktreeAction,
  onHistory, onSettings, onLibrary,
  startPending, observationStartPending, observationActionPending,
  worktreeActionPending, autonomousActionPending,
  startWorktreeError, observationStartError, observationActionError,
  worktreeActionError, autonomousActionError, actionFeedback,
  runLocked, worktreeRunLocked, loading, loadError = "", onRetry,
}: Props) {
  const pageVisible = usePageVisibility();
  const [setupOpen, setSetupOpen] = useState(false);
  const [setupMode, setSetupMode] = useState<"autonomous" | "observation">("autonomous");
  const [sourceOpen, setSourceOpen] = useState(false);
  const [observationGoal, setObservationGoal] = useState("");
  const [observationInputMode, setObservationInputMode] = useState<"prompt" | "blank">("prompt");
  const [observationDuration, setObservationDuration] = useState("300");
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [guardNotice, setGuardNotice] = useState("");

  const selectedRun = selectedRunKind === "autonomous" ? autonomousRun
    : selectedRunKind === "observation" ? observationRun
      : selectedRunKind === "worktree" ? worktreeRun : null;
  const runId = text(selectedRun?.runId);
  const runKey = selectedRunKind ? selectedRunKind + ":" + (runId || "new") : "self:none";
  const previousRunKey = useRef(runKey);
  useEffect(() => {
    if (previousRunKey.current !== runKey && selectedRun) setSetupOpen(false);
    previousRunKey.current = runKey;
  }, [runKey, selectedRun]);
  const phases = useMemo(() => buildSelfEvolutionConversationPhases(selectedRunKind, selectedRun, lang), [selectedRunKind, selectedRun, lang]);
  const currentPhase = phases.find((phase) => phase.current);
  const latestSessionPhase = [...phases].reverse().find((phase) => phase.sessionId);
  const followPhase = currentPhase?.sessionId ? currentPhase : latestSessionPhase;
  const savedPhaseId = phaseSelections[runKey];
  const selectedPhase = phases.find((phase) => phase.id === savedPhaseId && phase.sessionId)
    || followPhase || phases.find((phase) => phase.sessionId) || phases[0];
  const selectedStepId = selectedPhase?.id || "";
  const phaseSteps: SupervisedConversationWorkspaceStep[] = phases.map((phase) => ({ id: phase.id, label: phase.label, disabled: phase.disabled }));
  const sessionId = selectedPhase?.sessionId || "";
  const sessionQuery = useQuery<SessionDetail>({
    queryKey: queryKeys.session(sessionId || "__none__"),
    queryFn: ({ signal }) => fetchSessionDetailWindow(sessionId, { messageLimit: 80, signal }),
    structuralSharing: (previous, next) => mergeSessionDetailMessageWindow(previous as SessionDetail | undefined, next as SessionDetail),
    refetchInterval: resolvePollingInterval(pageVisible, liveRun(selectedRunKind, selectedRun) ? 2_000 : false),
    refetchIntervalInBackground: false,
    enabled: Boolean(sessionId),
    retry: false,
  });
  const sessionDetail = sessionQuery.data?.id === sessionId ? sessionQuery.data : undefined;
  const sessionError = sessionQuery.isError
    ? (sessionQuery.error instanceof Error ? sessionQuery.error.message : lang === "zh" ? "原生 Agent 会话暂时无法读取。" : "The native Agent conversation could not be loaded.")
    : "";
  const selectedGoal = selectedRunKind === "autonomous" ? text(autonomousRun?.request.goal)
    : selectedRunKind === "observation" ? text(observationRun?.goal)
      : selectedRunKind === "worktree" && worktreeRun ? runTitle(worktreeRun) : "";
  const selectedStatus = selectedRunKind === "autonomous" ? autonomousRun?.status
    : selectedRunKind === "observation" ? observationRun?.status : worktreeRun?.status;
  const durationSeconds = Number(observationDuration);
  const durationValid = Number.isInteger(durationSeconds) && durationSeconds >= 30 && durationSeconds <= 3600;
  const observationGoalValid = observationInputMode === "blank" || Boolean(observationGoal.trim());

  const evidenceTabs = useMemo(() => {
    const changes: Array<{ label: string; value: unknown }> = [];
    const verification: Array<{ label: string; value: unknown }> = [];
    const versions: Array<{ label: string; value: unknown }> = [];
    if (selectedRunKind === "autonomous" && autonomousRun) {
      (autonomousRun.candidate?.changedFiles || autonomousRun.resultReport?.changedFiles || []).forEach((file, index) => changes.push({ label: String(index + 1), value: file.path + " · " + file.changeType }));
      (autonomousRun.candidate?.verification || autonomousRun.resultReport?.verification || []).forEach((item, index) => verification.push({ label: String(index + 1), value: item }));
      const values: Array<[string, unknown]> = [
        [lang === "zh" ? "基线提交" : "Base commit", autonomousRun.candidate?.baseCommit],
        [lang === "zh" ? "候选提交" : "Candidate commit", autonomousRun.candidate?.headCommit || autonomousRun.resultReport?.candidateHead],
        [lang === "zh" ? "候选分支" : "Candidate branch", autonomousRun.candidate?.branchName],
        [lang === "zh" ? "候选工作树" : "Candidate worktree", autonomousRun.candidate?.worktreePath],
        [lang === "zh" ? "集成提交" : "Integration commit", autonomousRun.integration?.commitSha],
        [lang === "zh" ? "回滚清单" : "Rollback manifest", autonomousRun.integration?.rollbackManifestPath],
        [lang === "zh" ? "候选清理" : "Candidate cleanup", autonomousRun.cleanup?.status],
      ];
      values.forEach(([label, value]) => { if (text(value)) versions.push({ label, value }); });
    } else if (selectedRunKind === "observation" && observationRun) {
      changes.push({ label: lang === "zh" ? "边界" : "Boundary", value: lang === "zh" ? "只读观察，不修改代码" : "Read-only; no code changes" });
      if (observationRun.report) verification.push({ label: lang === "zh" ? "观察报告" : "Report", value: observationRun.report });
      if (observationRun.boundaryViolation) verification.push({ label: lang === "zh" ? "边界异常" : "Boundary issue", value: observationRun.boundaryViolation });
      const values: Array<[string, unknown]> = [
        [lang === "zh" ? "运行 ID" : "Run ID", observationRun.runId],
        [lang === "zh" ? "状态" : "Status", observationRun.status],
        [lang === "zh" ? "阶段" : "Phase", observationRun.phase],
        [lang === "zh" ? "开始时间" : "Started", observationRun.startedAt],
        [lang === "zh" ? "更新时间" : "Updated", observationRun.updatedAt],
        [lang === "zh" ? "结束时间" : "Finished", observationRun.finishedAt],
      ];
      values.forEach(([label, value]) => { if (text(value)) versions.push({ label, value }); });
    } else if (selectedRunKind === "worktree" && worktreeRun) {
      (worktreeRun.mergeAnalysis?.changedFiles || []).forEach((file, index) => changes.push({ label: String(index + 1), value: file.path + " · " + file.changeType + (file.highRisk ? (lang === "zh" ? " · 高风险" : " · high risk") : "") }));
      (worktreeRun.workflowSteps || []).forEach((step) => {
        if (Object.keys(step.metrics || {}).length) verification.push({ label: step.label || step.id, value: step.metrics });
        if (step.summary) verification.push({ label: step.label || step.id, value: step.status + " · " + step.summary });
      });
      const values: Array<[string, unknown]> = [
        [lang === "zh" ? "运行 ID" : "Run ID", worktreeRun.runId],
        [lang === "zh" ? "候选版本" : "Candidate variant", worktreeRun.mergeAnalysis?.currentCandidateVariantId],
        [lang === "zh" ? "合并状态" : "Integration status", worktreeRun.mergeAnalysis?.status],
        [lang === "zh" ? "集成提交" : "Integration commit", worktreeRun.merge?.commitSha],
        [lang === "zh" ? "回滚清单" : "Rollback manifest", worktreeRun.merge?.rollbackManifestPath],
      ];
      values.forEach(([label, value]) => { if (text(value)) versions.push({ label, value }); });
    }
    const empty = lang === "zh" ? "没有可展示的真实记录。" : "No records are available.";
    return [
      { id: "changes", label: lang === "zh" ? "改动" : "Changes", content: <EvidenceList rows={changes} empty={selectedRunKind === "observation" ? (lang === "zh" ? "只读观察不会生成代码改动。" : "Read-only observation produces no code changes.") : empty} /> },
      { id: "verification", label: lang === "zh" ? "验证" : "Verification", content: <EvidenceList rows={verification} empty={empty} /> },
      { id: "version", label: lang === "zh" ? "版本" : "Version", content: <EvidenceList rows={versions} empty={empty} /> },
    ];
  }, [selectedRunKind, autonomousRun, observationRun, worktreeRun, lang]);

  const conversation = loading && !selectedRun ? (
    <VStateSurface title={lang === "zh" ? "正在读取自进化运行" : "Loading self-evolution run"} tone="loading" fill />
  ) : loadError && !selectedRun ? (
    <VStateSurface title={lang === "zh" ? "运行信息读取失败" : "Could not load run information"} tone="error" fill actions={onRetry ? <VButton type="button" onPress={onRetry}>{lang === "zh" ? "重试" : "Retry"}</VButton> : undefined}>{loadError}</VStateSurface>
  ) : !selectedRun ? (
    <VStateSurface title={lang === "zh" ? "选择一轮自进化，或新建目标" : "Select a self-evolution run or create a goal"} tone="empty" fill>
      <p>{lang === "zh" ? "这里展示当前与最近的自进化；已结束的观察记录只在本次页面中保留。" : "Current and recent self-evolution runs appear here. Finished observations remain available only during this page visit."}</p>
      <VButton type="button" variant="primary" onPress={() => { setSetupMode("autonomous"); setSetupOpen(true); }}>{lang === "zh" ? "新建自进化目标" : "New self-evolution goal"}</VButton>
    </VStateSurface>
  ) : !sessionId ? (
    <VStateSurface title={lang === "zh" ? "此阶段没有 Agent 对话会话" : "No Agent conversation for this phase"} tone="empty" fill>
      <p>{selectedPhase?.summary || (lang === "zh" ? "该阶段没有原生会话 ID；运行状态与证据仍可在右侧查看。" : "This phase has no canonical session ID. Run state and evidence remain available in the right pane.")}</p>
    </VStateSurface>
  ) : <div className={loadError ? styles.conversationAreaWithNotice : styles.conversationArea}>
    {loadError ? <div className={styles.retryRow}><span role="alert">{loadError}</span>{onRetry ? <VButton type="button" variant="secondary" onPress={onRetry}>{lang === "zh" ? "重试读取" : "Retry"}</VButton> : null}</div> : null}
    <div className={styles.conversationBody}><ChatReadOnlySessionWorkspace
      assistant={{
        displayName: sessionDetail?.agentDisplayName || (selectedRunKind === "observation" ? (lang === "zh" ? "观察 Agent" : "Observation Agent") : (lang === "zh" ? "自进化 Agent" : "Self-evolution Agent")),
        avatarImageUrl: avatarImageUrlFrom(sessionDetail) || undefined,
        avatarFallback: avatarInitials(sessionDetail?.agentCode, sessionDetail?.agentDisplayName || (lang === "zh" ? "自进化 Agent" : "Self-evolution Agent"), lang === "zh" ? "自" : "SE"),
      }}
      defaultFileContext={sessionDetail?.defaultFileContext || ""}
      detail={sessionDetail}
      emptyLabel={lang === "zh" ? "该 Agent 会话暂时没有消息。" : "This Agent session has no messages yet."}
      errorMessage={sessionError}
      lang={lang}
      live={liveRun(selectedRunKind, selectedRun)}
      loading={sessionQuery.isLoading || (sessionQuery.isFetching && !sessionDetail)}
      loadingLabel={lang === "zh" ? "正在读取原生 Agent 会话…" : "Loading canonical Agent conversation…"}
      sessionId={sessionId}
      taskSummary={selectedGoal}
      user={{ displayName: lang === "zh" ? "操作者" : "You" }}
    />
    {sessionError ? <div className={styles.retryRow}><span role="alert">{sessionError}</span><VButton type="button" variant="secondary" onPress={() => void sessionQuery.refetch()}>{lang === "zh" ? "重试读取" : "Retry"}</VButton></div> : null}</div>
  </div>;
  const visibleConversation = selectedRun && loadError && !sessionId
    ? <div className={styles.conversationWithNotice}><div className={styles.retryRow} role="alert"><span>{loadError}</span>{onRetry ? <VButton type="button" variant="secondary" onPress={onRetry}>{lang === "zh" ? "重试读取" : "Retry"}</VButton> : null}</div>{conversation}</div>
    : conversation;

  const setup = (
    <div className={styles.setupPane}>
      <div className={styles.setupIntro}>
        <div><p className={styles.eyebrow}>{lang === "zh" ? "自进化" : "Self-evolution"}</p><h2 className={styles.setupHeading}>{lang === "zh" ? "发起一轮新运行" : "Start a new run"}</h2><p className={styles.subtleText}>{lang === "zh" ? "自主闭环最多迭代 1 轮，候选仍需人工审查；只读观察不修改代码。" : "Autonomous loops currently support one iteration and require human review; observation runs are read-only."}</p></div>
        <div className={styles.modePicker} role="tablist" aria-label={lang === "zh" ? "运行方式" : "Run type"}>
          <VButton type="button" variant={setupMode === "autonomous" ? "primary" : "secondary"} aria-pressed={setupMode === "autonomous"} onPress={() => setSetupMode("autonomous")}>{lang === "zh" ? "自主进化" : "Autonomous"}</VButton>
          <VButton type="button" variant={setupMode === "observation" ? "primary" : "secondary"} aria-pressed={setupMode === "observation"} onPress={() => setSetupMode("observation")}>{lang === "zh" ? "只读观察" : "Observation"}</VButton>
        </div>
      </div>
      {setupMode === "autonomous" ? <div className={styles.formStack}>
        <label className={styles.formField}><span>{lang === "zh" ? "进化目标" : "Evolution goal"}</span><VNativeTextarea rows={5} value={goalInput} onChange={(event) => onGoalInputChange(event.target.value)} placeholder={lang === "zh" ? "描述希望 Agent 调查并改进的具体问题" : "Describe the specific problem for the Agent to investigate and improve"} /></label>
        <div className={styles.budgetRow}><span>{lang === "zh" ? "迭代预算" : "Iteration budget"}</span><strong>1 {lang === "zh" ? "轮" : "iteration"}</strong><span>{lang === "zh" ? "当前服务端仅接受 1 轮" : "The service currently accepts one iteration"}</span></div>
        {startWorktreeError ? <p className={styles.errorText} role="alert">{startWorktreeError}</p> : null}
        <VButton type="button" variant="primary" isDisabled={startPending || runLocked || !goalInput.trim()} onPress={() => setConfirmation({ kind: "start-autonomous" })}>{startPending ? (lang === "zh" ? "正在启动…" : "Starting…") : (lang === "zh" ? "审查并启动" : "Review and start")}</VButton>
      </div> : <div className={styles.formStack}>
        <div className={styles.modePicker} role="group" aria-label={lang === "zh" ? "观察输入方式" : "Observation input mode"}>
          <VButton type="button" variant={observationInputMode === "prompt" ? "primary" : "secondary"} aria-pressed={observationInputMode === "prompt"} onPress={() => setObservationInputMode("prompt")}>{lang === "zh" ? "提示词观察" : "Prompted"}</VButton>
          <VButton type="button" variant={observationInputMode === "blank" ? "primary" : "secondary"} aria-pressed={observationInputMode === "blank"} onPress={() => setObservationInputMode("blank")}>{lang === "zh" ? "空白观察" : "Blank input"}</VButton>
        </div>
        <label className={styles.formField}><span>{lang === "zh" ? "观察目标" : "Observation prompt"}</span><VNativeTextarea rows={5} value={observationInputMode === "blank" ? "" : observationGoal} disabled={observationInputMode === "blank"} onChange={(event) => setObservationGoal(event.target.value)} placeholder={observationInputMode === "blank" ? (lang === "zh" ? "空白模式不会注入观察提示词" : "Blank mode sends no prompt to the observer") : (lang === "zh" ? "说明观察范围与希望得到的信息" : "Describe the scope and information to observe")} /></label>
        <label className={styles.formField}><span>{lang === "zh" ? "观察时长（秒）" : "Observation duration (seconds)"}</span><VNativeInput type="number" min={30} max={3600} step={30} value={observationDuration} onChange={(event) => setObservationDuration(event.target.value)} /></label>
        {!durationValid ? <p className={styles.errorText} role="alert">{lang === "zh" ? "观察时长须为 30 到 3600 秒的整数。" : "Duration must be a whole number from 30 to 3600 seconds."}</p> : null}
        {observationStartError ? <p className={styles.errorText} role="alert">{observationStartError}</p> : null}
        <p className={styles.subtleText}>{lang === "zh" ? "观察只读取上下文，不创建候选改动。" : "Observation reads context and creates no candidate changes."}</p>
        <VButton type="button" variant="primary" isDisabled={observationStartPending || runLocked || !observationGoalValid || !durationValid} onPress={() => setConfirmation({ kind: "start-observation" })}>{observationStartPending ? (lang === "zh" ? "正在启动…" : "Starting…") : (lang === "zh" ? "审查并启动观察" : "Review and start observation")}</VButton>
      </div>}
      {runLocked ? <p className={styles.subtleText}>{lang === "zh" ? "已有自进化运行占用运行锁。" : "An existing self-evolution run holds the run lock."}</p> : overview?.readiness?.nextAction ? <p className={styles.subtleText}>{overview.readiness.nextAction}</p> : null}
    </div>
  );

  const autonomousActions = (() => {
    if (selectedRunKind !== "autonomous" || !autonomousRun?.runId) return null;
    if (autonomousRun.status === "failed" && autonomousRun.phase === "integration_failed") return <VButton type="button" variant="primary" icon={<GitCommitHorizontal size={15} />} isDisabled={autonomousActionPending} onPress={() => setConfirmation({ kind: "autonomous-action", runId: autonomousRun.runId, action: "approve" })}>{lang === "zh" ? "重试 Git 集成" : "Retry Git integration"}</VButton>;
    if (autonomousRun.phase === "cleanup_failed") return <VButton type="button" variant="secondary" icon={<RotateCcw size={15} />} isDisabled={autonomousActionPending} onPress={() => setConfirmation({ kind: "autonomous-action", runId: autonomousRun.runId, action: "retry_cleanup" })}>{lang === "zh" ? "重试候选清理" : "Retry candidate cleanup"}</VButton>;
    if (autonomousRun.status === "awaiting_user_approval") return <>
      <VButton type="button" variant="primary" icon={<Check size={15} />} isDisabled={autonomousActionPending} onPress={() => setConfirmation({ kind: "autonomous-action", runId: autonomousRun.runId, action: "approve" })}>{lang === "zh" ? "批准并集成" : "Approve and integrate"}</VButton>
      <VButton type="button" variant="danger" icon={<X size={15} />} isDisabled={autonomousActionPending} onPress={() => setConfirmation({ kind: "autonomous-action", runId: autonomousRun.runId, action: "reject" })}>{lang === "zh" ? "拒绝候选" : "Reject candidate"}</VButton>
    </>;
    return null;
  })();
  const observationAction = selectedRunKind === "observation" && observationRun?.runId && ["queued", "running"].includes(text(observationRun.status).toLowerCase())
    ? <VButton type="button" variant="danger" icon={<Square size={14} />} isDisabled={observationActionPending || !observationRun.actionStates?.terminate?.enabled} title={observationRun.actionStates?.terminate?.reason} onPress={() => setConfirmation({ kind: "terminate-observation", runId: observationRun.runId })}>{lang === "zh" ? "终止观察" : "Stop observation"}</VButton>
    : null;
  const worktreeActions = selectedRunKind === "worktree" && worktreeRun ? <>
    {actionEnabled(worktreeRun, "terminate") ? <VButton type="button" variant="danger" icon={<Square size={14} />} isDisabled={worktreeActionPending} onPress={() => setConfirmation({ kind: "worktree-action", runId: worktreeRun.runId, action: "terminate" })}>{lang === "zh" ? "终止运行" : "Stop run"}</VButton> : null}
    {actionEnabled(worktreeRun, "approveReview") ? <VButton type="button" variant="secondary" isDisabled={worktreeActionPending || worktreeRunLocked} onPress={() => setConfirmation({ kind: "worktree-action", runId: worktreeRun.runId, action: "approve_review" })}>{lang === "zh" ? "通过审查" : "Approve review"}</VButton> : null}
    {actionEnabled(worktreeRun, "merge") ? <VButton type="button" variant="primary" icon={<GitCommitHorizontal size={15} />} isDisabled={worktreeActionPending || worktreeRunLocked} onPress={() => setConfirmation({ kind: "worktree-action", runId: worktreeRun.runId, action: "merge" })}>{lang === "zh" ? "集成候选" : "Integrate candidate"}</VButton> : null}
    {actionEnabled(worktreeRun, "discard") ? <VButton type="button" variant="danger" isDisabled={worktreeActionPending || worktreeRunLocked} onPress={() => setConfirmation({ kind: "worktree-action", runId: worktreeRun.runId, action: "discard" })}>{lang === "zh" ? "丢弃候选" : "Discard candidate"}</VButton> : null}
  </> : null;
  const actionErrors = [autonomousActionError, observationActionError, worktreeActionError, startWorktreeError, observationStartError, guardNotice].map(text).filter(Boolean).join("\n");
  const footer = selectedRun ? <div className={styles.footerContent}>
    <div className={styles.footerStatus}><VStatusChip tone={selectedStatus === "completed" || selectedStatus === "done" ? "success" : selectedStatus === "failed" ? "danger" : selectedStatus === "awaiting_user_approval" ? "warning" : "neutral"}>{statusLabel(selectedStatus, lang)}</VStatusChip>{selectedGoal ? <span className={styles.footerGoal} title={selectedGoal}>{selectedGoal}</span> : null}</div>
    <div className={styles.footerActions}>{autonomousActions}{observationAction}{worktreeActions}</div>
    {actionFeedback ? <p className={styles.feedbackText} role="status">{actionFeedback}</p> : null}
    {actionErrors ? <p className={styles.errorText} role="alert">{actionErrors}</p> : null}
  </div> : null;

  const runSummary = selectedRun ? <div className={styles.sourceSummary}>
    <span>{selectedRunKind === "autonomous" ? (lang === "zh" ? "自主闭环" : "Autonomous loop") : selectedRunKind === "observation" ? (lang === "zh" ? "只读观察" : "Read-only observation") : (lang === "zh" ? "隔离工作树" : "Isolated worktree")}</span>
    <strong>{selectedGoal || selectedRun.runId}</strong><span>{lang === "zh" ? "状态" : "Status"} · {statusLabel(selectedStatus, lang)}</span>
  </div> : null;
  const evidenceSourceGoal = selectedGoal || (lang === "zh" ? "等待选择自进化运行" : "Select a self-evolution run");
  const title = selectedRunKind === "autonomous" ? autonomousRun?.request.goal || (lang === "zh" ? "自进化自动闭环" : "Autonomous self-evolution")
    : selectedRunKind === "observation" ? observationRun?.goal || (lang === "zh" ? "只读观察" : "Read-only observation")
      : selectedRunKind === "worktree" && worktreeRun ? runTitle(worktreeRun) : (lang === "zh" ? "自进化工作台" : "Self-evolution workspace");

  const confirmationTitle = !confirmation ? "" : confirmation.kind === "start-autonomous" ? (lang === "zh" ? "启动自进化闭环？" : "Start the autonomous loop?")
    : confirmation.kind === "start-observation" ? (lang === "zh" ? "启动只读观察？" : "Start read-only observation?")
      : confirmation.kind === "terminate-observation" ? (lang === "zh" ? "终止只读观察？" : "Stop read-only observation?")
        : confirmation.kind === "worktree-action" ? (lang === "zh" ? "确认运行操作？" : "Confirm run action?")
          : confirmation.action === "approve" ? autonomousRun?.phase === "integration_failed" ? (lang === "zh" ? "重试 Git 集成？" : "Retry Git integration?") : (lang === "zh" ? "批准候选并集成？" : "Approve and integrate candidate?")
            : confirmation.action === "reject" ? (lang === "zh" ? "拒绝候选？" : "Reject candidate?") : (lang === "zh" ? "重试候选清理？" : "Retry candidate cleanup?");
  const confirmationBody = !confirmation ? "" : confirmation.kind === "start-autonomous" ? goalInput.trim()
    : confirmation.kind === "start-observation" ? observationInputMode === "blank" ? (lang === "zh" ? "空白输入，不注入观察提示词。" : "Blank input; no observation prompt will be injected.") : observationGoal.trim()
      : confirmation.kind === "terminate-observation" ? (lang === "zh" ? "本轮观察会收到终止请求。" : "A termination request will be sent for this observation run.")
        : confirmation.kind === "worktree-action" ? confirmation.action === "discard" ? (lang === "zh" ? "丢弃当前候选环境。" : "Discard the current candidate environment.") : confirmation.action === "merge" ? (lang === "zh" ? "按现有审查状态请求集成。" : "Request integration under the current review state.") : confirmation.action === "terminate" ? (lang === "zh" ? "终止当前隔离运行。" : "Terminate the isolated run.") : (lang === "zh" ? "提交该运行的审查决定。" : "Submit the review decision.")
          : confirmation.action === "approve" ? autonomousRun?.phase === "integration_failed" ? (lang === "zh" ? "后端将使用当前候选再次尝试 Git 集成。" : "The backend will retry integration with the existing candidate.") : (lang === "zh" ? "批准后后端会创建 Git 提交并清理候选环境。" : "Approval lets the backend create a commit and clean up the candidate worktree.")
            : confirmation.action === "reject" ? (lang === "zh" ? "拒绝只记录决定，不会把候选合入主分支。" : "Rejection records the decision and does not integrate the candidate.") : (lang === "zh" ? "后端将重试清理候选工作树和本地分支。" : "The backend will retry candidate worktree and branch cleanup.");

  const confirmationIsCurrent = (() => {
    if (!confirmation) return false;
    if (confirmation.kind === "start-autonomous") return setupOpen && !startPending && !runLocked && Boolean(goalInput.trim());
    if (confirmation.kind === "start-observation") return setupOpen && !observationStartPending && !runLocked && observationGoalValid && durationValid;
    if (confirmation.kind === "autonomous-action") {
      return selectedRunKind === "autonomous" && canConfirmAutonomousAction({
        action: confirmation.action,
        requestedRunId: confirmation.runId,
        selectedRun: autonomousRun,
        pending: autonomousActionPending,
      });
    }
    if (confirmation.kind === "terminate-observation") return selectedRunKind === "observation" && observationRun?.runId === confirmation.runId && !observationActionPending && ["queued", "running"].includes(text(observationRun.status).toLowerCase()) && Boolean(observationRun.actionStates?.terminate?.enabled);
    if (selectedRunKind !== "worktree" || worktreeRun?.runId !== confirmation.runId || worktreeActionPending) return false;
    if (confirmation.action !== "terminate" && worktreeRunLocked) return false;
    const actionKey = confirmation.action === "approve_review" ? "approveReview" : confirmation.action;
    return actionEnabled(worktreeRun, actionKey);
  })();

  const submitConfirmation = () => {
    if (!confirmation) return;
    if (!confirmationIsCurrent) {
      setGuardNotice(lang === "zh" ? "运行状态已变化，此操作未提交。请按当前状态重新选择。" : "Run state changed. The action was not submitted; review the current state and try again.");
      setConfirmation(null);
      return;
    }
    setGuardNotice("");
    const intent = confirmation;
    setConfirmation(null);
    if (intent.kind === "start-autonomous") onStartRun();
    else if (intent.kind === "start-observation") onStartObservation({ goal: observationInputMode === "blank" ? "" : observationGoal.trim(), durationSeconds, inputMode: observationInputMode });
    else if (intent.kind === "autonomous-action") {
      const comment = intent.action === "approve"
        ? autonomousRun?.phase === "integration_failed"
          ? (lang === "zh" ? "用户确认重试 Git 集成" : "User confirmed Git integration retry")
          : (lang === "zh" ? "用户批准候选" : "User approved candidate")
        : intent.action === "reject" ? (lang === "zh" ? "用户拒绝候选" : "User rejected candidate") : undefined;
      onAutonomousAction(intent.runId, intent.action, comment);
    } else if (intent.kind === "terminate-observation") onTerminateObservation(intent.runId);
    else onWorktreeAction(intent.runId, intent.action);
  };

  return <>
    <SupervisedConversationWorkspace
      {...workspaceNavigation}
      lang={lang}
      title={title}
      sourceLabel={selectedGoal || (lang === "zh" ? "新建目标" : "New goal")}
      sourceTitle={lang === "zh" ? "进化目标" : "Evolution goal"}
      sourceIcon={<Target size={15} />}
      sourceSummary={runSummary}
      trackContext={selectedRunKind === "autonomous" ? (lang === "zh" ? "迭代预算 · 1 轮" : "Iteration budget · 1") : selectedRunKind === "observation" ? (lang === "zh" ? "只读观察 · 无代码改动" : "Read-only observation · no code changes") : selectedRunKind === "worktree" ? (lang === "zh" ? "隔离工作树 · 旧版自进化" : "Isolated worktree · legacy self-evolution") : undefined}
      setupTitle={setupMode === "autonomous" ? (lang === "zh" ? "新建自进化目标" : "New self-evolution goal") : (lang === "zh" ? "配置只读观察" : "Configure read-only observation")}
      phases={phases.map(({ id, label, statusLabel, current, disabled }) => ({ id, label, statusLabel, current, disabled }))}
      selectedStepId={selectedStepId}
      steps={phaseSteps}
      onSelectStep={(id) => onPhaseSelect(runKey, id)}
      showFollowLive={Boolean(followPhase && selectedStepId !== followPhase.id)}
      onFollowLive={() => { if (followPhase) onPhaseSelect(runKey, followPhase.id); }}
      onNew={() => { setSetupMode("autonomous"); setSetupOpen(true); }}
      onSource={() => setSourceOpen(true)}
      onHistory={onHistory}
      onLibrary={onLibrary}
      onSettings={onSettings}
      setupOpen={setupOpen}
      setup={setup}
      conversation={visibleConversation}
      footer={footer}
      evidenceTabs={evidenceTabs}
      hasRun={Boolean(selectedRun)}
    />
    <VDialog open={Boolean(confirmation)} onOpenChange={(open) => { if (!open) setConfirmation(null); }} size="sm" title={confirmationTitle}>
      <div className={styles.dialogBody}><p>{confirmationBody}</p>
        {confirmation?.kind === "start-autonomous" ? <p className={styles.dialogFact}>{lang === "zh" ? "迭代预算：1 轮；候选完成后需人工审查。" : "Iteration budget: one; the candidate requires human review."}</p> : null}
        {!confirmationIsCurrent ? <p className={styles.errorText} role="alert">{lang === "zh" ? "运行状态或操作权限已变化，请返回并检查最新信息。" : "Run state or action permission changed. Go back and review the latest information."}</p> : null}
        <div className={styles.dialogActions}><VButton type="button" variant="secondary" onPress={() => setConfirmation(null)}>{lang === "zh" ? "返回" : "Back"}</VButton><VButton type="button" isDisabled={!confirmationIsCurrent} variant={confirmation?.kind === "autonomous-action" && confirmation.action === "reject" || confirmation?.kind === "terminate-observation" || confirmation?.kind === "worktree-action" && ["terminate", "discard"].includes(confirmation.action) ? "danger" : "primary"} onPress={submitConfirmation}>{lang === "zh" ? "确认" : "Confirm"}</VButton></div>
      </div>
    </VDialog>
    <VDialog open={sourceOpen} onOpenChange={setSourceOpen} size="md" title={lang === "zh" ? "运行上下文" : "Run context"}>
      <div className={styles.dialogBody}><p className={styles.dialogFact}>{evidenceSourceGoal}</p>
        {selectedRun ? <dl className={styles.contextFacts}>
          <div><dt>{lang === "zh" ? "运行类型" : "Run type"}</dt><dd>{selectedRunKind === "autonomous" ? (lang === "zh" ? "自主闭环" : "Autonomous loop") : selectedRunKind === "observation" ? (lang === "zh" ? "只读观察" : "Read-only observation") : (lang === "zh" ? "隔离工作树" : "Isolated worktree")}</dd></div>
          <div><dt>{lang === "zh" ? "运行 ID" : "Run ID"}</dt><dd>{selectedRun.runId}</dd></div>
          <div><dt>{lang === "zh" ? "状态" : "Status"}</dt><dd>{statusLabel(selectedStatus, lang)}</dd></div>
          {selectedRunKind === "autonomous" ? <div><dt>{lang === "zh" ? "迭代预算" : "Iteration budget"}</dt><dd>1</dd></div> : null}
          {selectedRunKind === "observation" ? <div><dt>{lang === "zh" ? "观察边界" : "Observation boundary"}</dt><dd>{lang === "zh" ? "只读，不创建工作树" : "Read-only; no worktree"}</dd></div> : null}
        </dl> : <p>{lang === "zh" ? "新建运行后，这里会显示目标与实际返回的上下文。" : "The goal and returned context will appear here after a run is created."}</p>}
      </div>
    </VDialog>
  </>;
}

function liveRun(kind: SelfEvolutionRunKind | null, run: SelfEvolutionAutonomousLoopRun | SelfObservationRun | SupervisedWorktreeRun | null) {
  if (!kind || !run) return false;
  const statuses = kind === "worktree" ? ["queued", "running", "stopping"] : ["queued", "running"];
  return statuses.includes(text(run.status).toLowerCase());
}
