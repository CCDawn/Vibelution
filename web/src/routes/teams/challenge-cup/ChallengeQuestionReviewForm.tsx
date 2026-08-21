import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../../api/queryKeys";
import { reviewChallengeQuestionRun } from "../../../api/teamExperiment";
import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { CHALLENGE_CUP_WORKFLOW_ID } from "../../../api/types/researchWorkflow";
import {
  VButton,
  VInput,
  VSelect,
  VStatusChip,
  VSurface,
  VTextarea,
} from "../../../components/vui";
import css from "./ChallengeQuestionDetailPanel.styles";

const GATES = [
  { key: "H1_problem_understanding", label: "H1 问题理解", labelEn: "H1 Problem understanding" },
  { key: "H2_hypothesis_selection", label: "H2 假设选择", labelEn: "H2 Hypothesis selection" },
  { key: "H3_research_plan", label: "H3 研究计划", labelEn: "H3 Research plan" },
  { key: "H4_external_output", label: "H4 外部产出", labelEn: "H4 External output" },
] as const;

type GateKey = (typeof GATES)[number]["key"];
type GateDecision = "approved" | "revision_requested" | "rejected";
type GateSelection = GateDecision | "pending";

const PENDING_DECISION_OPTION_ZH = { id: "pending" as const, label: "待定" };
const DECISION_OPTIONS_ZH: Array<{ id: GateSelection; label: string }> = [
  PENDING_DECISION_OPTION_ZH,
  { id: "approved", label: "通过" },
  { id: "revision_requested", label: "需修改" },
  { id: "rejected", label: "驳回" },
];

const PENDING_DECISION_OPTION_EN = { id: "pending" as const, label: "Pending" };
const DECISION_OPTIONS_EN: Array<{ id: GateSelection; label: string }> = [
  PENDING_DECISION_OPTION_EN,
  { id: "approved", label: "Approve" },
  { id: "revision_requested", label: "Request changes" },
  { id: "rejected", label: "Reject" },
];

const REVIEWER_STORAGE_KEY = "vibelution.challenge-question-reviewer";

function decisionLabel(decision: string, isZh: boolean): string {
  switch (decision) {
    case "approved":
    case "passed":
      return isZh ? "已通过" : "Approved";
    case "revision_requested":
      return isZh ? "需修改" : "Changes requested";
    case "rejected":
      return isZh ? "已驳回" : "Rejected";
    default:
      return isZh ? "待审核" : "Pending review";
  }
}

function decisionTone(decision: string): "accent" | "warning" | "danger" {
  switch (decision) {
    case "approved":
    case "passed":
      return "accent";
    case "rejected":
      return "danger";
    default:
      return "warning";
  }
}

function currentGateDecision(detail: ChallengeQuestionRunDetailPayload, gate: GateKey): string {
  const { output } = detail;
  switch (gate) {
    case "H1_problem_understanding":
      return output.problem_understanding.human_gate.decision;
    case "H2_hypothesis_selection":
      return output.selection.human_gate.decision;
    case "H3_research_plan":
      return output.research_plan.human_gate.decision;
    case "H4_external_output":
      return output.audit.human_review_status;
  }
}

function reviewField(detail: ChallengeQuestionRunDetailPayload, field: string): string {
  // 后端在审核后写入 output.review，但 TS 类型尚未声明该字段
  const review = (detail.output as { review?: Record<string, unknown> }).review;
  if (!review) return "";
  const value = review[field];
  return typeof value === "string" ? value : "";
}

function formatDecidedAt(value: string, isZh: boolean): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  try {
    return new Intl.DateTimeFormat(isZh ? "zh-CN" : "en-US", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  } catch {
    return value;
  }
}

export function ChallengeQuestionReviewForm(props: {
  detail: ChallengeQuestionRunDetailPayload;
  lang?: "zh" | "en";
}) {
  const { detail } = props;
  const isZh = props.lang !== "en";
  const queryClient = useQueryClient();
  const [decisions, setDecisions] = useState<Record<GateKey, GateSelection>>({
    H1_problem_understanding: "pending",
    H2_hypothesis_selection: "pending",
    H3_research_plan: "pending",
    H4_external_output: "pending",
  });
  const [reviewer, setReviewer] = useState(() => {
    try {
      return globalThis.localStorage?.getItem(REVIEWER_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [rationale, setRationale] = useState("");
  const reviewKey = `${detail.questionId}:${detail.selectedRunId}`;
  const [submittedReviewKey, setSubmittedReviewKey] = useState<string | null>(null);
  const isSubmitted = submittedReviewKey === reviewKey;

  const mutation = useMutation({
    mutationFn: () =>
      reviewChallengeQuestionRun(detail.teamId, detail.questionId, detail.selectedRunId, {
        reviewer: reviewer.trim(),
        rationale: rationale.trim(),
        decisions,
      }),
    onSuccess: async () => {
      try {
        globalThis.localStorage?.setItem(REVIEWER_STORAGE_KEY, reviewer.trim());
      } catch {
        // 记住审核人只是便利，存储不可用时静默降级
      }
      if (Object.values(decisions).some((decision) => decision !== "approved")) {
        setSubmittedReviewKey(reviewKey);
      }
      await queryClient.invalidateQueries({
        queryKey: queryKeys.challengeQuestionRunDetail(detail.teamId, detail.questionId),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.researchWorkflowLaunchOptions(CHALLENGE_CUP_WORKFLOW_ID, detail.teamId),
      });
    },
  });

  if (detail.record.status === "approved") {
    const decidedAt = reviewField(detail, "decided_at");
    return (
      <VSurface tone="card" className={css.reviewSummary} data-vui="question-review-summary">
        <div className={css.cardTopline}>
          <strong>{isZh ? "审核结论" : "Review outcome"}</strong>
          <VStatusChip tone="accent">{isZh ? "已正式批准" : "Formally approved"}</VStatusChip>
        </div>
        <div className={css.metadata}>
          {reviewField(detail, "reviewer") ? <span>{isZh ? `审核人 ${reviewField(detail, "reviewer")}` : `Reviewer ${reviewField(detail, "reviewer")}`}</span> : null}
          {decidedAt ? <span>{formatDecidedAt(decidedAt, isZh)}</span> : null}
        </div>
        {reviewField(detail, "rationale") ? <p>{reviewField(detail, "rationale")}</p> : null}
      </VSurface>
    );
  }

  // Human review requires official-model evidence at team level (register
  // alone never satisfies it; the run must be published first).
  const officialCallReady = detail.record?.validation?.officialModelCall === true;
  const allGatesDecided = GATES.every(({ key }) => decisions[key] !== "pending");
  const canSubmit = allGatesDecided
    && Boolean(reviewer.trim())
    && Boolean(rationale.trim())
    && !mutation.isPending
    && !isSubmitted
    && officialCallReady;

  return (
    <VSurface tone="card" className={css.reviewForm} data-vui="question-review-form">
      {isSubmitted ? (
        <div role="status" className={css.reviewSuccess} data-testid="review-success-banner">
          {isZh
            ? "审核结论已提交，表单已锁定，避免重复提交。"
            : "Review submitted. The form is locked to prevent duplicate submissions."}
        </div>
      ) : null}
      <div className={css.gateList}>
        {GATES.map((gate) => {
          const current = currentGateDecision(detail, gate.key);
          const gateLabel = isZh ? gate.label : gate.labelEn;
          return (
            <div className={css.gateRow} key={gate.key}>
              <span>{gateLabel}</span>
              <VStatusChip tone={decisionTone(current)}>{decisionLabel(current, isZh)}</VStatusChip>
              <VSelect
                aria-label={isZh ? `${gateLabel} 审核结论` : `${gateLabel} review decision`}
                density="compact"
                selectedKey={decisions[gate.key]}
                placeholder={isZh ? "待定" : "Pending"}
                options={isZh ? DECISION_OPTIONS_ZH : DECISION_OPTIONS_EN}
                onSelectionChange={(key) => {
                  if (key == null) return;
                  setDecisions((prev) => ({ ...prev, [gate.key]: String(key) as GateSelection }));
                }}
                isDisabled={mutation.isPending || isSubmitted}
              />
            </div>
          );
        })}
      </div>
      <label className={css.field}>
        <span>{isZh ? "审核人" : "Reviewer"}</span>
        <VInput
          aria-label={isZh ? "审核人" : "Reviewer"}
          value={reviewer}
          onChange={(event) => setReviewer(event.currentTarget.value)}
          placeholder={isZh ? "你的名字" : "Your name"}
          isDisabled={mutation.isPending || isSubmitted}
        />
      </label>
      <label className={css.field}>
        <span>{isZh ? "审核意见" : "Review rationale"}</span>
        <VTextarea
          aria-label={isZh ? "审核意见" : "Review rationale"}
          value={rationale}
          onChange={(event) => setRationale(event.currentTarget.value)}
          placeholder={isZh ? "通过 / 需修改的理由" : "Rationale for approve / request changes"}
          minRows={2}
          isDisabled={mutation.isPending || isSubmitted}
        />
      </label>
      {mutation.isError ? (
        <div role="alert" className={css.missingLine}>
          {mutation.error instanceof Error ? mutation.error.message : (isZh ? "提交失败，请重试" : "Submit failed; please retry")}
        </div>
      ) : null}
      <div>
        <VButton
          type="button"
          variant="primary"
          isPending={mutation.isPending}
          isDisabled={!canSubmit}
          disabledReason={isSubmitted
            ? (isZh ? "审核结论已提交" : "Review already submitted")
            : !officialCallReady
            ? (isZh
              ? "该 run 尚未满足官方模型调用门（证据需先发布到团队级），提交会被拒绝"
              : "This run has not passed the official-model-call gate (publish the evidence first); submission would be rejected")
            : !allGatesDecided
              ? (isZh ? "请逐项选择四个审核门禁的结论" : "Choose a decision for all four review gates")
            : !reviewer.trim() || !rationale.trim() ? (isZh ? "先填审核人和审核意见" : "Fill in reviewer and rationale first") : undefined}
          onClick={() => mutation.mutate()}
        >
          {isZh ? "提交审核结论" : "Submit review"}
        </VButton>
      </div>
    </VSurface>
  );
}
