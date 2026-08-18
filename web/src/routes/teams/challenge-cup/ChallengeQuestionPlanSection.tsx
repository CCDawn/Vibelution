import { FileCheck2 } from "lucide-react";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { VSurface } from "../../../components/vui";
import {
  ChallengeQuestionSectionHeading,
  ChallengeStringList,
} from "./ChallengeQuestionDetailPrimitives";
import { ChallengeQuestionReviewForm } from "./ChallengeQuestionReviewForm";
import css from "./ChallengeQuestionDetailPanel.styles";

type ChallengeQuestionPlanSectionProps = {
  detail: ChallengeQuestionRunDetailPayload;
};

export function ChallengeQuestionPlanSection({ detail }: ChallengeQuestionPlanSectionProps) {
  const { artifact, output } = detail;
  return (
    <>
      <section className={css.section} id="plan">
        <ChallengeQuestionSectionHeading index="06" title="研究计划" />
        <VSurface className={css.plan} tone="card">
          <h4>{output.research_plan.objective}</h4>
          <p>{output.research_plan.method}</p>
          <div className={css.planGrid}>
            <div><strong>变量</strong><ChallengeStringList values={output.research_plan.variables} /></div>
            <div><strong>控制</strong><ChallengeStringList values={output.research_plan.controls} /></div>
            <div><strong>成功门槛</strong><ChallengeStringList values={output.research_plan.success_criteria} /></div>
            <div><strong>失败门槛</strong><ChallengeStringList values={output.research_plan.failure_criteria} /></div>
          </div>
          {output.research_plan.work_packages.map((workPackage) => (
            <article className={css.workPackage} key={workPackage.work_package_id}>
              <strong>{workPackage.work_package_id} · {workPackage.goal}</strong>
              <ChallengeStringList values={workPackage.procedure} />
              <small>产出：{workPackage.outputs.join(" · ") || "未登记"}</small>
            </article>
          ))}
        </VSurface>
      </section>

      <section className={css.section} id="feedback">
        <ChallengeQuestionSectionHeading index="07" title="人工审核" />
        <ChallengeQuestionReviewForm detail={detail} />
        <div className={css.timeline}>
          {output.feedback_iterations.map((iteration) => (
            <article key={iteration.round}>
              <span>第 {iteration.round} 轮</span>
              <div>
                <strong>{iteration.trigger}</strong>
                <p>{iteration.human_feedback}</p>
                <ChallengeStringList values={iteration.changes} />
                {iteration.unresolved_issues.length ? (
                  <small>未解决：{iteration.unresolved_issues.join(" · ")}</small>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className={css.section} id="artifact">
        <ChallengeQuestionSectionHeading index="08" title="最终工件" />
        <VSurface className={css.artifact} tone="inset">
          <FileCheck2 size={20} aria-hidden="true" />
          <div>
            <strong>{artifact.immutable ? "不可变审核工件" : "可变工件"}</strong>
            <code>{artifact.path}</code>
            <code>SHA256 {artifact.sha256}</code>
          </div>
        </VSurface>
      </section>
    </>
  );
}
