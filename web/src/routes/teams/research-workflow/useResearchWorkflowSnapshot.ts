import { useCallback, useEffect, useRef, useState } from "react";

import { fetchResearchWorkflowSnapshot } from "../../../api/research-workflow/runs";
import type { ResearchWorkflowSnapshot } from "../../../api/types/research-workflow/core";
import {
  applySnapshotResponse,
  beginSnapshotFetch,
  emptySnapshotReadModel,
  type SnapshotReadModelState,
} from "./researchWorkflowSnapshotReducer";

export type UseResearchWorkflowSnapshotResult = {
  snapshot: ResearchWorkflowSnapshot | null;
  lastSequence: number;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  generation: number;
};

function nextRequestId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `snapshot-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function useResearchWorkflowSnapshot(
  teamId: string,
  runId: string,
): UseResearchWorkflowSnapshotResult {
  const [state, setState] = useState<SnapshotReadModelState>(() =>
    emptySnapshotReadModel(teamId, runId),
  );
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const scopeRef = useRef({ teamId, runId });

  scopeRef.current = { teamId, runId };

  const refresh = useCallback(async () => {
    const scope = { ...scopeRef.current };
    const canonicalTeamId = scope.teamId.trim();
    const canonicalRunId = scope.runId.trim();

    if (!canonicalTeamId) {
      setState(emptySnapshotReadModel(scope.teamId, scope.runId));
      setError("缺少 teamId，无法读取科研流程");
      return;
    }

    if (!canonicalRunId) {
      setState(emptySnapshotReadModel(canonicalTeamId, ""));
      setError(null);
      return;
    }

    const requestId = nextRequestId();
    let generation = 0;
    setState((current) => {
      const next = beginSnapshotFetch(current, {
        teamId: canonicalTeamId,
        runId: canonicalRunId,
        requestId,
      });
      generation = next.generation;
      return next;
    });
    setError(null);

    try {
      const snapshot = await fetchResearchWorkflowSnapshot({
        teamId: canonicalTeamId,
        runId: canonicalRunId,
      });
      if (!mountedRef.current) return;
      if (
        scopeRef.current.teamId.trim() !== canonicalTeamId
        || scopeRef.current.runId.trim() !== canonicalRunId
      ) {
        return;
      }
      setState((current) =>
        applySnapshotResponse(current, {
          teamId: canonicalTeamId,
          runId: canonicalRunId,
          requestId,
          generation,
          snapshot,
        }),
      );
    } catch (reason) {
      if (!mountedRef.current) return;
      if (
        scopeRef.current.teamId.trim() !== canonicalTeamId
        || scopeRef.current.runId.trim() !== canonicalRunId
      ) {
        return;
      }
      setError(reason instanceof Error ? reason.message : String(reason));
      setState((current) => ({
        ...current,
        pendingRequestId: current.pendingRequestId === requestId ? null : current.pendingRequestId,
      }));
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    setState(emptySnapshotReadModel(teamId, runId));
    setError(null);
    void refresh();
  }, [refresh, runId, teamId]);

  return {
    snapshot: state.snapshot,
    lastSequence: state.lastSequence,
    loading: state.pendingRequestId !== null,
    error,
    refresh,
    generation: state.generation,
  };
}
