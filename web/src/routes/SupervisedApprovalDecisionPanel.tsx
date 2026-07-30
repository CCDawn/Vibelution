import {
  AlertTriangle,
  CheckCircle2,
  GitMerge,
  LoaderCircle,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import type { SupervisedWorktreeRun } from "../api/types";
import {
  VButton,
  VChip,
} from "../components/vui";
import {
  buildSupervisedApprovalDecision,
  type SupervisedApprovalAction,
  type SupervisedApprovalTone,
} from "./supervisedApprovalDecision";
import styles from "./SupervisedApprovalDecisionPanel.styles";

type SupervisedApprovalDecisionPanelProps = {
  run: SupervisedWorktreeRun | null | undefined;
  lang: "zh" | "en";
  pending: boolean;
  error?: string;
  onAction: (runId: string, action: SupervisedApprovalAction) => void;
};

const TONE_MAP: Record<SupervisedApprovalTone, "neutral" | "info" | "warning" | "success" | "danger"> = {
  neutral: "neutral",
  info: "info",
  warning: "warning",
  success: "success",
  danger: "danger",
};

function formatScore(value: number | null) {
  if (value === null) {
    return "--";
  }
  return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function formatDelta(value: number | null) {
  if (value === null) {
    return "--";
  }
  return `${value >= 0 ? "+" : ""}${formatScore(value)}`;
}

function actionStateKey(action: SupervisedApprovalAction) {
  return action === "approve_review" ? "approveReview" : action;
}

function actionIcon(action: SupervisedApprovalAction, pending: boolean) {
  if (pending) {
    return <LoaderCircle size={15} aria-hidden="true" />;
  }
  if (action === "approve_review") {
    return <ShieldCheck size={15} aria-hidden="true" />;
  }
  if (action === "merge") {
    return <GitMerge size={15} aria-hidden="true" />;
  }
  return <RotateCcw size={15} aria-hidden="true" />;
}

export function SupervisedApprovalDecisionPanel({
  run,
  lang,
  pending,
  error = "",
  onAction,
}: SupervisedApprovalDecisionPanelProps) {
  const model = buildSupervisedApprovalDecision(run, lang);
  const primaryActionState = model.primaryAction && run
    ? run.actionStates?.[actionStateKey(model.primaryAction)]
    : null;
  const primaryActionEnabled = Boolean(model.primaryAction && run && primaryActionState?.enabled);
  const primaryActionDisabledReason = pending
    ? lang === "zh" ? "治理动作正在执行，请等待状态刷新。" : "Governance action is running; wait for state refresh."
    : model.primaryActionReason || primaryActionState?.reason || "";

  return (
    <section
      aria-label={lang === "zh" ? "用户审批决策工作台" : "Approval decision workbench"}
      aria-busy={pending}
      className={styles.panel}
      data-vui-recipe="supervised-approval-decision"
    >
      <header className={styles.header}>
        <div>
          <p>{lang === "zh" ? "用户审批 · 决策工作台" : "Approval · Decision workbench"}</p>
          <h3>{lang === "zh" ? "是否批准 Judge 受控合入" : "Approve the Judge-controlled merge?"}</h3>
        </div>
        <VChip tone={TONE_MAP[model.tone]}>{model.statusLabel}</VChip>
      </header>

      <section className={styles.decisionBanner} data-tone={model.tone}>
        <div className={styles.decisionCopy}>
          <small>{lang === "zh" ? "Judge 建议（仅供参考）" : "Judge recommendation (advisory)"}</small>
          <VChip tone="neutral">{model.judgeRecommendation.label}</VChip>
          <strong>{model.headline}</strong>
          <p>{model.reason}</p>
        </div>
        <div className={styles.delta}>
          <span>{lang === "zh" ? "评分变化" : "Score delta"}</span>
          <strong>{formatDelta(model.metrics.scoreDelta)}</strong>
        </div>
      </section>

      <section
        aria-label={lang === "zh" ? "候选对比指标" : "Candidate comparison metrics"}
        className={styles.metrics}
      >
        <article className={styles.metric}>
          <span>{lang === "zh" ? "基线得分" : "Baseline score"}</span>
          <strong>{formatScore(model.metrics.baselineScore)}</strong>
          <small>{lang === "zh" ? "Judge 首次评分" : "First Judge score"}</small>
        </article>
        <article className={styles.metric}>
          <span>{lang === "zh" ? "候选得分" : "Candidate score"}</span>
          <strong>{formatScore(model.metrics.candidateScore)}</strong>
          <small>{lang === "zh" ? "同一 Judge 会话复评" : "Same Judge session"}</small>
        </article>
        <article className={styles.metric}>
          <span>{lang === "zh" ? "候选差异" : "Candidate diff"}</span>
          <strong>{model.metrics.changedFileCount}</strong>
          <small>{lang === "zh" ? "个文件" : "files"}</small>
        </article>
        <article className={styles.metric}>
          <span>{lang === "zh" ? "风险等级" : "Risk level"}</span>
          <strong>
            {model.metrics.highRiskFileCount > 0
              ? lang === "zh" ? "需要复核" : "Review required"
              : lang === "zh" ? "常规" : "Normal"}
          </strong>
          <small>
            {lang === "zh"
              ? `${model.metrics.highRiskFileCount} 个高风险文件`
              : `${model.metrics.highRiskFileCount} high-risk file(s)`}
          </small>
        </article>
      </section>

      <div className={styles.bodyGrid}>
        <section className={styles.evidenceSurface}>
          <h4 className={styles.sectionHeading}>{lang === "zh" ? "为什么给出这个建议" : "Why this recommendation"}</h4>
          <div className={styles.evidenceList}>
            {model.evidence.length > 0 ? model.evidence.map((item, index) => (
              <div key={`${item.tone}-${index}`} className={styles.evidenceItem} data-tone={item.tone}>
                <span aria-hidden="true">
                  {item.tone === "positive" ? "✓" : item.tone === "warning" ? "!" : "·"}
                </span>
                <span>{item.text}</span>
              </div>
            )) : (
              <div className={styles.evidenceItem} data-tone="neutral">
                <span aria-hidden="true">·</span>
                <span>{lang === "zh" ? "当前还没有可比较的评分或合并证据。" : "No comparable score or merge evidence yet."}</span>
              </div>
            )}
          </div>
        </section>

        <section className={styles.evidenceSurface}>
          <h4 className={styles.sectionHeading}>{lang === "zh" ? "改动影响" : "Change impact"}</h4>
          <div className={styles.impactGrid}>
            <article className={styles.impactItem}><span>{lang === "zh" ? "文件变更" : "Files"}</span><strong>{model.metrics.changedFileCount}</strong></article>
            <article className={styles.impactItem}><span>{lang === "zh" ? "高风险" : "High risk"}</span><strong>{model.metrics.highRiskFileCount}</strong></article>
            <article className={styles.impactItem}><span>{lang === "zh" ? "重叠冲突" : "Overlaps"}</span><strong>{model.metrics.overlapFileCount}</strong></article>
            <article className={styles.impactItem}><span>{lang === "zh" ? "阻塞项" : "Blockers"}</span><strong>{model.metrics.blockerCount}</strong></article>
          </div>
        </section>
      </div>

      {model.rubric.taskCriteria.length > 0 || model.rubric.systemCriteria.length > 0 ? (
        <details className={styles.detail}>
          <summary>
            <span>{lang === "zh" ? "查看本轮冻结评分表" : "View frozen rubric"}</span>
            <span className={styles.detailMeta}>
              {model.rubric.hash ? `#${model.rubric.hash.slice(0, 10)}` : "--"}
            </span>
          </summary>
          <div className={styles.bodyGrid}>
            <section className={styles.evidenceSurface}>
              <h4 className={styles.sectionHeading}>
                {lang === "zh" ? "任务定向标准" : "Task-specific criteria"}
                {model.rubric.taskWeight !== null ? ` · ${formatScore(model.rubric.taskWeight * 100)}%` : ""}
              </h4>
              <div className={styles.evidenceList}>
                {model.rubric.taskCriteria.map((criterion) => (
                  <div key={criterion.id} className={styles.rubricCriterionItem} data-tone="neutral">
                    <span>{formatScore(criterion.weight * 100)}%</span>
                    <span>
                      <strong>{criterion.label}</strong>
                      {" · "}
                      {criterion.description}
                      <br />
                      <small>
                        {lang === "zh"
                          ? `基线 ${formatScore(criterion.baselineScore)} → 改进后 ${formatScore(criterion.candidateScore)}`
                          : `Baseline ${formatScore(criterion.baselineScore)} → Rerun ${formatScore(criterion.candidateScore)}`}
                      </small>
                    </span>
                  </div>
                ))}
                <div className={styles.evidenceItem} data-tone="neutral">
                  <span aria-hidden="true">↳</span>
                  <span>
                    {lang === "zh"
                      ? `基线 ${formatScore(model.metrics.baselineTaskScore)} · 改进后 ${formatScore(model.metrics.candidateTaskScore)}`
                      : `Baseline ${formatScore(model.metrics.baselineTaskScore)} · Rerun ${formatScore(model.metrics.candidateTaskScore)}`}
                  </span>
                </div>
              </div>
            </section>
            <section className={styles.evidenceSurface}>
              <h4 className={styles.sectionHeading}>
                {lang === "zh" ? "系统固定评分表" : "System-fixed criteria"}
                {model.rubric.systemWeight !== null ? ` · ${formatScore(model.rubric.systemWeight * 100)}%` : ""}
              </h4>
              <div className={styles.evidenceList}>
                {model.rubric.systemCriteria.map((criterion) => (
                  <div key={criterion.id} className={styles.rubricCriterionItem} data-tone="neutral">
                    <span>{formatScore(criterion.weight * 100)}%</span>
                    <span>
                      <strong>{criterion.label}</strong>
                      {" · "}
                      {criterion.description}
                      <br />
                      <small>
                        {lang === "zh"
                          ? `基线 ${formatScore(criterion.baselineScore)} → 改进后 ${formatScore(criterion.candidateScore)}`
                          : `Baseline ${formatScore(criterion.baselineScore)} → Rerun ${formatScore(criterion.candidateScore)}`}
                      </small>
                    </span>
                  </div>
                ))}
                <div className={styles.evidenceItem} data-tone="neutral">
                  <span aria-hidden="true">↳</span>
                  <span>
                    {lang === "zh"
                      ? `基线 ${formatScore(model.metrics.baselineSystemScore)} · 改进后 ${formatScore(model.metrics.candidateSystemScore)}`
                      : `Baseline ${formatScore(model.metrics.baselineSystemScore)} · Rerun ${formatScore(model.metrics.candidateSystemScore)}`}
                  </span>
                </div>
              </div>
            </section>
          </div>
        </details>
      ) : null}

      {model.blockers.length > 0 ? (
        <ul className={styles.blockerList}>
          {model.blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
        </ul>
      ) : null}

      {model.changedFiles.length > 0 ? (
        <details className={styles.detail}>
          <summary>
            <span>{lang === "zh" ? "查看候选文件差异" : "View candidate file diff"}</span>
            <span className={styles.detailMeta}>{model.changedFiles.length} files · {lang === "zh" ? "默认收起" : "collapsed"}</span>
          </summary>
          <div className={styles.fileList}>
            {model.changedFiles.map((file) => (
              <div key={file.path} className={styles.fileRow}>
                <code title={file.path}>{file.path}</code>
                <span>{file.changeType || file.status || "--"}</span>
                {file.highRisk ? <VChip tone="warning">{lang === "zh" ? "高风险" : "High risk"}</VChip> : null}
              </div>
            ))}
          </div>
        </details>
      ) : null}

      <section aria-label={lang === "zh" ? "治理动作路径" : "Governance action path"} className={styles.actionSection}>
        <h4 className={styles.actionSectionHeading}>{lang === "zh" ? "治理动作路径" : "Governance action path"}</h4>
        <div className={styles.actionPath}>
          {model.steps.map((step) => (
            <article key={step.id} className={styles.actionCard} data-status={step.status}>
              <div className={styles.actionCardHeader}>
                <strong>{step.title}</strong>
                <VChip tone={step.status === "blocked" ? "danger" : step.status === "done" ? "success" : step.status === "active" ? "accent" : "neutral"}>
                  {step.statusLabel}
                </VChip>
              </div>
              <p>{step.description}</p>
              <small>{step.consequence}</small>
            </article>
          ))}
        </div>
      </section>

      {error ? <p role="alert" className={styles.error}>{error}</p> : null}

      <footer className={styles.actionBar}>
        <span className={styles.runtimeEffect}>
          {model.runtimeEffect === "refresh_required"
            ? <AlertTriangle size={14} aria-hidden="true" />
            : <CheckCircle2 size={14} aria-hidden="true" />}
          {model.runtimeEffectLabel}
        </span>
        {model.primaryAction && run ? (
          <VButton
            type="button"
            variant={model.primaryAction === "rollback" ? "danger" : "primary"}
            icon={actionIcon(model.primaryAction, pending)}
            isDisabled={pending || !primaryActionEnabled}
            disabledReason={primaryActionDisabledReason}
            onPress={() => onAction(run.runId, model.primaryAction as SupervisedApprovalAction)}
          >
            {pending
              ? lang === "zh" ? "正在执行" : "Working"
              : model.primaryActionLabel}
          </VButton>
        ) : (
          <VChip tone={model.phase === "rolled_back" ? "success" : "neutral"}>
            {model.phase === "rolled_back"
              ? lang === "zh" ? "已回滚" : "Rolled back"
              : lang === "zh" ? "暂无可执行动作" : "No action available"}
          </VChip>
        )}
      </footer>
    </section>
  );
}
