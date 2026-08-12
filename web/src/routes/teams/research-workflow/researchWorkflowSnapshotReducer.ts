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
  const nextSequence = Number(options.snapshot.latestEventSequence || 0);
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
