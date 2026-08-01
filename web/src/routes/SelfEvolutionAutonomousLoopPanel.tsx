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
  const cleanupFailed = run?.phase === "cleanup_failed";
  const completed = run?.status === "completed" && run?.phase === "completed";
  const statusLabel = completed
    ? lang === "zh" ? "闭环完成" : "Complete"
    : awaitingReview
      ? lang === "zh" ? "等待用户审查" : "Waiting for user review"
      : failed
        ? lang === "zh" ? "闭环中断" : "Loop interrupted"
      : run?.status || (lang === "zh" ? "尚未启动" : "Not started");

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
          <span className={styles.summary}>
            {run.resultReport?.summary
              || run.candidate?.summary
              || run.plan?.summary
              || run.observation?.summary
              || statusLabel}
          </span>
        </div>
        <VButton type="button" variant="ghost" isDisabled>
          {statusLabel}
        </VButton>
      </header>

      <div className={styles.phaseGrid} aria-label={lang === "zh" ? "闭环阶段" : "Loop phases"}>
        {PHASES.map((item, index) => (
          <div
            key={item.id}
            className={[
              styles.phase,
              index === currentIndex ? styles.phaseCurrent : "",
              index < currentIndex || completed ? styles.phaseDone : "",
            ].filter(Boolean).join(" ")}
          >
            <span className={styles.phaseLabel}>{lang === "zh" ? item.zh : item.en}</span>
            <span className={styles.phaseStatus}>
              {index < currentIndex || completed
                ? lang === "zh" ? "已完成" : "Done"
                : index === currentIndex
                  ? lang === "zh" ? "当前" : "Current"
                  : lang === "zh" ? "待处理" : "Pending"}
            </span>
          </div>
        ))}
      </div>

      <VMetricStrip
        ariaLabel={lang === "zh" ? "自动闭环摘要" : "Autonomous loop summary"}
        status={{ label: statusLabel, tone: completed ? "success" : awaitingReview ? "warning" : "info" }}
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

      <div className={styles.cards}>
        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <strong className={styles.cardTitle}>{lang === "zh" ? "观察现状" : "Observation"}</strong>
            <ConversationLink lang={lang} sessionId={run.observation?.conversationSessionId} />
          </div>
          <p className={styles.cardBody}>{run.observation?.summary || "--"}</p>
        </section>
        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <strong className={styles.cardTitle}>{lang === "zh" ? "制定计划" : "Plan"}</strong>
            <ConversationLink lang={lang} sessionId={run.plan?.conversationSessionId} />
          </div>
          <p className={styles.cardBody}>{run.plan?.summary || "--"}</p>
        </section>
        <section className={styles.card}>
          <div className={styles.cardHeader}>
            <strong className={styles.cardTitle}>{lang === "zh" ? "隔离进化" : "Isolated evolution"}</strong>
            <ConversationLink lang={lang} sessionId={run.candidate?.conversationSessionId} />
          </div>
          <p className={styles.cardBody}>{run.candidate?.summary || "--"}</p>
        </section>
      </div>

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

      {failed ? (
        <VStateSurface
          title={lang === "zh" ? "自动闭环未完成" : "Autonomous loop did not complete"}
          tone="error"
          icon={<X size={15} />}
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
