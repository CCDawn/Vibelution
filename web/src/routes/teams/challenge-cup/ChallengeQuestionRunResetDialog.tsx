import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  fetchQuestionRunResetPreview,
  resetQuestionRun,
} from "../../../api/hypothesisFirst";
import { queryKeys } from "../../../api/queryKeys";
import { trackQuestionRunReset } from "../challengeCupTelemetry";
import { VConfirmDialog, VInput } from "../../../components/vui";
import css from "./ChallengeQuestionDetailPanel.styles";

export type ChallengeQuestionRunResetDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  teamId: string;
  questionId: string;
  onCompleted: (targetNodeId: string) => void;
  lang?: "zh" | "en";
};

const IMPACT_ROWS = [
  ["candidateCount", "候选假说", "Candidate hypotheses"],
  ["selectionCount", "假说选择", "Hypothesis selections"],
  ["meetingCount", "生成或评审讨论", "Generation/review meetings"],
  ["hypothesisRoundCount", "评审轮次", "Review rounds"],
  ["collectionRequestCount", "资料搜集请求", "Collection requests"],
  ["collectionRunCount", "资料搜集运行", "Collection runs"],
  ["formalRunCount", "将取消的正式运行", "Formal runs to cancel"],
  ["archivedFormalRunCount", "将归档的正式运行", "Formal runs to archive"],
] as const;

/** One-question destructive confirmation. The server remains the reset authority. */
export function ChallengeQuestionRunResetDialog({
  open,
  onOpenChange,
  teamId,
  questionId,
  onCompleted,
  lang = "zh",
}: ChallengeQuestionRunResetDialogProps) {
  const isZh = lang !== "en";
  const queryClient = useQueryClient();
  const [confirmationQuestionId, setConfirmationQuestionId] = useState("");
  const previewQuery = useQuery({
    queryKey: ["teams", teamId, "hypothesis-first", "run-reset-preview", questionId],
    queryFn: () => fetchQuestionRunResetPreview(teamId, questionId),
    enabled: open && Boolean(teamId && questionId),
    retry: false,
  });
  const resetMutation = useMutation({
    mutationFn: () => resetQuestionRun(teamId, questionId, confirmationQuestionId),
    onMutate: () => ({
      telemetry: trackQuestionRunReset({
        teamId,
        questionId,
        ...(preview ? { impact: { ...preview.impact } } : {}),
      }),
    }),
    onSuccess: async (result, _vars, context) => {
      context?.telemetry?.succeeded({ targetNodeId: result.nextAction.targetNodeId });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["teams", teamId, "hypothesis-first"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.teamMeetingRounds(teamId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.teamHypothesisRounds(teamId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.hypothesisFirstSelectionContext(teamId, questionId) }),
        // A reset changes the question's recorded result state, which the
        // catalog overview and the single-question detail both read; without
        // this they keep showing the pre-reset run.
        queryClient.invalidateQueries({ queryKey: queryKeys.challengeQuestionRunStatus(teamId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.challengeQuestionRunDetail(teamId, questionId) }),
      ]);
      setConfirmationQuestionId("");
      onOpenChange(false);
      onCompleted(result.nextAction.targetNodeId);
    },
    onError: (error, _vars, context) => {
      context?.telemetry?.failed(error);
    },
  });
  const normalizedQuestionId = questionId.trim().toUpperCase();
  const preview = previewQuery.data;
  const confirmed = confirmationQuestionId.trim().toUpperCase() === normalizedQuestionId;
  const confirmDisabled = !preview || !preview.canReset || !confirmed || resetMutation.isPending;
  const confirmationHint = preview?.canReset && !confirmed
    ? (isZh
      ? `请输入 ${normalizedQuestionId} 以解锁重置操作。`
      : `Type ${normalizedQuestionId} to unlock the reset.`)
    : "";
  const errorText = resetMutation.error instanceof Error
    ? resetMutation.error.message
    : (previewQuery.error instanceof Error ? previewQuery.error.message : "");

  return (
    <VConfirmDialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen) setConfirmationQuestionId("");
        onOpenChange(nextOpen);
      }}
      title={isZh ? `重置 ${normalizedQuestionId} 的运行？` : `Reset the run for ${normalizedQuestionId}?`}
      description={isZh
        ? "这只清理本题的假说闭环工作记录，不会删除题目、团队配置或其他题目。"
        : "This clears only this question's hypothesis-loop records; the question, team configuration, and other questions are untouched."}
      tone="danger"
      confirmLabel={isZh ? "重置本题运行" : "Reset this question run"}
      cancelLabel={isZh ? "取消" : "Cancel"}
      confirmPending={resetMutation.isPending}
      confirmDisabled={confirmDisabled}
      onConfirm={() => resetMutation.mutate()}
    >
      <div className={css.resetDialog}>
        {previewQuery.isPending ? <p role="status">{isZh ? "正在核对将清理的内容…" : "Checking what will be cleared…"}</p> : null}
        {preview ? (
          <>
            <ul className={css.resetImpactList} aria-label={isZh ? "将清理的内容" : "Content to be cleared"}>
              {IMPACT_ROWS.map(([key, labelZh, labelEn]) => (
                <li key={key}><span>{isZh ? labelZh : labelEn}</span><strong>{preview.impact[key]}</strong></li>
              ))}
            </ul>
            {preview.blockingReason ? <p className={css.resetWarning} role="status">{preview.blockingReason}</p> : null}
          </>
        ) : null}
        {errorText ? <p className={css.resetWarning} role="alert">{errorText}</p> : null}
        {confirmationHint ? <p role="status">{confirmationHint}</p> : null}
        <label className={css.field}>
          <span>{isZh ? `输入 ${normalizedQuestionId} 以确认` : `Type ${normalizedQuestionId} to confirm`}</span>
          <VInput
            value={confirmationQuestionId}
            onChange={(event) => setConfirmationQuestionId(event.target.value)}
            placeholder={normalizedQuestionId}
            aria-label={isZh ? `输入 ${normalizedQuestionId} 确认重置` : `Type ${normalizedQuestionId} to confirm the reset`}
            autoComplete="off"
          />
        </label>
      </div>
    </VConfirmDialog>
  );
}
