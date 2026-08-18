import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, FlaskConical, Play, ShieldCheck } from "lucide-react";

import {
  VNativeButton,
  VNativeInput,
  VNativeTextarea,
  VPanelHeader,
  VStatusChip,
} from "../components/vui";
import type {
  EngineeringProxyHypothesisDraft,
  ExperimentHypothesisCandidateSummary,
  ExperimentPlanRecord,
} from "./teams/experimentLoopModel";
import { hypothesisProgressStepLabel } from "./teams/experimentWorkbenchStepModel";
import styles from "./TeamExperimentHypothesisGovernancePanel.styles";

type Lang = "zh" | "en";

export type TeamExperimentHypothesisGovernancePanelProps = {
  lang: Lang;
  activePlan: ExperimentPlanRecord | null;
  hypotheses: ExperimentHypothesisCandidateSummary[];
  materializing: boolean;
  reviewingCandidateId: string;
  revisingCandidateId: string;
  materializeError?: Error | null;
  reviewError?: Error | null;
  revisionError?: Error | null;
  resumeError?: Error | null;
  resuming?: boolean;
  onResume?: (candidateId: string) => void;
  onMaterialize: (
    plan: ExperimentPlanRecord,
    draft: EngineeringProxyHypothesisDraft,
  ) => void;
  onReview: (candidateId: string) => void;
  onCreateRevision: (
    plan: ExperimentPlanRecord,
    candidateId: string,
  ) => void;
};

export function createEngineeringProxyHypothesisDraft(
  plan: ExperimentPlanRecord | null,
): EngineeringProxyHypothesisDraft {
  if (!plan) {
    return {
      title: "工程代理假设",
      hypothesis: "",
      claimBoundary: "",
      expectedBenefit: "",
      expectedComputeCost: "",
    };
  }
  const metric = plan.experimentPlan.metric || "预注册主指标";
  const baseline = plan.experimentPlan.baseline || "固定 baseline";
  const dataset = plan.experimentPlan.dataset || "固定数据集";
  const budget = String(plan.experimentContract?.methodConfig?.budget || "").trim();
  const revision = plan.experimentContract?.revision ?? 1;
  return {
    title: `工程代理假设 · v${revision}`,
    hypothesis: (
      `在固定 seed 与相同 ${dataset} 下，当前候选流程相对 ${baseline} `
      + `可使 ${metric} 达到预注册成功门槛。`
    ),
    claimBoundary: (
      "仅验证当前实验设计的工程可执行性、复现性与门禁链路；"
      + "不支持任何未经独立证据验证的科学机制、生物学或临床结论。"
    ),
    expectedBenefit: `在受控条件下满足 ${metric} 的预注册成功标准。`,
    expectedComputeCost: budget || "遵循当前实验设计中冻结的预算。",
  };
}

function hypothesisStatusLabel(
  candidate: ExperimentHypothesisCandidateSummary,
  lang: Lang,
) {
  if (!candidate.valid || candidate.missingExperimentPlanFields.length > 0) {
    return lang === "zh" ? "需修订" : "Needs revision";
  }
  if (candidate.approvedForExperiment) {
    return lang === "zh" ? "已人工批准" : "Human approved";
  }
  if (candidate.reviewDecision === "reject") {
    return lang === "zh" ? "已拒绝" : "Rejected";
  }
  if (candidate.reviewDecision === "revise") {
    return lang === "zh" ? "待修订复核" : "Revision requested";
  }
  return lang === "zh" ? "待人工审核" : "Awaiting human review";
}

export function TeamExperimentHypothesisGovernancePanel(
  props: TeamExperimentHypothesisGovernancePanelProps,
) {
  const {
    lang,
    activePlan,
    hypotheses,
    materializing,
    reviewingCandidateId,
    revisingCandidateId,
    materializeError,
    reviewError,
    revisionError,
    resumeError,
    resuming = false,
    onResume,
    onMaterialize,
    onReview,
    onCreateRevision,
  } = props;
  const draftSeed = useMemo(
    () => createEngineeringProxyHypothesisDraft(activePlan),
    [activePlan],
  );
  const [draft, setDraft] = useState<EngineeringProxyHypothesisDraft>(draftSeed);

  useEffect(() => {
    setDraft(draftSeed);
  }, [draftSeed]);

  const activePlanHasGovernedSelection = Boolean(
    activePlan?.hypothesisSelection?.hypothesisCandidateId,
  );
  const planHasProxyCandidate = Boolean(
    activePlan
    && hypotheses.some(
      (candidate) => (
        candidate.hypothesisKind === "engineering_proxy"
        && candidate.sourcePlanId === activePlan.planId
      ),
    ),
  );
  const canMaterialize = Boolean(
    activePlan
    && !activePlanHasGovernedSelection
    && !planHasProxyCandidate
    && draft.title.trim()
    && draft.hypothesis.trim()
    && draft.claimBoundary.trim()
    && !materializing,
  );
  const error = materializeError || reviewError || revisionError || resumeError;

  return (
    <section
      aria-label={lang === "zh" ? "假设审查与设计选择" : "Hypothesis review and design selection"}
      className={styles.panel}
      data-experiment-hypothesis-governance="true"
    >
      <VPanelHeader
        className={styles.header}
        headingLevel={null}
        title={lang === "zh" ? "假设审查" : "Hypothesis review"}
        actions={(
          <span className={styles.guardBadge}>
            <ShieldCheck size={13} />
            {lang === "zh" ? "需人工批准" : "Human approval"}
          </span>
        )}
      />

      {activePlan && !activePlanHasGovernedSelection && !planHasProxyCandidate ? (
        <div className={styles.draftGrid}>
          <div className={styles.draftIntro}>
            <span className={styles.sectionLabel}>
              {lang === "zh" ? "生成候选" : "Create candidate"}
            </span>
            <VNativeInput
              aria-label={lang === "zh" ? "候选标题" : "Candidate title"}
              value={draft.title}
              onChange={(event) => setDraft((current) => ({
                ...current,
                title: event.target.value,
              }))}
            />
          </div>
          <div className={styles.draftFields}>
            <VNativeTextarea
              aria-label={lang === "zh" ? "假设" : "Hypothesis"}
              rows={2}
              value={draft.hypothesis}
              onChange={(event) => setDraft((current) => ({
                ...current,
                hypothesis: event.target.value,
              }))}
            />
            <VNativeTextarea
              aria-label={lang === "zh" ? "论断边界" : "Claim boundary"}
              rows={2}
              value={draft.claimBoundary}
              onChange={(event) => setDraft((current) => ({
                ...current,
                claimBoundary: event.target.value,
              }))}
            />
            <div className={styles.actionRow}>
              <VNativeButton
                type="button"
                disabled={!canMaterialize}
                onClick={() => activePlan && onMaterialize(activePlan, draft)}
              >
                <FlaskConical size={14} />
                {materializing
                  ? (lang === "zh" ? "生成中" : "Creating")
                  : (lang === "zh" ? "生成候选" : "Create candidate")}
              </VNativeButton>
            </div>
          </div>
        </div>
      ) : null}

      <div className={styles.candidateGrid}>
        {hypotheses.slice(0, 8).map((candidate) => {
          const complete = (
            candidate.valid
            && candidate.missingExperimentPlanFields.length === 0
          );
          const selectedByActivePlan = Boolean(
            activePlan?.hypothesisCandidateIds.includes(candidate.candidateId),
          );
          const canReview = (
            complete
            && !candidate.approvedForExperiment
            && candidate.reviewDecision !== "reject"
          );
          const canCreateRevision = Boolean(
            activePlan
            && candidate.approvedForExperiment
            && !selectedByActivePlan
          );
          return (
            <article
              key={candidate.candidateId}
              className={styles.candidateCard}
            >
              <div className={styles.candidateHeader}>
                <strong className={styles.candidateTitle}>
                  {candidate.title || candidate.candidateId}
                </strong>
                <VStatusChip tone="neutral">
                  {hypothesisStatusLabel(candidate, lang)}
                </VStatusChip>
              </div>
              <p className={styles.hypothesis} title={candidate.hypothesis || candidate.summary || undefined}>
                {candidate.hypothesis || candidate.summary || "-"}
              </p>
              {candidate.claimBoundary ? (
                <details className={styles.claimBoundary}>
                  <summary>{lang === "zh" ? "论断边界" : "Claim boundary"}</summary>
                  {candidate.claimBoundary}
                </details>
              ) : null}
              {candidate.missingExperimentPlanFields.length > 0 ? (
                <span className={styles.metadata}>
                  {lang === "zh" ? "仍缺：" : "Missing: "}
                  {candidate.missingExperimentPlanFields.join(", ")}
                </span>
              ) : (
                <span className={styles.metadata}>
                  {candidate.experimentPlan.dataset || "-"}
                  {" · "}
                  {candidate.experimentPlan.metric || "-"}
                </span>
              )}
              {candidate.hypothesisProgress ? (
                <div
                  className={styles.progressRow}
                  data-testid={`hypothesis-progress-${candidate.candidateId}`}
                >
                  <span className={styles.progressText}>
                    {lang === "zh"
                      ? `实验进展 ${candidate.hypothesisProgress.completedCount}/${candidate.hypothesisProgress.totalSteps}`
                      : `Progress ${candidate.hypothesisProgress.completedCount}/${candidate.hypothesisProgress.totalSteps}`}
                  </span>
                  {candidate.hypothesisProgress.status === "failed" ? (
                    <span className={styles.progressFailed}>
                      {lang === "zh"
                        ? `止步于${hypothesisProgressStepLabel(candidate.hypothesisProgress.currentStep, lang)}`
                        : `Failed at ${hypothesisProgressStepLabel(candidate.hypothesisProgress.currentStep, lang)}`}
                    </span>
                  ) : candidate.hypothesisProgress.nextStep ? (
                    <span className={styles.progressNext}>
                      {lang === "zh"
                        ? `下一步：${hypothesisProgressStepLabel(candidate.hypothesisProgress.nextStep, lang)}`
                        : `Next: ${hypothesisProgressStepLabel(candidate.hypothesisProgress.nextStep, lang)}`}
                    </span>
                  ) : (
                    <span className={styles.progressNext}>
                      {lang === "zh" ? "已完成全部步骤" : "All steps complete"}
                    </span>
                  )}
                  {onResume && candidate.hypothesisProgress.nextStep ? (
                    <VNativeButton
                      type="button"
                      disabled={resuming}
                      data-testid={`hypothesis-resume-${candidate.candidateId}`}
                      onClick={() => onResume(candidate.candidateId)}
                    >
                      <Play size={14} />
                      {resuming
                        ? (lang === "zh" ? "恢复中" : "Resuming")
                        : (lang === "zh" ? "继续此假设" : "Resume")}
                    </VNativeButton>
                  ) : null}
                </div>
              ) : null}
              <div className={styles.candidateActions}>
                {canReview ? (
                  <VNativeButton
                    type="button"
                    disabled={reviewingCandidateId === candidate.candidateId}
                    onClick={() => onReview(candidate.candidateId)}
                  >
                    <ShieldCheck size={14} />
                    {reviewingCandidateId === candidate.candidateId
                      ? (lang === "zh" ? "审核中" : "Reviewing")
                      : (lang === "zh" ? "人工批准用于设计" : "Approve for design")}
                  </VNativeButton>
                ) : null}
                {canCreateRevision ? (
                  <VNativeButton
                    type="button"
                    disabled={revisingCandidateId === candidate.candidateId}
                    onClick={() => activePlan && onCreateRevision(
                      activePlan,
                      candidate.candidateId,
                    )}
                  >
                    <CheckCircle2 size={14} />
                    {revisingCandidateId === candidate.candidateId
                      ? (lang === "zh" ? "创建中" : "Creating")
                      : (lang === "zh" ? "创建新设计修订" : "Create design revision")}
                  </VNativeButton>
                ) : null}
                {selectedByActivePlan ? (
                  <span className={styles.selected}>
                    <CheckCircle2 size={13} />
                    {lang === "zh" ? "当前设计已选择" : "Selected by active design"}
                  </span>
                ) : null}
              </div>
              {candidate.approvedForExperiment && !selectedByActivePlan ? (
                <span className={styles.approvalNote}>
                  {lang === "zh"
                    ? "新修订不会自动冻结，也不会运行 Smoke。"
                    : "The new revision will not auto-freeze or run Smoke."}
                </span>
              ) : null}
            </article>
          );
        })}
        {hypotheses.length === 0 ? (
          <span className={styles.empty}>
            {lang === "zh"
              ? "暂无假设候选。请先保存完整实验设计，再生成工程代理候选。"
              : "No hypothesis candidates. Save a complete design before creating an engineering proxy."}
          </span>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className={styles.alert}>
          {error.message}
        </p>
      ) : null}
    </section>
  );
}
