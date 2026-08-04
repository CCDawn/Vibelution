import {
  ArrowUpRight,
  CheckCircle2,
  GitCommitHorizontal,
  RotateCcw,
  ShieldCheck,
  X,
} from "lucide-react";

import type { SelfEvolutionAutonomousLoopRun } from "../api/types";
import {
  VButton,
  VMetricStrip,
  VRouteLinkButton,
  VStateSurface,
  VSurface,
} from "../components/vui";
import { selfEvolutionAutonomousLoopPanelStyles as styles } from "./SelfEvolutionAutonomousLoopPanel.styles";

type SelfEvolutionAutonomousLoopPanelProps = {
  lang: "zh" | "en";
  run?: SelfEvolutionAutonomousLoopRun | null;
  pending: boolean;
  error: string;
  onAction: (
    action: "approve" | "reject" | "retry_cleanup",
    comment?: string,
  ) => void;
};

const PHASES = [
  { id: "observing", zh: "观察现状", en: "Observe" },
  { id: "planning", zh: "制定计划", en: "Plan" },
  { id: "evolving", zh: "隔离进化", en: "Evolve" },
  { id: "reporting", zh: "等待用户审查", en: "User review" },
  { id: "integrating", zh: "Git 集成", en: "Git integration" },
  { id: "completed", zh: "闭环完成", en: "Complete" },
] as const;

function phaseIndex(phase: string): number {
  const normalized = String(phase || "").trim().toLowerCase();
  if (normalized === "queued") {
    return -1;
  }
  if (normalized.endsWith("_interrupted")) {
    const base = normalized.replace(/_interrupted$/, "");
    const baseIndex = PHASES.findIndex((item) => item.id === base || item.id.startsWith(base));
    if (baseIndex >= 0) {
      return baseIndex;
    }
    if (base === "observing" || base.startsWith("observ")) {
      return 0;
    }
    if (base === "planning" || base.startsWith("plan")) {
      return 1;
    }
    if (base === "evolving" || base.startsWith("evolv")) {
      return 2;
    }
  }
  if (normalized === "observing_failed") {
    return 0;
  }
  if (normalized === "planning_failed") {
    return 1;
  }
  if (normalized === "evolving_failed") {
    return 2;
  }
  if (normalized === "integration_failed") {
    return 4;
  }
  if (normalized === "cleanup_pending" || normalized === "cleanup_failed") {
    return 4;
  }
  return PHASES.findIndex((item) => item.id === normalized);
}

function compactRevision(value: string | null | undefined): string {
  const text = String(value || "").trim();
  return text ? text.slice(0, 12) : "--";
}

function evidenceText(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value ?? "");
  }
}

function chatRoute(sessionId: string | null | undefined): string {
  const normalized = String(sessionId || "").trim();
  return normalized ? `/chat?session=${encodeURIComponent(normalized)}` : "";
}

function ConversationLink({
  lang,
  sessionId,
}: {
  lang: "zh" | "en";
  sessionId?: string;
}) {
  const route = chatRoute(sessionId);
  if (!route) {
    return null;
  }
  return (
    <VRouteLinkButton to={route} variant="ghost" density="compact">
      {lang === "zh" ? "查看 Agent 会话" : "Open Agent conversation"}
    </VRouteLinkButton>
  );
}

function phaseStatusLabel(
  index: number,
  currentIndex: number,
  completed: boolean,
  failed: boolean,
  lang: "zh" | "en",
): string {
  if (completed || index < currentIndex) {
    return lang === "zh" ? "已完成" : "Done";
  }
  if (index === currentIndex) {
    if (failed) {
      return lang === "zh" ? "中断" : "Interrupted";
    }
    return lang === "zh" ? "当前" : "Current";
  }
  return lang === "zh" ? "未开始" : "Not started";
}

export function SelfEvolutionAutonomousLoopPanel({
  lang,
  run,
  pending,
  error,
  onAction,
}: SelfEvolutionAutonomousLoopPanelProps) {
  const currentIndex = phaseIndex(run?.phase ?? "");
  const changedFiles = run?.candidate?.changedFiles ?? [];
  const verification = run?.candidate?.verification ?? [];
  const awaitingReview = run?.status === "awaiting_user_approval";
  const failed = run?.status === "failed";
  const integrationFailed = failed && run?.phase === "integration_failed";
  const cleanupFailed = run?.phase === "cleanup_failed";
  const completed = run?.status === "completed" && run?.phase === "completed";
  const statusLabel = completed
    ? lang === "zh" ? "闭环完成" : "Complete"
    : awaitingReview
      ? lang === "zh" ? "等待用户审查" : "Waiting for user review"
      : failed
        ? lang === "zh" ? "闭环中断" : "Loop interrupted"
        : run?.status || (lang === "zh" ? "尚未启动" : "Not started");
  const statusTone = completed
    ? "success"
    : awaitingReview
      ? "warning"
      : failed
        ? "error"
        : "info";
  const metricTone = completed
    ? "success"
    : failed
      ? "danger"
      : awaitingReview
        ? "warning"
        : "info";

  const observationSummary = String(run?.observation?.summary || "").trim();
  const planSummary = String(run?.plan?.summary || "").trim();
  const candidateSummary = String(run?.candidate?.summary || "").trim();
  const hasStageContent = Boolean(observationSummary || planSummary || candidateSummary);
  const showStageCards = hasStageContent || !failed;

  if (!run) {
    return (
      <VStateSurface
        title={lang === "zh" ? "自进化自动闭环" : "Autonomous self-evolution loop"}
        tone="empty"
        icon={<ArrowUpRight size={15} />}
      >
        <p>
          {lang === "zh"
            ? "Agent 将观察现状、制定计划并在隔离工作树中进化；结果报告后必须由用户审查，批准后才会创建 Git 提交并删除本地候选分支。"
            : "Agents observe, plan, and evolve in an isolated worktree. A user must review the report before Git integration and local candidate cleanup."}
        </p>
        {error ? <p className={styles.error}>{error}</p> : null}
      </VStateSurface>
    );
  }

  const headerSummary = run.resultReport?.summary
    || candidateSummary
    || planSummary
    || observationSummary
    || (failed
      ? (lang === "zh"
        ? "闭环在完成前中断；下方标明中断阶段与候选环境状态。"
        : "The loop stopped before completion; interruption phase and candidate state are below.")
      : statusLabel);

  return (
    <VSurface
      className={styles.surface}
      elevation="flat"
      padding="none"
      tone="panel"
      ariaLabel={lang === "zh" ? "自进化自动闭环" : "Autonomous self-evolution loop"}
    >
      <header className={styles.header}>
        <div className={styles.heading}>
          <span className={styles.eyebrow}>
            {lang === "zh" ? "自进化自动闭环" : "Autonomous self-evolution"}
          </span>
          <strong className={styles.title}>{run.request.goal}</strong>
          <span className={styles.summary}>{headerSummary}</span>
        </div>
        <span className={styles.statusPill} data-tone={statusTone}>
          {statusLabel}
        </span>
      </header>

      {failed ? (
        <VStateSurface
          title={lang === "zh" ? "自动闭环未完成" : "Autonomous loop did not complete"}
          tone="error"
          icon={<X size={15} />}
          actions={integrationFailed ? (
            <VButton
              type="button"
              variant="primary"
              icon={<GitCommitHorizontal size={14} />}
              isDisabled={pending}
              onPress={() => onAction(
                "approve",
                lang === "zh"
                  ? "用户修复集成环境后重试 Git 集成"
                  : "User retried Git integration after repairing the environment",
              )}
            >
              {lang === "zh" ? "重试 Git 集成" : "Retry Git integration"}
            </VButton>
          ) : undefined}
          facts={[
            {
              key: "phase",
              label: lang === "zh" ? "中断阶段" : "Interrupted phase",
              value: run.phase,
            },
            {
              key: "candidate",
              label: lang === "zh" ? "候选环境" : "Candidate environment",
              value: run.candidate?.worktreePath
                ? lang === "zh" ? "已保留" : "Preserved"
                : lang === "zh" ? "尚未生成" : "Not created",
            },
          ]}
        >
          {run.error?.message || (lang === "zh" ? "请检查失败原因后重新启动一轮。" : "Inspect the failure and start a new loop.")}
        </VStateSurface>
      ) : null}

      <div className={styles.phaseGrid} aria-label={lang === "zh" ? "闭环阶段" : "Loop phases"} data-testid="self-loop-phase-stepper">
        {PHASES.map((item, index) => {
          const done = completed || index < currentIndex;
          const current = index === currentIndex;
          const interrupted = failed && current;
          const pendingPhase = !done && !current;
          return (
            <div
              key={item.id}
              className={[
                styles.phase,
                current && !failed ? styles.phaseCurrent : "",
                done ? styles.phaseDone : "",
                interrupted ? styles.phaseInterrupted : "",
                pendingPhase ? styles.phasePending : "",
              ].filter(Boolean).join(" ")}
              data-phase={item.id}
              data-state={interrupted ? "interrupted" : done ? "done" : current ? "current" : "pending"}
            >
              <span className={styles.phaseLabel}>{lang === "zh" ? item.zh : item.en}</span>
              <span className={styles.phaseStatus}>
                {phaseStatusLabel(index, currentIndex, completed, failed, lang)}
              </span>
            </div>
          );
        })}
      </div>

      <VMetricStrip
        ariaLabel={lang === "zh" ? "自动闭环摘要" : "Autonomous loop summary"}
        status={{ label: statusLabel, tone: metricTone }}
        metrics={[
          {
            id: "iterations",
            label: lang === "zh" ? "迭代上限" : "Iteration limit",
            value: run.request.maxIterations,
          },
          {
            id: "files",
            label: lang === "zh" ? "候选文件" : "Candidate files",
            value: changedFiles.length,
          },
          {
            id: "verification",
            label: lang === "zh" ? "验证证据" : "Verification",
            value: verification.length,
          },
        ]}
      />

      {showStageCards ? (
        <div className={styles.cards}>
          <section className={[styles.card, !observationSummary && failed ? styles.cardMuted : ""].filter(Boolean).join(" ")}>
            <div className={styles.cardHeader}>
              <strong className={styles.cardTitle}>{lang === "zh" ? "观察现状" : "Observation"}</strong>
              <ConversationLink lang={lang} sessionId={run.observation?.conversationSessionId} />
            </div>
            <p className={[styles.cardBody, !observationSummary ? styles.cardEmpty : ""].filter(Boolean).join(" ")}>
              {observationSummary || (lang === "zh" ? "尚未产生观察摘要" : "No observation summary yet")}
            </p>
          </section>
          <section className={[styles.card, !planSummary && failed ? styles.cardMuted : ""].filter(Boolean).join(" ")}>
            <div className={styles.cardHeader}>
              <strong className={styles.cardTitle}>{lang === "zh" ? "制定计划" : "Plan"}</strong>
              <ConversationLink lang={lang} sessionId={run.plan?.conversationSessionId} />
            </div>
            <p className={[styles.cardBody, !planSummary ? styles.cardEmpty : ""].filter(Boolean).join(" ")}>
              {planSummary || (lang === "zh" ? "尚未产生计划摘要" : "No plan summary yet")}
            </p>
          </section>
          <section className={[styles.card, !candidateSummary && failed ? styles.cardMuted : ""].filter(Boolean).join(" ")}>
            <div className={styles.cardHeader}>
              <strong className={styles.cardTitle}>{lang === "zh" ? "隔离进化" : "Isolated evolution"}</strong>
              <ConversationLink lang={lang} sessionId={run.candidate?.conversationSessionId} />
            </div>
            <p className={[styles.cardBody, !candidateSummary ? styles.cardEmpty : ""].filter(Boolean).join(" ")}>
              {candidateSummary || (lang === "zh" ? "尚未产生候选摘要" : "No candidate summary yet")}
            </p>
          </section>
        </div>
      ) : null}

      {changedFiles.length ? (
        <div className={styles.list} aria-label={lang === "zh" ? "候选变更" : "Candidate changes"}>
          {changedFiles.map((file) => (
            <div key={`${file.changeType}:${file.path}`} className={styles.row}>
              <span className={styles.rowMain}>{file.path}</span>
              <span className={styles.rowMeta}>{file.changeType}</span>
            </div>
          ))}
        </div>
      ) : null}

      {verification.length ? (
        <div className={styles.list} aria-label={lang === "zh" ? "验证结果" : "Verification results"}>
          {verification.map((item, index) => (
            <div key={`${index}:${evidenceText(item)}`} className={styles.row}>
              <span className={styles.rowMain}>{evidenceText(item)}</span>
              <span className={styles.rowMeta}>{lang === "zh" ? "验证" : "Verified"}</span>
            </div>
          ))}
        </div>
      ) : null}

      {awaitingReview ? (
        <VStateSurface
          title={lang === "zh" ? "等待用户审查" : "Waiting for user review"}
          tone="unavailable"
          icon={<ShieldCheck size={15} />}
          facts={[
            {
              key: "candidate",
              label: lang === "zh" ? "候选版本" : "Candidate",
              value: compactRevision(run.candidate?.headCommit),
            },
            {
              key: "branch",
              label: lang === "zh" ? "本地分支" : "Local branch",
              value: run.candidate?.branchName || "--",
            },
          ]}
          actions={(
            <>
              <VButton
                type="button"
                variant="primary"
                icon={<GitCommitHorizontal size={14} />}
                isDisabled={pending}
                onPress={() => onAction("approve", lang === "zh" ? "用户批准自动合入" : "User approved automatic integration")}
              >
                {lang === "zh" ? "批准并自动合入" : "Approve and integrate"}
              </VButton>
              <VButton
                type="button"
                variant="secondary"
                icon={<X size={14} />}
                isDisabled={pending}
                onPress={() => onAction("reject", lang === "zh" ? "用户退回候选" : "User rejected candidate")}
              >
                {lang === "zh" ? "拒绝并保留候选" : "Reject and preserve candidate"}
              </VButton>
            </>
          )}
        >
          {lang === "zh"
            ? "批准后由确定性后端创建 Git 提交并清理候选环境；拒绝只记录决定并保留候选工作树，便于人工检查。"
            : "Approval creates the Git commit and cleans the candidate environment. Rejection records the decision and preserves the candidate worktree for inspection."}
        </VStateSurface>
      ) : null}

      {cleanupFailed ? (
        <VStateSurface
          title={lang === "zh" ? "Git 已提交，候选清理未完成" : "Git committed; candidate cleanup incomplete"}
          tone="error"
          icon={<RotateCcw size={15} />}
          actions={(
            <VButton
              type="button"
              variant="danger"
              isDisabled={pending}
              onPress={() => onAction("retry_cleanup")}
            >
              {lang === "zh" ? "重试清理" : "Retry cleanup"}
            </VButton>
          )}
        >
          {run.error?.message || "--"}
        </VStateSurface>
      ) : null}

      {completed ? (
        <VStateSurface
          title={lang === "zh" ? "闭环完成" : "Loop complete"}
          tone="info"
          icon={<CheckCircle2 size={15} />}
          facts={[
            {
              key: "commit",
              label: "Git commit",
              value: compactRevision(run.integration?.commitSha),
            },
            {
              key: "worktree",
              label: lang === "zh" ? "候选工作树" : "Candidate worktree",
              value: run.cleanup?.worktreeRemoved
                ? lang === "zh" ? "工作树已删除" : "Worktree removed"
                : "--",
            },
            {
              key: "branch",
              label: lang === "zh" ? "候选分支" : "Candidate branch",
              value: run.cleanup?.localBranchDeleted
                ? lang === "zh" ? "本地分支已删除" : "Local branch removed"
                : "--",
            },
          ]}
        >
          {lang === "zh"
            ? `Agent 已完成本地 Git 集成并清理候选环境。完整提交：${run.integration?.commitSha || "--"}`
            : `The Agent completed local Git integration and cleaned the candidate environment. Commit: ${run.integration?.commitSha || "--"}`}
        </VStateSurface>
      ) : null}

      {error ? <p className={styles.error}>{error}</p> : null}
    </VSurface>
  );
}
