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
  { key: "H1_problem_understanding", label: "H1 问题理解" },
  { key: "H2_hypothesis_selection", label: "H2 假设选择" },
  { key: "H3_research_plan", label: "H3 研究计划" },
  { key: "H4_external_output", label: "H4 外部产出" },
] as const;

type GateKey = (typeof GATES)[number]["key"];
type GateDecision = "approved" | "revision_requested" | "rejected";

const DECISION_OPTIONS: Array<{ id: GateDecision; label: string }> = [
  { id: "approved", label: "通过" },
  { id: "revision_requested", label: "要求修改" },
  { id: "rejected", label: "驳回" },
];

const REVIEWER_STORAGE_KEY = "vibelution.challenge-question-reviewer";

function decisionLabel(decision: string): string {
  switch (decision) {
    case "approved":
    case "passed":
      return "已通过";
    case "revision_requested":
      return "要求修改";
    case "rejected":
      return "已驳回";
    default:
      return "待审核";
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

export function ChallengeQuestionReviewForm(props: {
  detail: ChallengeQuestionRunDetailPayload;
}) {
  const { detail } = props;
  const queryClient = useQueryClient();
  const [decisions, setDecisions] = useState<Record<GateKey, GateDecision>>({
    H1_problem_understanding: "approved",
    H2_hypothesis_selection: "approved",
    H3_research_plan: "approved",
    H4_external_output: "approved",
  });
  const [reviewer, setReviewer] = useState(() => {
    try {
      return globalThis.localStorage?.getItem(REVIEWER_STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });
  const [rationale, setRationale] = useState("");

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
      await queryClient.invalidateQueries({
        queryKey: queryKeys.challengeQuestionRunDetail(detail.teamId, detail.questionId),
      });
      await queryClient.invalidateQueries({
        queryKey: queryKeys.researchWorkflowLaunchOptions(CHALLENGE_CUP_WORKFLOW_ID, detail.teamId),
      });
    },
  });

  if (detail.record.status === "approved") {
    return (
      <VSurface tone="card" className={css.reviewSummary} data-vui="question-review-summary">
        <div className={css.cardTopline}>
          <strong>审核结论</strong>
          <VStatusChip tone="accent">已正式批准</VStatusChip>
        </div>
        <div className={css.metadata}>
          {reviewField(detail, "reviewer") ? <span>审核人 {reviewField(detail, "reviewer")}</span> : null}
          {reviewField(detail, "decided_at") ? <span>{reviewField(detail, "decided_at")}</span> : null}
        </div>
        {reviewField(detail, "rationale") ? <p>{reviewField(detail, "rationale")}</p> : null}
      </VSurface>
    );
  }

  const canSubmit = Boolean(reviewer.trim()) && Boolean(rationale.trim()) && !mutation.isPending;

  return (
    <VSurface tone="card" className={css.reviewForm} data-vui="question-review-form">
      <div className={css.gateList}>
        {GATES.map((gate) => {
          const current = currentGateDecision(detail, gate.key);
          return (
            <div className={css.gateRow} key={gate.key}>
              <span>{gate.label}</span>
              <VStatusChip tone={decisionTone(current)}>{decisionLabel(current)}</VStatusChip>
              <VSelect
                aria-label={`${gate.label} 审核结论`}
                density="compact"
                selectedKey={decisions[gate.key]}
                options={DECISION_OPTIONS}
                onSelectionChange={(key) => {
                  if (key == null) return;
                  setDecisions((prev) => ({ ...prev, [gate.key]: String(key) as GateDecision }));
                }}
                isDisabled={mutation.isPending}
              />
            </div>
          );
        })}
      </div>
      <label className={css.field}>
        <span>审核人</span>
        <VInput
          aria-label="审核人"
          value={reviewer}
          onChange={(event) => setReviewer(event.currentTarget.value)}
          placeholder="你的名字"
          isDisabled={mutation.isPending}
        />
      </label>
      <label className={css.field}>
        <span>审核意见</span>
        <VTextarea
          aria-label="审核意见"
          value={rationale}
          onChange={(event) => setRationale(event.currentTarget.value)}
          placeholder="通过 / 要求修改的理由"
          minRows={2}
          isDisabled={mutation.isPending}
        />
      </label>
      {mutation.isError ? (
        <div role="alert" className={css.missingLine}>
          {mutation.error instanceof Error ? mutation.error.message : "提交失败，请重试"}
        </div>
      ) : null}
      <div>
        <VButton
          type="button"
          variant="primary"
          isPending={mutation.isPending}
          isDisabled={!canSubmit}
          disabledReason={!reviewer.trim() || !rationale.trim() ? "先填审核人和审核意见" : undefined}
          onClick={() => mutation.mutate()}
        >
          提交审核结论
        </VButton>
      </div>
    </VSurface>
  );
}
