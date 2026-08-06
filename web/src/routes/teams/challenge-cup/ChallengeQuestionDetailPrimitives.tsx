import type { ChallengeQuestionDimensionReview } from "../../../api/types";
import css from "./ChallengeQuestionDetailPanel.styles";

const DIMENSION_LABELS: Record<string, string> = {
  evidence_support: "证据支持",
  factual_accuracy: "事实准确",
  novelty: "新颖性",
  falsifiability: "可证伪性",
  plan_feasibility: "计划可行性",
  risk_and_ethics: "风险与伦理",
  counterexample_coverage: "反例覆盖",
};

export function challengeGateLabel(decision: string) {
  if (decision === "approved") return "已批准";
  if (decision === "revision_requested") return "需修订";
  if (decision === "rejected") return "已拒绝";
  return "待审核";
}

export function challengeRatingLabel(rating: ChallengeQuestionDimensionReview["rating"]) {
  return {
    insufficient: "不足",
    weak: "较弱",
    mixed: "混合",
    adequate: "充分",
    strong: "强",
  }[rating];
}

export function challengeDimensionLabel(dimension: string) {
  return DIMENSION_LABELS[dimension] || dimension;
}

export function ChallengeQuestionSectionHeading({ index, title }: { index: string; title: string }) {
  return (
    <div className={css.sectionHeading}>
      <span>{index}</span>
      <div><h3>{title}</h3></div>
    </div>
  );
}

export function ChallengeStringList({ values }: { values: string[] }) {
  if (!values.length) {
    return <span className={css.missing}>未登记</span>;
  }
  return (
    <ul className={css.compactList}>
      {values.map((value) => <li key={value}>{value}</li>)}
    </ul>
  );
}
