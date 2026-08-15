/**
 * Selected source-collection run detail queries for Teams.
 * Run list selection stays in Route; this hook owns summary/status/records/assignments.
 */
import { useQuery } from "@tanstack/react-query";

import {
  fetchDataProcessingRunStatus,
  listDataProcessingCollectionAssignments,
  listDataProcessingRunRecords,
} from "../../api/dataProcessing";
import { queryKeys } from "../../api/queryKeys";
import { fetchSourceCollectionSummary } from "../../api/sourceCollection";
import type {
  DataProcessingStatus,
} from "../../api/types";
import { resolvePollingInterval } from "../../app/pollingPolicy";
import {
  sourceCollectionRunRecordsQueryKey,
  sourceCollectionSummaryQueryKey,
} from "./teamWorkflowQueryKeys";
import { sourceCollectionStageWritebackRefetchInterval } from "./useResearchWorkflowResources";
import { sourceCollectionRunRefetchInterval } from "./workflowPresentation";
import type {
  DataProcessingRecordListPayload,
  SourceCollectionSummaryPayload,
} from "./sourceCollectionRunQueryModel";

export type UseSourceCollectionRunQueriesOptions = {
  effectiveTeamId: string;
  pageVisible: boolean;
  selectedSourceCollectionRunEffectiveId: string;
  sourceCollectionWorkspaceSelected: boolean;
  sourceCollectionFindingDetailsVisible: boolean;
  sourceCollectionStageWritebackSyncActive: boolean;
  selectedRunStatusFallback: string;
};

export function useSourceCollectionRunQueries(options: UseSourceCollectionRunQueriesOptions) {
  const sourceCollectionSummaryQuery = useQuery({
    queryKey: sourceCollectionSummaryQueryKey(
      options.effectiveTeamId || "none",
      options.selectedSourceCollectionRunEffectiveId || "latest",
    ),
    queryFn: ({ signal }) =>
      fetchSourceCollectionSummary<SourceCollectionSummaryPayload>(
        options.effectiveTeamId,
        {
          signal,
          runId: options.selectedSourceCollectionRunEffectiveId || undefined,
        },
      ),
    enabled: Boolean(
      options.effectiveTeamId
      && options.sourceCollectionWorkspaceSelected
      && options.selectedSourceCollectionRunEffectiveId,
    ),
    staleTime: 10_000,
    refetchInterval: (query) => {
      const payload = query.state.data as SourceCollectionSummaryPayload | undefined;
      const active = payload?.status === "active";
      return active
        ? resolvePollingInterval(options.pageVisible, 1500)
        : sourceCollectionStageWritebackRefetchInterval(
          options.pageVisible,
          payload,
          options.sourceCollectionStageWritebackSyncActive,
        );
    },
  });

  const sourceCollectionRecordsQueryEnabled = options.sourceCollectionFindingDetailsVisible;
  const sourceCollectionAssignmentsQueryEnabled = options.sourceCollectionFindingDetailsVisible;
  const sourceCollectionRunStatusQueryEnabled =
    sourceCollectionRecordsQueryEnabled || sourceCollectionAssignmentsQueryEnabled;

  const sourceCollectionRunStatusQuery = useQuery({
    queryKey: queryKeys.dataProcessingRunStatus(options.selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: ({ signal }) =>
      fetchDataProcessingRunStatus(
        options.selectedSourceCollectionRunEffectiveId,
        { signal },
      ),
    enabled: sourceCollectionRunStatusQueryEnabled,
    refetchInterval: (query) => {
      const status = query.state.data as DataProcessingStatus | undefined;
      return sourceCollectionRunRefetchInterval(options.pageVisible, status?.runStatus || "");
    },
  });

  const selectedRunStatus =
    sourceCollectionRunStatusQuery.data?.runStatus
    || sourceCollectionSummaryQuery.data?.runStatus?.runStatus
    || options.selectedRunStatusFallback
    || "";

  const sourceCollectionRecordsQuery = useQuery({
    queryKey: sourceCollectionRunRecordsQueryKey(options.selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: ({ signal }) =>
      listDataProcessingRunRecords<DataProcessingRecordListPayload>(
        options.selectedSourceCollectionRunEffectiveId,
        { signal },
      ),
    enabled: sourceCollectionRecordsQueryEnabled,
    refetchInterval: () => sourceCollectionRunRefetchInterval(options.pageVisible, selectedRunStatus),
  });

  const sourceCollectionAssignmentsQuery = useQuery({
    queryKey: queryKeys.dataProcessingCollectionAssignments(options.selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: ({ signal }) =>
      listDataProcessingCollectionAssignments(
        options.selectedSourceCollectionRunEffectiveId,
        { signal },
      ),
    enabled: sourceCollectionAssignmentsQueryEnabled,
    refetchInterval: () => sourceCollectionRunRefetchInterval(options.pageVisible, selectedRunStatus),
  });

  return {
    sourceCollectionSummaryQuery,
    sourceCollectionRunStatusQuery,
    sourceCollectionRecordsQuery,
    sourceCollectionAssignmentsQuery,
  };
}
