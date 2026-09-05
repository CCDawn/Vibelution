import { FileCheck2 } from "lucide-react";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { VStatusChip, VSurface } from "../../../components/vui";
import {
  ChallengeQuestionSectionHeading,
  ChallengeStringList,
} from "./ChallengeQuestionDetailPrimitives";
import { ChallengeQuestionReviewForm } from "./ChallengeQuestionReviewForm";
import {
  stageTwoProgressHint,
  stageTwoStatusCopy,
  type ChallengeQuestionStageProjection,
} from "./challengeQuestionStageModel";
import css from "./ChallengeQuestionDetailPanel.styles";

type ChallengeQuestionPlanSectionProps = {
  detail: ChallengeQuestionRunDetailPayload;
  stageProjection: ChallengeQuestionStageProjection;
  lang?: "zh" | "en";
};

export function ChallengeQuestionPlanSection({ detail, stageProjection, lang = "zh" }: ChallengeQuestionPlanSectionProps) {
  const isZh = lang === "zh";
  const { artifact, output } = detail;
  const planCard = stageProjection.hasResearchPlanProposal ? (
    <VSurface className={css.plan} tone="card">
      <h4>{output.research_plan.objective}</h4>
      <p>{output.research_plan.method}</p>
      <div className={css.planGrid}>
        <div><strong>{isZh ? "变量" : "Variables"}</strong><ChallengeStringList values={output.research_plan.variables} lang={lang} /></div>
        <div><strong>{isZh ? "控制" : "Controls"}</strong><ChallengeStringList values={output.research_plan.controls} lang={lang} /></div>
        <div><strong>{isZh ? "成功门槛" : "Success criteria"}</strong><ChallengeStringList values={output.research_plan.success_criteria} lang={lang} /></div>
        <div><strong>{isZh ? "失败门槛" : "Failure criteria"}</strong><ChallengeStringList values={output.research_plan.failure_criteria} lang={lang} /></div>
      </div>
      {output.research_plan.work_packages.map((workPackage) => (
        <article className={css.workPackage} key={workPackage.work_package_id}>
          <strong>{workPackage.work_package_id} · {workPackage.goal}</strong>
          <ChallengeStringList values={workPackage.procedure} lang={lang} />
          <small>{isZh ? "产出：" : "Outputs: "}{workPackage.outputs.join(" · ") || (isZh ? "未登记" : "Not registered")}</small>
        </article>
      ))}
    </VSurface>
  ) : (
    <VSurface className={css.plan} tone="card" data-testid="question-plan-pending-empty">
      <p className={css.archiveHint}>
        {isZh ? "本题尚无研究计划产物。" : "No research-plan artifact yet. "}
        {stageTwoProgressHint(stageProjection.stageTwoActive, lang)}
      </p>
    </VSurface>
  );
  return (
    <>
      <section className={css.section} id="plan">
        <div className={css.sectionHeadingRow}>
          <ChallengeQuestionSectionHeading index="06" title={isZh ? "研究计划" : "Research plan"} />
          <VStatusChip tone={stageProjection.stageTwoActive ? "accent" : "neutral"}>
            {stageTwoStatusCopy(stageProjection.stageTwoActive, lang)}
          </VStatusChip>
        </div>
        {planCard}
      </section>

      <section className={css.section} id="feedback">
        <ChallengeQuestionSectionHeading index="07" title={isZh ? "人工审核" : "Human review"} />
        <ChallengeQuestionReviewForm detail={detail} lang={lang} />
        <div className={css.timeline}>
          {output.feedback_iterations.map((iteration) => (
            <article key={iteration.round}>
              <span>{isZh ? `第 ${iteration.round} 轮` : `Round ${iteration.round}`}</span>
              <div>
                <strong>{iteration.trigger}</strong>
                <p>{iteration.human_feedback}</p>
                <ChallengeStringList values={iteration.changes} lang={lang} />
                {iteration.unresolved_issues.length ? (
                  <small>{isZh ? "未解决：" : "Unresolved: "}{iteration.unresolved_issues.join(" · ")}</small>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className={css.section} id="artifact">
        <ChallengeQuestionSectionHeading index="08" title={isZh ? "最终工件" : "Final artifact"} />
        <VSurface className={css.artifact} tone="inset">
          <FileCheck2 size={20} aria-hidden="true" />
          <div>
            <strong>{artifact.immutable ? (isZh ? "不可变审核工件" : "Immutable review artifact") : (isZh ? "可变工件" : "Mutable artifact")}</strong>
            <details className={css.techDetails}>
              <summary>{isZh ? "技术细节" : "Technical details"}</summary>
              <code>{artifact.path}</code>
              <code>SHA256 {artifact.sha256}</code>
            </details>
          </div>
        </VSurface>
      </section>
    </>
  );
}
