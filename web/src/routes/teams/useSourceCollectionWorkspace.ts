/**
 * Source-collection workspace state machine for Teams.
 * Phase 1: owns SC UI state, project/run list queries, default-run selection,
 * draft hydration, and selected-run detail queries.
 *
 * Mutations that also serve non-SC surfaces stay in TeamsRoute and receive setters from here.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { listDataProcessingRuns } from "../../api/dataProcessing";
import { queryKeys } from "../../api/queryKeys";
import { listTeamResearchProjects } from "../../api/researchProjectAgentTasks";
import type { DataProcessingRunListPayload } from "../../api/types";
import {
  SOURCE_COLLECTION_RUN_PREVIEW_LIMIT,
  sourceCollectionFreshProjectDraft,
  type SourceCollectionDraft,
} from "./source-collection/presentationModel";
import type { SourceCollectionSourceFilter } from "./source-collection/evidenceModel";
import {
  selectDefaultSourceCollectionRun,
  sourceCollectionRunHasUsableRecords,
  sourceCollectionRunsForTeam,
} from "./source-collection/runModel";
import type { SourceCollectionStageModuleId } from "./source-collection/stageProjection";
import { researchProjectQueryKey } from "./research-projects/ResearchProjectSwitcher";
import type { TeamResearchProject, TeamResearchProjectListPayload } from "../../api/types";
import { sourceCollectionRunListRefetchInterval } from "./workflowPresentation";
import { useSourceCollectionRunQueries } from "./useSourceCollectionRunQueries";
import type { SourceCollectionOutputDraft } from "./sourceCollectionMutationModel";
import { sourceCollectionSummaryQuerySeedText } from "./sourceCollectionRunQueryModel";
import {
  resolveResearchProjectsQueryEnabled,
  resolveSourceCollectionRunsQueryEnabled,
} from "./teamDetailLoadPolicy";

export type UseSourceCollectionWorkspaceInput = {
  effectiveTeamId: string;
  pageVisible: boolean;
  /** Research workflow team selected (challenge cup / research-team). */
  researchWorkflowTeamSelected: boolean;
  /** Standalone SC page or research view is source/knowledge collection. */
  sourceCollectionWorkspaceSelected: boolean;
  /** URL/forced initial stage when mounting. */
  initialStageId?: SourceCollectionStageModuleId | null;
};

const EMPTY_OUTPUT_DRAFT: SourceCollectionOutputDraft = {
  assignmentId: "",
  sourceType: "paper",
  title: "",
  sourceRef: "",
  rawLocation: "",
  summary: "",
  notes: "",
};

// Panel expand/focus is a per-session UI preference, not layout memory (pane
// sizes stay on WORKBENCH_LAYOUT_IDS) and not deep-link state, so it lives in
// sessionStorage keyed by team.
const SC_PANEL_STATE_STORAGE_PREFIX = "vibelution.sc-workspace-panels.";

type SourceCollectionPanelStateSnapshot = {
  expandedPanelId: string;
  focusedPanelId: string;
};

export function readSourceCollectionPanelState(teamId: string): SourceCollectionPanelStateSnapshot | null {
  if (!teamId || typeof window === "undefined" || typeof window.sessionStorage === "undefined") {
    return null;
  }
  try {
    const raw = window.sessionStorage.getItem(SC_PANEL_STATE_STORAGE_PREFIX + teamId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<SourceCollectionPanelStateSnapshot> | null;
    return {
      expandedPanelId: typeof parsed?.expandedPanelId === "string" ? parsed.expandedPanelId : "",
      focusedPanelId: typeof parsed?.focusedPanelId === "string" ? parsed.focusedPanelId : "",
    };
  } catch {
    return null;
  }
}

export function writeSourceCollectionPanelState(teamId: string, snapshot: SourceCollectionPanelStateSnapshot) {
  if (!teamId || typeof window === "undefined" || typeof window.sessionStorage === "undefined") {
    return;
  }
  try {
    window.sessionStorage.setItem(SC_PANEL_STATE_STORAGE_PREFIX + teamId, JSON.stringify(snapshot));
  } catch {
    // Storage blocked/full: panel recovery is a convenience, never fatal.
  }
}

export function useSourceCollectionWorkspace(input: UseSourceCollectionWorkspaceInput) {
  const {
    effectiveTeamId,
    pageVisible,
    researchWorkflowTeamSelected,
    sourceCollectionWorkspaceSelected,
    initialStageId,
  } = input;

  const sourceCollectionDraftHydratedRunIdRef = useRef("");
  const sourceCollectionDraftHydratedSearchPlanRef = useRef("");
  const sourceCollectionFreshProjectDraftIdRef = useRef("");

  const [sourceCollectionDraft, setSourceCollectionDraft] = useState<SourceCollectionDraft>(() =>
    sourceCollectionFreshProjectDraft({ name: "", topic: "" }),
  );
  const [selectedSourceCollectionRunId, setSelectedSourceCollectionRunId] = useState("");
  const [sourceCollectionOutputDraft, setSourceCollectionOutputDraft] = useState<SourceCollectionOutputDraft>(
    EMPTY_OUTPUT_DRAFT,
  );
  const [selectedSourceCollectionStageId, setSelectedSourceCollectionStageId] = useState<SourceCollectionStageModuleId>(
    initialStageId ?? "finding",
  );
  const [sourceCollectionStageSyncUntilMs, setSourceCollectionStageSyncUntilMs] = useState(0);
  const [sourceCollectionPendingStageTaskIds, setSourceCollectionPendingStageTaskIds] = useState<
    Partial<Record<SourceCollectionStageModuleId, string[]>>
  >({});
  const [sourceCollectionResultPageByStage, setSourceCollectionResultPageByStage] = useState<
    Record<SourceCollectionStageModuleId, number>
  >({
    finding: 1,
    extraction: 1,
    relations: 1,
    ingestion: 1,
  });
  const [sourceCollectionExpandedPanelId, setSourceCollectionExpandedPanelId] = useState(
    () => readSourceCollectionPanelState(effectiveTeamId)?.expandedPanelId ?? "",
  );
  const [sourceCollectionFocusedPanelId, setSourceCollectionFocusedPanelId] = useState(
    () => readSourceCollectionPanelState(effectiveTeamId)?.focusedPanelId ?? "",
  );
  const [sourceCollectionSourceFilter, setSourceCollectionSourceFilter] = useState<SourceCollectionSourceFilter>("all");
  const [selectedSourceCollectionCandidateId, setSelectedSourceCollectionCandidateId] = useState("");

  // Keep stage in sync when forced/URL initial stage changes after mount.
  useEffect(() => {
    if (initialStageId) {
      setSelectedSourceCollectionStageId(initialStageId);
    }
  }, [initialStageId]);

  // Hydrate panel expand/focus once the team id resolves (it may arrive async
  // after refresh); only fill still-untouched state so user actions win.
  const sourceCollectionPanelStateHydratedTeamRef = useRef("");
  useEffect(() => {
    if (!effectiveTeamId || sourceCollectionPanelStateHydratedTeamRef.current === effectiveTeamId) {
      return;
    }
    sourceCollectionPanelStateHydratedTeamRef.current = effectiveTeamId;
    const snapshot = readSourceCollectionPanelState(effectiveTeamId);
    if (!snapshot) return;
    setSourceCollectionExpandedPanelId((current) => current || snapshot.expandedPanelId);
    setSourceCollectionFocusedPanelId((current) => current || snapshot.focusedPanelId);
  }, [effectiveTeamId]);

  useEffect(() => {
    writeSourceCollectionPanelState(effectiveTeamId, {
      expandedPanelId: sourceCollectionExpandedPanelId,
      focusedPanelId: sourceCollectionFocusedPanelId,
    });
  }, [effectiveTeamId, sourceCollectionExpandedPanelId, sourceCollectionFocusedPanelId]);

  const sourceCollectionRunsQueryEnabled = resolveSourceCollectionRunsQueryEnabled({
    effectiveTeamId,
    researchWorkflowTeamSelected,
    sourceCollectionWorkspaceSelected,
  });
  const researchProjectsQueryEnabled = resolveResearchProjectsQueryEnabled({
    effectiveTeamId,
    researchWorkflowTeamSelected,
  });

  const sourceCollectionResearchProjectsQuery = useQuery<TeamResearchProjectListPayload>({
    queryKey: researchProjectQueryKey(effectiveTeamId || "none"),
    queryFn: ({ signal }) =>
      listTeamResearchProjects(effectiveTeamId, { signal }),
    enabled: researchProjectsQueryEnabled,
    staleTime: 10_000,
  });
  const activeSourceCollectionResearchProjectId = sourceCollectionResearchProjectsQuery.data?.activeProjectId || "";

  const sourceCollectionRunsQuery = useQuery({
    queryKey: [
      ...queryKeys.teamWorkflowSourceCollectionRuns(effectiveTeamId || "none", SOURCE_COLLECTION_RUN_PREVIEW_LIMIT),
      activeSourceCollectionResearchProjectId || "unresolved-project",
    ],
    queryFn: ({ signal }) =>
      listDataProcessingRuns({
        limit: SOURCE_COLLECTION_RUN_PREVIEW_LIMIT,
        teamId: effectiveTeamId,
        startedFrom: "team_workflow_source_collection",
        signal,
      }),
    enabled: sourceCollectionRunsQueryEnabled && Boolean(activeSourceCollectionResearchProjectId),
    refetchInterval: (query) => {
      const payload = query.state.data as DataProcessingRunListPayload | undefined;
      const hasActiveRun = (payload?.runs ?? []).some((run) =>
        ["collecting", "processing"].includes(String(run.status || "").toLowerCase()),
      );
      return sourceCollectionRunListRefetchInterval(pageVisible, hasActiveRun);
    },
    staleTime: 5_000,
  });

  const sourceCollectionRuns = useMemo(
    () => sourceCollectionRunsForTeam(
      sourceCollectionRunsQuery.data,
      effectiveTeamId,
      activeSourceCollectionResearchProjectId,
    ),
    [activeSourceCollectionResearchProjectId, effectiveTeamId, sourceCollectionRunsQuery.data],
  );
  const activeSourceCollectionResearchProject = useMemo<TeamResearchProject | null>(
    () => sourceCollectionResearchProjectsQuery.data?.projects.find(
      (project) => project.projectId === activeSourceCollectionResearchProjectId,
    ) ?? null,
    [activeSourceCollectionResearchProjectId, sourceCollectionResearchProjectsQuery.data?.projects],
  );

  const sourceCollectionLatestRun = sourceCollectionRuns[0] ?? null;
  const sourceCollectionHistoricalRunWithRecords =
    sourceCollectionRuns.find(sourceCollectionRunHasUsableRecords) ?? null;
  const selectedSourceCollectionRun = selectDefaultSourceCollectionRun(
    sourceCollectionRuns,
    selectedSourceCollectionRunId,
  );
  const sourceCollectionLatestRunIsEmpty = Boolean(
    sourceCollectionLatestRun
    && !sourceCollectionRunHasUsableRecords(sourceCollectionLatestRun),
  );
  const sourceCollectionShowingHistoricalRunByDefault = Boolean(
    !selectedSourceCollectionRunId
    && sourceCollectionLatestRunIsEmpty
    && sourceCollectionHistoricalRunWithRecords
    && selectedSourceCollectionRun?.runId === sourceCollectionHistoricalRunWithRecords.runId
    && sourceCollectionLatestRun?.runId !== sourceCollectionHistoricalRunWithRecords.runId,
  );
  const selectedSourceCollectionRunEffectiveId = selectedSourceCollectionRun?.runId ?? "";
  const sourceCollectionSelectedRunTopic = String(selectedSourceCollectionRun?.scope?.topic || "").trim();
  const sourceCollectionSelectedRunGoal = String(selectedSourceCollectionRun?.scope?.goal || "").trim();
  const sourceCollectionSelectedRunQueryCount =
    Number(
      selectedSourceCollectionRun?.metadata?.queryCount
      ?? selectedSourceCollectionRun?.scope?.dataSearchPlanRef?.queryCount,
    ) || 0;

  // Reset stage result pagination when the effective run or list filter changes.
  useEffect(() => {
    setSourceCollectionResultPageByStage({
      finding: 1,
      extraction: 1,
      relations: 1,
      ingestion: 1,
    });
  }, [selectedSourceCollectionRunEffectiveId, sourceCollectionSourceFilter]);

  useEffect(() => {
    if (
      !selectedSourceCollectionRunEffectiveId
      || sourceCollectionDraftHydratedRunIdRef.current === selectedSourceCollectionRunEffectiveId
    ) {
      return;
    }
    sourceCollectionDraftHydratedRunIdRef.current = selectedSourceCollectionRunEffectiveId;
    sourceCollectionDraftHydratedSearchPlanRef.current = "";
    setSourceCollectionDraft((current) => ({
      ...current,
      title: selectedSourceCollectionRun?.title || current.title,
      topic: sourceCollectionSelectedRunTopic || current.topic,
      goal: sourceCollectionSelectedRunGoal || current.goal,
      querySeeds: "",
    }));
  }, [
    selectedSourceCollectionRun?.title,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSelectedRunGoal,
    sourceCollectionSelectedRunTopic,
  ]);

  const sourceCollectionFindingDetailsVisible = Boolean(
    sourceCollectionWorkspaceSelected
    && selectedSourceCollectionRunEffectiveId
    && selectedSourceCollectionStageId === "finding",
  );

  const sourceCollectionStageWritebackSyncActive = sourceCollectionStageSyncUntilMs > Date.now();
  const sourceCollectionPendingStageTaskIdList = useMemo(
    () =>
      Object.values(sourceCollectionPendingStageTaskIds)
        .flat()
        .filter((taskId): taskId is string => Boolean(taskId)),
    [sourceCollectionPendingStageTaskIds],
  );
  const sourceCollectionStageWritebackAwaitingTask =
    sourceCollectionStageWritebackSyncActive && sourceCollectionPendingStageTaskIdList.length > 0;

  const {
    sourceCollectionSummaryQuery,
    sourceCollectionRunStatusQuery,
    sourceCollectionRecordsQuery,
    sourceCollectionAssignmentsQuery,
  } = useSourceCollectionRunQueries({
    effectiveTeamId,
    pageVisible,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionWorkspaceSelected,
    sourceCollectionFindingDetailsVisible,
    sourceCollectionStageWritebackSyncActive,
    selectedRunStatusFallback: selectedSourceCollectionRun?.status || "",
  });

  useEffect(() => {
    const querySeedText = sourceCollectionSummaryQuerySeedText(
      sourceCollectionSummaryQuery.data,
      selectedSourceCollectionRunEffectiveId,
    );
    const searchPlanId = String(sourceCollectionSummaryQuery.data?.searchPlan?.planId || "").trim();
    const hydrationKey = `${selectedSourceCollectionRunEffectiveId}:${searchPlanId}`;
    if (
      !querySeedText
      || !searchPlanId
      || sourceCollectionDraftHydratedSearchPlanRef.current === hydrationKey
    ) {
      return;
    }
    sourceCollectionDraftHydratedSearchPlanRef.current = hydrationKey;
    setSourceCollectionDraft((current) => ({
      ...current,
      querySeeds: querySeedText,
    }));
  }, [selectedSourceCollectionRunEffectiveId, sourceCollectionSummaryQuery.data]);

  useEffect(() => {
    if (
      !activeSourceCollectionResearchProject
      || sourceCollectionRunsQuery.isPending
      || sourceCollectionRuns.length > 0
      || sourceCollectionFreshProjectDraftIdRef.current === activeSourceCollectionResearchProject.projectId
    ) {
      return;
    }
    sourceCollectionFreshProjectDraftIdRef.current = activeSourceCollectionResearchProject.projectId;
    sourceCollectionDraftHydratedRunIdRef.current = "";
    sourceCollectionDraftHydratedSearchPlanRef.current = "";
    setSelectedSourceCollectionRunId("");
    setSourceCollectionDraft(sourceCollectionFreshProjectDraft(activeSourceCollectionResearchProject));
  }, [
    activeSourceCollectionResearchProject,
    sourceCollectionRuns.length,
    sourceCollectionRunsQuery.isPending,
  ]);

  return {
    // state
    sourceCollectionDraft,
    setSourceCollectionDraft,
    selectedSourceCollectionRunId,
    setSelectedSourceCollectionRunId,
    sourceCollectionOutputDraft,
    setSourceCollectionOutputDraft,
    selectedSourceCollectionStageId,
    setSelectedSourceCollectionStageId,
    sourceCollectionStageSyncUntilMs,
    setSourceCollectionStageSyncUntilMs,
    sourceCollectionPendingStageTaskIds,
    setSourceCollectionPendingStageTaskIds,
    sourceCollectionResultPageByStage,
    setSourceCollectionResultPageByStage,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionFocusedPanelId,
    setSourceCollectionFocusedPanelId,
    sourceCollectionSourceFilter,
    setSourceCollectionSourceFilter,
    selectedSourceCollectionCandidateId,
    setSelectedSourceCollectionCandidateId,
    // refs (for reset handlers that previously touched them)
    sourceCollectionDraftHydratedRunIdRef,
    sourceCollectionDraftHydratedSearchPlanRef,
    sourceCollectionFreshProjectDraftIdRef,
    // project + runs
    sourceCollectionResearchProjectsQuery,
    activeSourceCollectionResearchProjectId,
    activeSourceCollectionResearchProject,
    sourceCollectionRunsQuery,
    sourceCollectionRuns,
    sourceCollectionLatestRun,
    sourceCollectionHistoricalRunWithRecords,
    selectedSourceCollectionRun,
    sourceCollectionLatestRunIsEmpty,
    sourceCollectionShowingHistoricalRunByDefault,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSelectedRunTopic,
    sourceCollectionSelectedRunGoal,
    sourceCollectionSelectedRunQueryCount,
    // writeback
    sourceCollectionStageWritebackSyncActive,
    sourceCollectionPendingStageTaskIdList,
    sourceCollectionStageWritebackAwaitingTask,
    // detail queries
    sourceCollectionFindingDetailsVisible,
    sourceCollectionSummaryQuery,
    sourceCollectionRunStatusQuery,
    sourceCollectionRecordsQuery,
    sourceCollectionAssignmentsQuery,
  };
}

export type SourceCollectionWorkspaceApi = ReturnType<typeof useSourceCollectionWorkspace>;
