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
  lang?: "zh" | "en";
};

export function ChallengeQuestionAnalysisSection({ output, lang = "zh" }: ChallengeQuestionAnalysisSectionProps) {
  const isZh = lang === "zh";
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
        <ChallengeQuestionSectionHeading index="03" title={isZh ? "候选假设" : "Candidate hypotheses"} />
        <div className={css.twoColumn}>
          {output.hypotheses.map((hypothesis) => (
            <article className={css.hypothesisCard} key={hypothesis.hypothesis_id}>
              <div className={css.cardTopline}>
                <strong>{hypothesis.hypothesis_id}</strong>
                {hypothesis.hypothesis_id === output.selection.selected_hypothesis_id
                  ? <VStatusChip tone="accent">{isZh ? "最终选择" : "Selected"}</VStatusChip>
                  : <VStatusChip tone="neutral">{isZh ? "备选" : "Alternative"}</VStatusChip>}
              </div>
              <h4>{hypothesis.statement}</h4>
              <dl>
                <div><dt>{isZh ? "机制" : "Mechanism"}</dt><dd>{hypothesis.mechanism}</dd></div>
                <div><dt>{isZh ? "新颖性依据" : "Novelty basis"}</dt><dd>{hypothesis.novelty_basis}</dd></div>
                <div><dt>{isZh ? "如何证伪" : "Falsifiability"}</dt><dd>{hypothesis.falsifiability}</dd></div>
                <div><dt>{isZh ? "预测" : "Predictions"}</dt><dd><ChallengeStringList values={hypothesis.predictions} lang={lang} /></dd></div>
                <div><dt>{isZh ? "支持证据" : "Supporting evidence"}</dt><dd>{hypothesis.supporting_evidence_refs.join(" · ")}</dd></div>
                <div><dt>{isZh ? "挑战证据" : "Challenging evidence"}</dt><dd>{hypothesis.challenging_evidence_refs.join(" · ") || (isZh ? "无" : "None")}</dd></div>
                <div><dt>{isZh ? "适用边界" : "Boundary conditions"}</dt><dd><ChallengeStringList values={hypothesis.boundary_conditions} lang={lang} /></dd></div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <section className={css.section} id="reviews">
        <ChallengeQuestionSectionHeading index="04" title={isZh ? "七维评价" : "Seven-dim review"} />
        <div className={css.reviewGroups}>
          {output.hypotheses.map((hypothesis) => (
            <article key={hypothesis.hypothesis_id}>
              <h4>{hypothesis.hypothesis_id}</h4>
              <div className={css.reviewGrid}>
                {(reviewsByHypothesis.get(hypothesis.hypothesis_id) ?? []).map((review) => (
                  <VTooltip
                    content={`${review.rationale} · ${review.evidence_refs.join(" · ") || (isZh ? "未登记" : "Not registered")} · ${review.reviewer}`}
                    key={`${review.hypothesis_id}-${review.dimension}`}
                    width="wide"
                  >
                    <div>
                      <span>{challengeDimensionLabel(review.dimension, lang)}</span>
                      <strong>{challengeRatingLabel(review.rating, lang)}</strong>
                    </div>
                  </VTooltip>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className={css.section} id="selection">
        <ChallengeQuestionSectionHeading index="05" title={isZh ? "选择" : "Selection"} />
        <VSurface className={css.selection} tone="card">
          <div>
            <span>{isZh ? "被选假设" : "Selected hypothesis"}</span>
            <strong>{output.selection.selected_hypothesis_id}</strong>
            <p>{selectedHypothesis?.statement || (isZh ? "未找到对应假设" : "Matching hypothesis not found")}</p>
          </div>
          <div>
            <span>{isZh ? "比较方法" : "Comparison method"}</span>
            <strong>{output.selection.comparison_method}</strong>
            <ChallengeStringList values={output.selection.tradeoffs} lang={lang} />
          </div>
          <div>
            <span>{isZh ? "人工门禁" : "Human gate"}</span>
            <strong>{challengeGateLabel(output.selection.human_gate.decision, lang)}</strong>
            <p>{output.selection.human_gate.rationale}</p>
          </div>
          <div>
            <span>{isZh ? "未选择项" : "Rejected"}</span>
            {output.selection.rejected_hypotheses.map((item) => (
              <p key={item.hypothesis_id}><strong>{item.hypothesis_id}</strong> · {item.reason}</p>
            ))}
          </div>
        </VSurface>
      </section>
    </>
  );
}
