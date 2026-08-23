/**
 * Formal snapshot read-model reducer (T6).
 * Server snapshot is authority; UI selection/viewport never enter this state.
 */

import type { ResearchWorkflowSnapshot } from "../../../api/types/research-workflow/core";

export type SnapshotReadModelState = {
  generation: number;
  teamId: string;
  runId: string;
  snapshot: ResearchWorkflowSnapshot | null;
  lastSequence: number;
  pendingRequestId: string | null;
  commandError: string | null;
  resyncRequired: boolean;
};

export function emptySnapshotReadModel(
  teamId = "",
  runId = "",
): SnapshotReadModelState {
  return {
    generation: 0,
    teamId,
    runId,
    snapshot: null,
    lastSequence: 0,
    pendingRequestId: null,
    commandError: null,
    resyncRequired: false,
  };
}

export function beginSnapshotFetch(
  state: SnapshotReadModelState,
  options: { teamId: string; runId: string; requestId: string },
): SnapshotReadModelState {
  const teamId = String(options.teamId || "");
  const runId = String(options.runId || "");
  const switched = state.teamId !== teamId || state.runId !== runId;
  if (switched) {
    return {
      ...emptySnapshotReadModel(teamId, runId),
      generation: state.generation + 1,
      pendingRequestId: options.requestId,
    };
  }
  return {
    ...state,
    pendingRequestId: options.requestId,
  };
}

export function applySnapshotResponse(
  state: SnapshotReadModelState,
  options: {
    teamId: string;
    runId: string;
    requestId: string;
    generation: number;
    snapshot: ResearchWorkflowSnapshot;
  },
): SnapshotReadModelState {
  // Stale response for a previous run/generation must not overwrite.
  if (options.generation !== state.generation) {
    return state;
  }
  if (state.teamId !== options.teamId || state.runId !== options.runId) {
    return state;
  }
  if (state.pendingRequestId && state.pendingRequestId !== options.requestId) {
    return state;
  }
  const snapshotRun = options.snapshot.run;
  // The payload scope is part of the authority contract; a correctly scoped
  // request must never hydrate a different run/team just because the HTTP
  // response arrived late.
  if (
    String(snapshotRun?.teamId || "") !== String(options.teamId || "")
    || String(snapshotRun?.runId || "") !== String(options.runId || "")
  ) {
    return {
      ...state,
      pendingRequestId: null,
      commandError: "snapshot_scope_mismatch",
      resyncRequired: true,
    };
  }
  if (options.snapshot.schemaVersion != null && options.snapshot.schemaVersion !== 2) {
    return {
      ...state,
      pendingRequestId: null,
      commandError: "snapshot_schema_unsupported",
      resyncRequired: true,
    };
  }
  const nextSequence = Number(options.snapshot.latestEventSequence || 0);
  const currentSequence = Number(state.lastSequence || 0);
  const currentRunVersion = Number(state.snapshot?.run?.runVersion ?? 0);
  const nextRunVersion = Number(snapshotRun?.runVersion ?? 0);
  // Snapshot refreshes are monotonic within one scoped run. A delayed response
  // may clear the request marker, but it cannot roll back task/progress facts.
  if (
    nextSequence < currentSequence
    || (nextSequence === currentSequence && nextRunVersion < currentRunVersion)
  ) {
    return {
      ...state,
      pendingRequestId: null,
    };
  }
  // Empty/same sequence must not create a refetch loop by itself.
  return {
    ...state,
    snapshot: options.snapshot,
    lastSequence: nextSequence,
    pendingRequestId: null,
    commandError: null,
    resyncRequired: false,
  };
}

export function clearCommandError(state: SnapshotReadModelState): SnapshotReadModelState {
  return { ...state, commandError: null };
}

export function setCommandError(
  state: SnapshotReadModelState,
  error: string,
): SnapshotReadModelState {
  return { ...state, commandError: error };
}
