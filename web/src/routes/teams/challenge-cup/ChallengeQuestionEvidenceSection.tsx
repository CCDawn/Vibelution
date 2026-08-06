import { ExternalLink } from "lucide-react";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { VStatusChip, VSurface } from "../../../components/vui";
import {
  ChallengeQuestionSectionHeading,
  ChallengeStringList,
} from "./ChallengeQuestionDetailPrimitives";
import css from "./ChallengeQuestionDetailPanel.styles";

type ChallengeQuestionEvidenceSectionProps = {
  detail: ChallengeQuestionRunDetailPayload;
};

export function ChallengeQuestionEvidenceSection({ detail }: ChallengeQuestionEvidenceSectionProps) {
  const { output, record } = detail;

  return (
    <>
      <section className={css.section} id="question-agent">
        <ChallengeQuestionSectionHeading index="01" title="题目与接单" />
        <div className={css.factGrid}>
          <VSurface tone="inset"><span>题号</span><strong>{detail.questionId}</strong></VSurface>
          <VSurface tone="inset"><span>运行</span><strong>{detail.selectedRunId}</strong></VSurface>
          <VSurface tone="inset"><span>登记执行者</span><strong>{record.registeredBy || "未登记"}</strong></VSurface>
          <VSurface tone="inset"><span>模型</span><strong>{output.run.model_id}</strong></VSurface>
        </div>
        <VSurface className={css.explanation} tone="card">
          <strong>问题理解</strong>
          <p>{output.problem_understanding.scope}</p>
          <dl>
            <div><dt>子问题</dt><dd><ChallengeStringList values={output.problem_understanding.subquestions} /></dd></div>
            <div><dt>假设前提</dt><dd><ChallengeStringList values={output.problem_understanding.assumptions} /></dd></div>
            <div><dt>已知未知</dt><dd><ChallengeStringList values={output.problem_understanding.known_unknowns} /></dd></div>
          </dl>
        </VSurface>
      </section>

      <section className={css.section} id="sources">
        <ChallengeQuestionSectionHeading index="02" title="来源与证据" />
        <div className={css.cardList}>
          {output.evidence.map((evidence) => (
            <article className={css.evidenceCard} key={evidence.evidence_id}>
              <div className={css.cardTopline}>
                <strong>{evidence.evidence_id} · {evidence.title}</strong>
                <VStatusChip tone={evidence.relation === "challenges" ? "warning" : "neutral"}>
                  {evidence.relation}
                </VStatusChip>
              </div>
              <div className={css.metadata}>
                <span>{evidence.source_type}</span>
                <span>{evidence.verification_status}</span>
                {evidence.doi ? <span>DOI {evidence.doi}</span> : null}
                <a href={evidence.source_url} target="_blank" rel="noreferrer noopener">
                  打开来源 <ExternalLink size={13} aria-hidden="true" />
                </a>
              </div>
              <div className={css.fact}>
                <span>证据事实</span>
                <p>{evidence.fact}</p>
              </div>
              <div className={css.missingLine}>证据锚点未登记</div>
              {evidence.limitations?.length ? (
                <div><strong>限制</strong><ChallengeStringList values={evidence.limitations} /></div>
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
