import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { queryKeys } from "../../../api/queryKeys";
import { fetchChallengeCupTokenUsage } from "../../../api/teamExperiment";

import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import {
  VButton,
  VEmptyState,
  VErrorSummary,
  VStateSurface,
  VStatusChip,
  VStringSelect,
  VSurface,
} from "../../../components/vui";
import { TeamHypothesisRoundTimeline } from "../TeamHypothesisRoundTimeline";
import { TeamMeetingRoundPanel } from "../TeamMeetingRoundPanel";
import { useShellI18n } from "../../../i18n/useShellI18n";
import { ChallengeQuestionAnalysisSection } from "./ChallengeQuestionAnalysisSection";
import { ChallengeQuestionEvidenceSection } from "./ChallengeQuestionEvidenceSection";
import { ChallengeQuestionPlanSection } from "./ChallengeQuestionPlanSection";
import { ChallengeQuestionRegisterDialog } from "./ChallengeQuestionRegisterDialog";
import { HypothesisSelectionPanel } from "./HypothesisSelectionPanel";
import { ChallengeQuestionTokenUsage } from "./ChallengeTokenUsageStrip";
import { isTokenUsageOverview, questionTokenUsage } from "./challengeTokenUsageModel";
import { challengeRecordStatusLabel } from "./ChallengeQuestionDetailPrimitives";
import css from "./ChallengeQuestionDetailPanel.styles";

export type ChallengeQuestionDetailPanelProps = {
  requestedQuestionId: string;
  teamId?: string;
  detail?: ChallengeQuestionRunDetailPayload;
  isLoading: boolean;
  errorMessage?: string;
  onClose: () => void;
  /** Selected historical run id (empty = latest); revisions become reviewable. */
  selectedRunId?: string;
  onSelectRunId?: (runId: string) => void;
};

const DETAIL_ANCHORS_ZH = [
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

const DETAIL_ANCHORS_EN = [
  ["question-agent", "Question & agent"],
  ["sources", "Sources & evidence"],
  ["hypotheses", "Candidate hypotheses"],
  ["reviews", "Seven-dim review"],
  ["selection", "Selection"],
  ["hypothesis-first-selection", "Hypothesis selection"],
  ["hypothesis-first-meeting", "Review discussion"],
  ["hypothesis-first-rounds", "Review rounds"],
  ["plan", "Research plan"],
  ["feedback", "Human review"],
  ["artifact", "Final artifact"],
] as const;

export function ChallengeQuestionDetailPanel({
  requestedQuestionId,
  teamId = "",
  detail,
  isLoading,
  errorMessage = "",
  onClose,
  selectedRunId = "",
  onSelectRunId,
}: ChallengeQuestionDetailPanelProps) {
  const [reviseDialogOpen, setReviseDialogOpen] = useState(false);
  const { lang } = useShellI18n();
  const isZh = lang === "zh";
  const detailAnchors = isZh ? DETAIL_ANCHORS_ZH : DETAIL_ANCHORS_EN;
  const tokenUsageQuery = useQuery({
    queryKey: queryKeys.challengeCupTokenUsage(teamId),
    queryFn: () => fetchChallengeCupTokenUsage(teamId),
    enabled: Boolean(teamId.trim()),
    staleTime: 15_000,
    retry: false,
  });
  const tokenUsageOverview = isTokenUsageOverview(tokenUsageQuery.data);
  const questionUsage = tokenUsageOverview
    ? questionTokenUsage(tokenUsageQuery.data, requestedQuestionId)
    : null;
  const tokenUsageState = tokenUsageQuery.isPending
    ? "pending"
    : tokenUsageQuery.isError || !tokenUsageOverview
      ? "error"
      : "success";

  if (isLoading) {
    return (
      <VSurface className={css.state} tone="workspace">
        <VStateSurface
          title={isZh ? `正在读取 ${requestedQuestionId} 的审核工件` : `Loading review artifacts for ${requestedQuestionId}`}
          tone="loading"
        />
      </VSurface>
    );
  }
  if (errorMessage || !detail) {
    const operableTeamId = detail?.teamId || teamId;
    const canContinueReview = Boolean(operableTeamId && requestedQuestionId);
    return (
      <VSurface className={css.state} tone="workspace">
        {canContinueReview ? (
          <VErrorSummary
            data-testid="question-detail-fail-soft-warning"
            tone="warning"
            label={
              requestedQuestionId
                ? `${requestedQuestionId} · ${isZh ? "验收档案" : "Acceptance artifacts"}`
                : (isZh ? "验收档案" : "Acceptance artifacts")
            }
            summary={
              isZh
                ? "验收档案暂不可用，假说评审仍可继续"
                : "Acceptance artifacts are temporarily unavailable; hypothesis review can continue."
            }
            details={errorMessage ? <code>{errorMessage}</code> : undefined}
            openLabel={isZh ? "技术细节" : "Technical details"}
            closeLabel={isZh ? "收起" : "Hide details"}
          />
        ) : (
          <>
            <VEmptyState
              title={isZh
                ? `${requestedQuestionId || "该题"} 的验收档案暂不可用`
                : `Acceptance artifacts unavailable for ${requestedQuestionId || "this question"}`}
            />
            {errorMessage ? (
              <details className={css.techDetails}>
                <summary>{isZh ? "技术细节" : "Technical details"}</summary>
                <code>{errorMessage}</code>
              </details>
            ) : null}
          </>
        )}
        {canContinueReview ? (
          <div className={css.section} data-testid="question-detail-fail-soft-ops">
            <HypothesisSelectionPanel teamId={operableTeamId} questionId={requestedQuestionId} lang={lang} />
            <TeamMeetingRoundPanel teamId={operableTeamId} questionId={requestedQuestionId} />
          </div>
        ) : null}
        <VButton density="compact" onPress={onClose} variant="secondary">
          {isZh ? "返回题目列表" : "Back to question list"}
        </VButton>
      </VSurface>
    );
  }

  const { output, record } = detail;

  return (
    <main className={css.workspace} aria-label={isZh ? `${detail.questionId} 单题验收` : `${detail.questionId} acceptance`}>
      <header className={css.header}>
        <div>
          <span className={css.eyebrow}>{isZh ? "单题验收" : "Question acceptance"}</span>
          <h2>{detail.questionId}: {output.question_en}</h2>
          {output.question_zh ? <p className={css.questionZh}>{output.question_zh}</p> : null}
        </div>
        <div className={css.headerActions}>
          <VStatusChip tone={record.status === "approved" ? "accent" : "warning"}>
            {challengeRecordStatusLabel(record.status, isZh ? "zh" : "en")}
          </VStatusChip>
          {onSelectRunId && detail.runs.length > 1 ? (
            <label className={css.runSwitcher} data-testid="question-run-switcher">
              <span>{isZh ? "查看 run" : "Run"}</span>
              <VStringSelect
                value={selectedRunId || detail.selectedRunId}
                onValueChange={(value) => onSelectRunId(value)}
                ariaLabel={isZh ? "选择要查看的 run" : "Select run to view"}
                options={detail.runs.map((run) => ({
                  value: run.runId,
                  label: `${run.runId}${run.runId === detail.selectedRunId ? (isZh ? "（最新）" : " (latest)") : ""}`,
                }))}
              />
            </label>
          ) : null}
          {record.status === "needs_revision" ? (
            <VButton density="compact" variant="primary" onPress={() => setReviseDialogOpen(true)}>
              {isZh ? "登记修订产出" : "Register revision output"}
            </VButton>
          ) : null}
          <VButton density="compact" icon={<ArrowLeft size={15} aria-hidden="true" />} onPress={onClose} variant="secondary">
            {isZh ? "返回题目列表" : "Back to question list"}
          </VButton>
        </div>
      </header>

      <nav className={css.anchorNav} aria-label={isZh ? "单题验收章节" : "Acceptance sections"}>
        {detailAnchors.map(([id, label], index) => (
          <a href={`#${id}`} key={id}><span>{index + 1}</span>{label}</a>
        ))}
      </nav>

      {teamId ? <ChallengeQuestionTokenUsage lang={lang} usage={questionUsage} state={tokenUsageState} /> : null}

      <ChallengeQuestionEvidenceSection detail={detail} lang={lang} />
      <ChallengeQuestionAnalysisSection output={output} lang={lang} />
      <HypothesisSelectionPanel teamId={detail.teamId} questionId={detail.questionId} lang={lang} />
      <TeamMeetingRoundPanel teamId={detail.teamId} questionId={detail.questionId} />
      <TeamHypothesisRoundTimeline teamId={detail.teamId} questionId={detail.questionId} />
      <ChallengeQuestionPlanSection detail={detail} lang={lang} />

      {reviseDialogOpen ? (
        <ChallengeQuestionRegisterDialog
          teamId={detail.teamId}
          initialMode="register"
          parentRunId={record.runId}
          questionIdHint={detail.questionId}
          onClose={() => setReviseDialogOpen(false)}
          lang={lang}
        />
      ) : null}
    </main>
  );
}
