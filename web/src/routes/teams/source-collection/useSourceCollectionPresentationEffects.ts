/**
 * SC presentation invalidation + selection hygiene effects.
 * Phase R2-l extract from useSourceCollectionPresentationCore (behavior-conserving).
 */
import { useEffect, type Dispatch, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../../api/queryKeys";
import type { TeamWorkflowCandidate } from "../../../api/types";
import {
  SOURCE_COLLECTION_RUN_PREVIEW_LIMIT,
  SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS,
} from "./presentationModel";
import {
  sourceCollectionRunRecordsQueryKey,
  sourceCollectionSummaryQueryKey,
} from "../teamWorkflowQueryKeys";

export type UseSourceCollectionPresentationEffectsOptions = {
  queryClient: QueryClient;
  pageVisible: boolean;
  researchWorkflowTeamSelected: boolean;
  selectedTeamId: string;
  selectedSourceCollectionRunEffectiveId: string;
  requestedSourceCollectionStage: string | null | undefined;
  setSourceCollectionStageSyncUntilMs: Dispatch<SetStateAction<number>>;
  selectedSourceCollectionSearchAccepted: boolean;
  selectedSourceCollectionCandidateId: string;
  sourceManifestCandidates: TeamWorkflowCandidate[];
  setSelectedSourceCollectionCandidateId: Dispatch<SetStateAction<string>>;
};

export function useSourceCollectionPresentationEffects(
  options: UseSourceCollectionPresentationEffectsOptions,
) {
  const {
    queryClient,
    pageVisible,
    researchWorkflowTeamSelected,
    selectedTeamId,
    selectedSourceCollectionRunEffectiveId,
    requestedSourceCollectionStage,
    setSourceCollectionStageSyncUntilMs,
    selectedSourceCollectionSearchAccepted,
    selectedSourceCollectionCandidateId,
    sourceManifestCandidates,
    setSelectedSourceCollectionCandidateId,
  } = options;

  useEffect(() => {
    if (!researchWorkflowTeamSelected || !pageVisible || !selectedTeamId || !selectedSourceCollectionRunEffectiveId) {
      return;
    }
    if (requestedSourceCollectionStage) {
      setSourceCollectionStageSyncUntilMs(Date.now() + SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS);
    }
    void queryClient.invalidateQueries({
      queryKey: sourceCollectionSummaryQueryKey(selectedTeamId, selectedSourceCollectionRunEffectiveId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.teamWorkflowSourceCollectionRuns(selectedTeamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.dataProcessingRunStatus(selectedSourceCollectionRunEffectiveId),
    });
    void queryClient.invalidateQueries({
      queryKey: sourceCollectionRunRecordsQueryKey(selectedSourceCollectionRunEffectiveId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.dataProcessingCollectionAssignments(selectedSourceCollectionRunEffectiveId),
    });
  }, [
    pageVisible,
    queryClient,
    requestedSourceCollectionStage,
    researchWorkflowTeamSelected,
    selectedSourceCollectionRunEffectiveId,
    selectedTeamId,
    setSourceCollectionStageSyncUntilMs,
  ]);

  useEffect(() => {
    if (!selectedTeamId || !selectedSourceCollectionRunEffectiveId || !selectedSourceCollectionSearchAccepted) {
      return;
    }
    void queryClient.invalidateQueries({
      queryKey: queryKeys.teamWorkflowSourceCollectionRuns(selectedTeamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.dataProcessingRunStatus(selectedSourceCollectionRunEffectiveId),
    });
    void queryClient.invalidateQueries({
      queryKey: sourceCollectionRunRecordsQueryKey(selectedSourceCollectionRunEffectiveId),
    });
    void queryClient.invalidateQueries({
      queryKey: queryKeys.dataProcessingCollectionAssignments(selectedSourceCollectionRunEffectiveId),
    });
    void queryClient.invalidateQueries({
      queryKey: sourceCollectionSummaryQueryKey(selectedTeamId, selectedSourceCollectionRunEffectiveId),
    });
  }, [
    queryClient,
    selectedSourceCollectionRunEffectiveId,
    selectedSourceCollectionSearchAccepted,
    selectedTeamId,
  ]);

  useEffect(() => {
    if (!selectedSourceCollectionCandidateId) {
      return;
    }
    if (!sourceManifestCandidates.some((candidate) => candidate.candidateId === selectedSourceCollectionCandidateId)) {
      setSelectedSourceCollectionCandidateId("");
    }
  }, [
    selectedSourceCollectionCandidateId,
    setSelectedSourceCollectionCandidateId,
    sourceManifestCandidates,
  ]);
}
