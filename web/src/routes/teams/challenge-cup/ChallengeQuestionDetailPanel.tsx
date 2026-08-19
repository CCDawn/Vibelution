import { useState } from "react";
import { ArrowLeft } from "lucide-react";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import {
  VButton,
  VEmptyState,
  VStateSurface,
  VStatusChip,
  VSurface,
} from "../../../components/vui";
import { TeamHypothesisRoundTimeline } from "../TeamHypothesisRoundTimeline";
import { TeamMeetingRoundPanel } from "../TeamMeetingRoundPanel";
import { researchWorkflowErrorInlineText } from "../researchWorkflowErrorModel";
import { ChallengeQuestionAnalysisSection } from "./ChallengeQuestionAnalysisSection";
import { ChallengeQuestionEvidenceSection } from "./ChallengeQuestionEvidenceSection";
import { ChallengeQuestionPlanSection } from "./ChallengeQuestionPlanSection";
import { ChallengeQuestionRegisterDialog } from "./ChallengeQuestionRegisterDialog";
import { HypothesisSelectionPanel } from "./HypothesisSelectionPanel";
import css from "./ChallengeQuestionDetailPanel.styles";

export type ChallengeQuestionDetailPanelProps = {
  requestedQuestionId: string;
  detail?: ChallengeQuestionRunDetailPayload;
  isLoading: boolean;
  errorMessage?: string;
  onClose: () => void;
};

const DETAIL_ANCHORS = [
  ["question-agent", "题目与接单"],
  ["sources", "来源与证据"],
  ["hypotheses", "候选假设"],
  ["reviews", "七维评价"],
  ["selection", "选择"],
  ["hypothesis-first-selection", "假说选择"],
  ["hypothesis-first-meeting", "评审讨论"],
  ["hypothesis-first-rounds", "评审轮次"],
  ["plan", "研究计划"],
  ["feedback", "人工审核"],
  ["artifact", "最终工件"],
] as const;

const RECORD_STATUS_LABELS: Record<string, string> = {
  approved: "正式批准",
  pending_review: "待审核",
  needs_revision: "待修订",
  rejected: "已驳回",
};

function recordStatusLabel(status: string): string {
  return RECORD_STATUS_LABELS[status] ?? status;
}

export function ChallengeQuestionDetailPanel({
  requestedQuestionId,
  detail,
  isLoading,
  errorMessage = "",
  onClose,
}: ChallengeQuestionDetailPanelProps) {
  const [reviseDialogOpen, setReviseDialogOpen] = useState(false);

  if (isLoading) {
    return (
      <VSurface className={css.state} tone="workspace">
        <VStateSurface title={`正在读取 ${requestedQuestionId} 的审核工件`} tone="loading" />
      </VSurface>
    );
  }
  if (errorMessage || !detail) {
    return (
      <VSurface className={css.state} tone="workspace">
        <VEmptyState title={`${requestedQuestionId || "该题"} 的审核工件不可用`} />
        {errorMessage ? (
          <>
            <p>{researchWorkflowErrorInlineText(errorMessage)}</p>
            <details className={css.techDetails}>
              <summary>技术细节</summary>
              <code>{errorMessage}</code>
            </details>
          </>
        ) : null}
        <VButton density="compact" onPress={onClose} variant="secondary">
          返回题目列表
        </VButton>
      </VSurface>
    );
  }

  const { output, record } = detail;

  return (
    <main className={css.workspace} aria-label={`${detail.questionId} 单题验收`}>
      <header className={css.header}>
        <div>
          <span className={css.eyebrow}>单题验收</span>
          <h2>{detail.questionId}: {output.question_en}</h2>
          {output.question_zh ? <p className={css.questionZh}>{output.question_zh}</p> : null}
        </div>
        <div className={css.headerActions}>
          <VStatusChip tone={record.status === "approved" ? "accent" : "warning"}>
            {recordStatusLabel(record.status)}
          </VStatusChip>
          {record.status === "needs_revision" ? (
            <VButton density="compact" variant="primary" onPress={() => setReviseDialogOpen(true)}>
              登记修订产出
            </VButton>
          ) : null}
          <VButton density="compact" icon={<ArrowLeft size={15} aria-hidden="true" />} onPress={onClose} variant="secondary">
            返回题目列表
          </VButton>
        </div>
      </header>

      <nav className={css.anchorNav} aria-label="单题验收章节">
        {DETAIL_ANCHORS.map(([id, label], index) => (
          <a href={`#${id}`} key={id}><span>{index + 1}</span>{label}</a>
        ))}
      </nav>

      <ChallengeQuestionEvidenceSection detail={detail} />
      <ChallengeQuestionAnalysisSection output={output} />
      <HypothesisSelectionPanel teamId={detail.teamId} questionId={detail.questionId} />
      <TeamMeetingRoundPanel teamId={detail.teamId} questionId={detail.questionId} />
      <TeamHypothesisRoundTimeline teamId={detail.teamId} questionId={detail.questionId} />
      <ChallengeQuestionPlanSection detail={detail} />

      {reviseDialogOpen ? (
        <ChallengeQuestionRegisterDialog
          teamId={detail.teamId}
          initialMode="register"
          parentRunId={record.runId}
          questionIdHint={detail.questionId}
          onClose={() => setReviseDialogOpen(false)}
        />
      ) : null}
    </main>
  );
}
