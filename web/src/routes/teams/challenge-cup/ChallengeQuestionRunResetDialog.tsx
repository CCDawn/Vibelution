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
};

const IMPACT_ROWS = [
  ["candidateCount", "候选假说"],
  ["selectionCount", "假说选择"],
  ["meetingCount", "生成或评审讨论"],
  ["hypothesisRoundCount", "评审轮次"],
  ["collectionRequestCount", "资料搜集请求"],
  ["collectionRunCount", "资料搜集运行"],
] as const;

/** One-question destructive confirmation. The server remains the reset authority. */
export function ChallengeQuestionRunResetDialog({
  open,
  onOpenChange,
  teamId,
  questionId,
  onCompleted,
}: ChallengeQuestionRunResetDialogProps) {
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
    ? `请输入 ${normalizedQuestionId} 以解锁重置操作。`
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
      title={`重置 ${normalizedQuestionId} 的运行？`}
      description="这只清理本题的假说闭环工作记录，不会删除题目、团队配置或其他题目。"
      tone="danger"
      confirmLabel="重置本题运行"
      cancelLabel="取消"
      confirmPending={resetMutation.isPending}
      confirmDisabled={confirmDisabled}
      onConfirm={() => resetMutation.mutate()}
    >
      <div className={css.resetDialog}>
        {previewQuery.isPending ? <p role="status">正在核对将清理的内容…</p> : null}
        {preview ? (
          <>
            <ul className={css.resetImpactList} aria-label="将清理的内容">
              {IMPACT_ROWS.map(([key, label]) => (
                <li key={key}><span>{label}</span><strong>{preview.impact[key]}</strong></li>
              ))}
            </ul>
            {preview.blockingReason ? <p className={css.resetWarning} role="status">{preview.blockingReason}</p> : null}
          </>
        ) : null}
        {errorText ? <p className={css.resetWarning} role="alert">{errorText}</p> : null}
        {confirmationHint ? <p role="status">{confirmationHint}</p> : null}
        <label className={css.field}>
          <span>输入 {normalizedQuestionId} 以确认</span>
          <VInput
            value={confirmationQuestionId}
            onChange={(event) => setConfirmationQuestionId(event.target.value)}
            placeholder={normalizedQuestionId}
            aria-label={`输入 ${normalizedQuestionId} 确认重置`}
            autoComplete="off"
          />
        </label>
      </div>
    </VConfirmDialog>
  );
}
