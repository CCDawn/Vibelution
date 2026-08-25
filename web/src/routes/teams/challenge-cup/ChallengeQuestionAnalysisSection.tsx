import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { VNativeButton, VStatusChip, VSurface, VTooltip } from "../../../components/vui";
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
  summaryOnly?: boolean;
};

export function ChallengeQuestionAnalysisSection({ output, lang = "zh", summaryOnly = false }: ChallengeQuestionAnalysisSectionProps) {
  const isZh = lang === "zh";
  const [expandedHypothesisId, setExpandedHypothesisId] = useState(
    output.selection.selected_hypothesis_id || output.hypotheses[0]?.hypothesis_id || "",
  );
  const selectedHypothesis = output.hypotheses.find(
    (hypothesis) => hypothesis.hypothesis_id === output.selection.selected_hypothesis_id,
  );
  const reviewsByHypothesis = new Map<string, typeof output.dimension_reviews>();
  output.dimension_reviews.forEach((review) => {
    const reviews = reviewsByHypothesis.get(review.hypothesis_id) ?? [];
    reviews.push(review);
    reviewsByHypothesis.set(review.hypothesis_id, reviews);
  });

  if (summaryOnly) {
    return (
      <section className={css.section} id="hypotheses">
        <ChallengeQuestionSectionHeading
          index="01"
          title={isZh ? "假说摘要" : "Hypothesis summary"}
        />
        <p className={css.archiveHint}>
          {isZh ? "默认只展开一条，需要核验时再切换。" : "One item stays open; switch only when you need details."}
        </p>
        <div className={css.hypothesisSummaryList}>
          {output.hypotheses.map((hypothesis, index) => {
            const expanded = hypothesis.hypothesis_id === expandedHypothesisId;
            const panelId = `question-archive-hypothesis-${index}`;
            return (
              <article className={css.hypothesisSummaryCard} key={hypothesis.hypothesis_id}>
                <VNativeButton
                  type="button"
                  className={css.hypothesisToggle}
                  aria-expanded={expanded}
                  aria-controls={panelId}
                  onClick={() => setExpandedHypothesisId((current) => current === hypothesis.hypothesis_id ? "" : hypothesis.hypothesis_id)}
                >
                  <span className={css.hypothesisToggleCopy}>
                    <span className={css.hypothesisIndex}>{index + 1}</span>
                    <strong>{hypothesis.statement}</strong>
                    {hypothesis.hypothesis_id === output.selection.selected_hypothesis_id ? (
                      <VStatusChip tone="accent">{isZh ? "最终选择" : "Selected"}</VStatusChip>
                    ) : null}
                  </span>
                  {expanded ? <ChevronDown size={17} aria-hidden="true" /> : <ChevronRight size={17} aria-hidden="true" />}
                </VNativeButton>
                {expanded ? (
                  <div className={css.hypothesisSummaryDetail} id={panelId}>
                    <dl>
                      <div><dt>{isZh ? "机制" : "Mechanism"}</dt><dd>{hypothesis.mechanism}</dd></div>
                      <div><dt>{isZh ? "如何证伪" : "Falsifiability"}</dt><dd>{hypothesis.falsifiability}</dd></div>
                      <div><dt>{isZh ? "适用边界" : "Boundary conditions"}</dt><dd><ChallengeStringList values={hypothesis.boundary_conditions} lang={lang} /></dd></div>
                    </dl>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>
    );
  }

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
                    <div
                      tabIndex={0}
                      className="focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-[var(--accent-cool)]"
                    >
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
