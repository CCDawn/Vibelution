import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getChallengeQuestionReverifyProgress,
  repairChallengeQuestionRegistration,
  reverifyChallengeQuestionCitations,
} from "../../../api/challengeQuestionRuns";
import { queryKeys } from "../../../api/queryKeys";
import type { ChallengeQuestionRunDetailPayload } from "../../../api/types";
import { VButton, VErrorSummary } from "../../../components/vui";

export type ChallengeQuestionRepairActionsProps = {
  detail: ChallengeQuestionRunDetailPayload;
  lang?: "zh" | "en";
  /**
   * The review form only hosts the registration repair beside its submit
   * button; the question header hosts both sanctioned repairs.
   */
  only?: "all" | "repair";
};

function repairErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * Sanctioned repair entries for registered question runs whose program
 * evidence gate can never pass on its own: DOI-based citation reverification
 * (validation.citationValidation=failed) and canonical result-package
 * sealing (validation.officialModelCall!==true). Both call idempotent
 * backend repairs and refetch the question result afterwards.
 */
export function ChallengeQuestionRepairActions({
  detail,
  lang,
  only = "all",
}: ChallengeQuestionRepairActionsProps) {
  const isZh = lang !== "en";
  const queryClient = useQueryClient();
  const validation = detail.record?.validation;
  const runId = detail.record?.runId || detail.selectedRunId;
  const hasTarget = Boolean(detail.teamId && detail.questionId && runId);
  const showReverify = only === "all" && hasTarget
    && validation?.citationValidation === "failed";
  const showRepair = hasTarget && validation?.officialModelCall !== true;

  const refetchAfterRepair = async () => {
    await queryClient.invalidateQueries({
      queryKey: queryKeys.challengeQuestionRunDetail(detail.teamId, detail.questionId),
    });
    await queryClient.invalidateQueries({
      queryKey: queryKeys.challengeQuestionRunStatus(detail.teamId),
    });
  };

  const reverifyMutation = useMutation({
    mutationFn: () => reverifyChallengeQuestionCitations(detail.teamId, detail.questionId, runId),
    onSuccess: refetchAfterRepair,
  });
  // SCI-049: while the recheck POST is in flight, poll the read-only
  // heartbeat surface so the operator sees done/total instead of a frozen
  // button for minutes.
  const reverifyProgress = useQuery({
    queryKey: queryKeys.challengeQuestionReverifyProgress(detail.teamId, detail.questionId, runId),
    queryFn: () =>
      getChallengeQuestionReverifyProgress(detail.teamId, detail.questionId, runId),
    enabled: reverifyMutation.isPending,
    refetchInterval: 2000,
  });
  const progressHeartbeat = reverifyProgress.data?.heartbeat ?? null;
  const repairMutation = useMutation({
    mutationFn: () => repairChallengeQuestionRegistration(detail.teamId, detail.questionId, runId),
    onSuccess: refetchAfterRepair,
  });

  if (!showReverify && !showRepair) return null;

  const failedMutation = reverifyMutation.isError ? reverifyMutation : repairMutation;

  return (
    <>
      {showReverify ? (
        <VButton
          density="compact"
          variant="secondary"
          data-testid="challenge-question-reverify-citations"
          isPending={reverifyMutation.isPending}
          isDisabled={repairMutation.isPending}
          onClick={() => reverifyMutation.mutate()}
        >
          {reverifyMutation.isPending
            ? (isZh
              ? progressHeartbeat
                ? `重核中…（${progressHeartbeat.done}/${progressHeartbeat.total}）`
                : "重核中…"
              : progressHeartbeat
                ? `Reverifying… (${progressHeartbeat.done}/${progressHeartbeat.total})`
                : "Reverifying…")
            : (isZh ? "重核引用文献" : "Reverify citations")}
        </VButton>
      ) : null}
      {showRepair ? (
        <VButton
          density="compact"
          variant="secondary"
          data-testid="challenge-question-repair-registration"
          isPending={repairMutation.isPending}
          isDisabled={reverifyMutation.isPending}
          onClick={() => repairMutation.mutate()}
        >
          {repairMutation.isPending
            ? (isZh ? "登记中…" : "Sealing…")
            : (isZh ? "补齐结果包登记" : "Repair result registration")}
        </VButton>
      ) : null}
      {failedMutation?.isError ? (
        <VErrorSummary
          data-testid="challenge-question-repair-actions-error"
          tone="warning"
          label={isZh ? "修复操作未完成" : "Repair not completed"}
          summary={isZh
            ? "运行记录未被修改，可重试；若持续失败请查看技术细节。"
            : "The run record is unchanged and the action can be retried; see technical details if it keeps failing."}
          details={<code>{repairErrorMessage(failedMutation.error)}</code>}
          openLabel={isZh ? "技术细节" : "Technical details"}
          closeLabel={isZh ? "收起" : "Hide details"}
        />
      ) : null}
    </>
  );
}
