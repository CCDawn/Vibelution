import type { ChallengeQuestionDimensionReview } from "../../../api/types";
import css from "./ChallengeQuestionDetailPanel.styles";

const RECORD_STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  approved: "正式批准",
  pending_review: "待审核",
  review_required: "待审核",
  needs_revision: "需修改",
  rejected: "已驳回",
  blocked: "已阻塞",
  failed: "失败",
};

const RECORD_STATUS_LABELS_EN: Record<string, string> = {
  draft: "Draft",
  approved: "Approved",
  pending_review: "Pending review",
  review_required: "Pending review",
  needs_revision: "Changes requested",
  rejected: "Rejected",
  blocked: "Blocked",
  failed: "Failed",
};

const VALIDATION_STATUS_LABELS: Record<string, string> = {
  passed: "通过",
  failed: "失败",
  pending: "待定",
  skipped: "已跳过",
};

const VALIDATION_STATUS_LABELS_EN: Record<string, string> = {
  passed: "Passed",
  failed: "Failed",
  pending: "Pending",
  skipped: "Skipped",
};

const EVIDENCE_SOURCE_TYPE_LABELS: Record<string, string> = {
  peer_reviewed_paper: "同行评审论文",
  preprint: "预印本",
  dataset: "数据集",
  standard: "标准",
  official_document: "官方文档",
  book: "书籍",
  other: "其他",
};

const EVIDENCE_SOURCE_TYPE_LABELS_EN: Record<string, string> = {
  peer_reviewed_paper: "Peer-reviewed paper",
  preprint: "Preprint",
  dataset: "Dataset",
  standard: "Standard",
  official_document: "Official document",
  book: "Book",
  other: "Other",
};

const EVIDENCE_VERIFICATION_STATUS_LABELS: Record<string, string> = {
  unverified: "未验证",
  metadata_checked: "元数据已核验",
  full_text_checked: "全文已核验",
  human_verified: "人工已核验",
};

const EVIDENCE_VERIFICATION_STATUS_LABELS_EN: Record<string, string> = {
  unverified: "Unverified",
  metadata_checked: "Metadata checked",
  full_text_checked: "Full text checked",
  human_verified: "Human verified",
};

export function challengeRecordStatusLabel(status: string, lang: "zh" | "en" = "zh"): string {
  return (lang === "en" ? RECORD_STATUS_LABELS_EN : RECORD_STATUS_LABELS)[status] ?? status;
}

export function challengeValidationStatusLabel(status: string, lang: "zh" | "en" = "zh"): string {
  return (lang === "en" ? VALIDATION_STATUS_LABELS_EN : VALIDATION_STATUS_LABELS)[status] ?? status;
}

export function challengeEvidenceSourceTypeLabel(sourceType: string, lang: "zh" | "en" = "zh"): string {
  return (lang === "en" ? EVIDENCE_SOURCE_TYPE_LABELS_EN : EVIDENCE_SOURCE_TYPE_LABELS)[sourceType] ?? sourceType;
}

export function challengeEvidenceVerificationStatusLabel(status: string, lang: "zh" | "en" = "zh"): string {
  return (lang === "en" ? EVIDENCE_VERIFICATION_STATUS_LABELS_EN : EVIDENCE_VERIFICATION_STATUS_LABELS)[status] ?? status;
}

const DIMENSION_LABELS: Record<string, string> = {
  evidence_support: "证据支持",
  factual_accuracy: "事实准确",
  novelty: "新颖性",
  falsifiability: "可证伪性",
  plan_feasibility: "计划可行性",
  risk_and_ethics: "风险与伦理",
  counterexample_coverage: "反例覆盖",
};

const DIMENSION_LABELS_EN: Record<string, string> = {
  evidence_support: "Evidence support",
  factual_accuracy: "Factual accuracy",
  novelty: "Novelty",
  falsifiability: "Falsifiability",
  plan_feasibility: "Plan feasibility",
  risk_and_ethics: "Risk & ethics",
  counterexample_coverage: "Counterexample coverage",
};

export function challengeGateLabel(decision: string, lang: "zh" | "en" = "zh") {
  if (lang === "en") {
    if (decision === "approved") return "Approved";
    if (decision === "revision_requested") return "Changes requested";
    if (decision === "rejected") return "Rejected";
    return "Pending review";
  }
  if (decision === "approved") return "已批准";
  if (decision === "revision_requested") return "需修改";
  if (decision === "rejected") return "已拒绝";
  return "待审核";
}

export function challengeRatingLabel(
  rating: ChallengeQuestionDimensionReview["rating"],
  lang: "zh" | "en" = "zh",
) {
  if (lang === "en") {
    return {
      insufficient: "Insufficient",
      weak: "Weak",
      mixed: "Mixed",
      adequate: "Adequate",
      strong: "Strong",
    }[rating];
  }
  return {
    insufficient: "不足",
    weak: "较弱",
    mixed: "混合",
    adequate: "充分",
    strong: "强",
  }[rating];
}

export function challengeDimensionLabel(dimension: string, lang: "zh" | "en" = "zh") {
  const table = lang === "en" ? DIMENSION_LABELS_EN : DIMENSION_LABELS;
  return table[dimension] || dimension;
}

export function ChallengeQuestionSectionHeading({ index, title }: { index: string; title: string }) {
  return (
    <div className={css.sectionHeading}>
      <span>{index}</span>
      <div><h3>{title}</h3></div>
    </div>
  );
}

export function ChallengeStringList({ values, lang = "zh" }: { values: string[]; lang?: "zh" | "en" }) {
  if (!values.length) {
    return <span className={css.missing}>{lang === "en" ? "Not registered" : "未登记"}</span>;
  }
  return (
    <ul className={css.compactList}>
      {values.map((value) => <li key={value}>{value}</li>)}
    </ul>
  );
}
