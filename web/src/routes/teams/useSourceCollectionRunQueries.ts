/**
 * Selected source-collection run detail queries for Teams.
 * Run list selection stays in Route; this hook owns summary/status/records/assignments.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  DataProcessingCollectionAssignmentListPayload,
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
    queryFn: ({ signal }) => {
      const params = options.selectedSourceCollectionRunEffectiveId
        ? `?runId=${encodeURIComponent(options.selectedSourceCollectionRunEffectiveId)}`
        : "";
      return fetchJson<SourceCollectionSummaryPayload>(
        `/api/teams/${encodeURIComponent(options.effectiveTeamId)}/workflow-orchestration/source-collection/summary${params}`,
        { signal },
      );
    },
    enabled: Boolean(options.effectiveTeamId && options.sourceCollectionWorkspaceSelected),
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
      fetchJson<DataProcessingStatus>(
        `/api/data-processing/runs/${encodeURIComponent(options.selectedSourceCollectionRunEffectiveId)}/status`,
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
      fetchJson<DataProcessingRecordListPayload>(
        `/api/data-processing/runs/${encodeURIComponent(options.selectedSourceCollectionRunEffectiveId)}/records`,
        { signal },
      ),
    enabled: sourceCollectionRecordsQueryEnabled,
    refetchInterval: () => sourceCollectionRunRefetchInterval(options.pageVisible, selectedRunStatus),
  });

  const sourceCollectionAssignmentsQuery = useQuery({
    queryKey: queryKeys.dataProcessingCollectionAssignments(options.selectedSourceCollectionRunEffectiveId || "none"),
    queryFn: ({ signal }) =>
      fetchJson<DataProcessingCollectionAssignmentListPayload>(
        `/api/data-processing/runs/${encodeURIComponent(options.selectedSourceCollectionRunEffectiveId)}/collection-assignments`,
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
