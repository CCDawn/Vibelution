import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { VStatusChip, VSurface, VTooltip } from "../../../components/vui";
import {
  challengeDimensionLabel,
  challengeGateLabel,
  challengeRatingLabel,
  ChallengeQuestionSectionHeading,
  ChallengeStringList,
} from "./ChallengeQuestionDetailPrimitives";
import css from "./ChallengeQuestionDetailPanel.styles";

type ChallengeQuestionAnalysisSectionProps = {
  output: ChallengeQuestionRunDetailPayload["output"];
};

export function ChallengeQuestionAnalysisSection({ output }: ChallengeQuestionAnalysisSectionProps) {
  const selectedHypothesis = output.hypotheses.find(
    (hypothesis) => hypothesis.hypothesis_id === output.selection.selected_hypothesis_id,
  );
  const reviewsByHypothesis = new Map<string, typeof output.dimension_reviews>();
  output.dimension_reviews.forEach((review) => {
    const reviews = reviewsByHypothesis.get(review.hypothesis_id) ?? [];
    reviews.push(review);
    reviewsByHypothesis.set(review.hypothesis_id, reviews);
  });

  return (
    <>
      <section className={css.section} id="hypotheses">
        <ChallengeQuestionSectionHeading index="03" title="候选假设" />
        <div className={css.twoColumn}>
          {output.hypotheses.map((hypothesis) => (
            <article className={css.hypothesisCard} key={hypothesis.hypothesis_id}>
              <div className={css.cardTopline}>
                <strong>{hypothesis.hypothesis_id}</strong>
                {hypothesis.hypothesis_id === output.selection.selected_hypothesis_id
                  ? <VStatusChip tone="accent">最终选择</VStatusChip>
                  : <VStatusChip tone="neutral">备选</VStatusChip>}
              </div>
              <h4>{hypothesis.statement}</h4>
              <dl>
                <div><dt>机制</dt><dd>{hypothesis.mechanism}</dd></div>
                <div><dt>新颖性依据</dt><dd>{hypothesis.novelty_basis}</dd></div>
                <div><dt>如何证伪</dt><dd>{hypothesis.falsifiability}</dd></div>
                <div><dt>预测</dt><dd><ChallengeStringList values={hypothesis.predictions} /></dd></div>
                <div><dt>支持证据</dt><dd>{hypothesis.supporting_evidence_refs.join(" · ")}</dd></div>
                <div><dt>挑战证据</dt><dd>{hypothesis.challenging_evidence_refs.join(" · ") || "无"}</dd></div>
                <div><dt>适用边界</dt><dd><ChallengeStringList values={hypothesis.boundary_conditions} /></dd></div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <section className={css.section} id="reviews">
        <ChallengeQuestionSectionHeading index="04" title="七维评价" />
        <div className={css.reviewGroups}>
          {output.hypotheses.map((hypothesis) => (
            <article key={hypothesis.hypothesis_id}>
              <h4>{hypothesis.hypothesis_id}</h4>
              <div className={css.reviewGrid}>
                {(reviewsByHypothesis.get(hypothesis.hypothesis_id) ?? []).map((review) => (
                  <VTooltip
                    content={`${review.rationale} · ${review.evidence_refs.join(" · ") || "未登记"} · ${review.reviewer}`}
                    key={`${review.hypothesis_id}-${review.dimension}`}
                    width="wide"
                  >
                    <div>
                      <span>{challengeDimensionLabel(review.dimension)}</span>
                      <strong>{challengeRatingLabel(review.rating)}</strong>
                    </div>
                  </VTooltip>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className={css.section} id="selection">
        <ChallengeQuestionSectionHeading index="05" title="选择" />
        <VSurface className={css.selection} tone="card">
          <div>
            <span>被选假设</span>
            <strong>{output.selection.selected_hypothesis_id}</strong>
            <p>{selectedHypothesis?.statement || "未找到对应假设"}</p>
          </div>
          <div>
            <span>比较方法</span>
            <strong>{output.selection.comparison_method}</strong>
            <ChallengeStringList values={output.selection.tradeoffs} />
          </div>
          <div>
            <span>人工门禁</span>
            <strong>{challengeGateLabel(output.selection.human_gate.decision)}</strong>
            <p>{output.selection.human_gate.rationale}</p>
          </div>
          <div>
            <span>未选择项</span>
            {output.selection.rejected_hypotheses.map((item) => (
              <p key={item.hypothesis_id}><strong>{item.hypothesis_id}</strong> · {item.reason}</p>
            ))}
          </div>
        </VSurface>
      </section>
    </>
  );
}
