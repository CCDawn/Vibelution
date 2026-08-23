import { useCallback, useEffect, useRef, useState } from "react";

import { replayResearchWorkflowEvents } from "../../../api/research-workflow/events";
import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import {
  applyFormalEvent,
  applyFormalEventBatch,
  emptyFormalEventReadModel,
  hydrateFormalEventFromSnapshot,
  type FormalEventReadModel,
} from "./researchWorkflowEventReducer";

export function useResearchWorkflowEventReplay(options: {
  teamId: string;
  runId: string;
  enabled: boolean;
  latestEventSequence: number;
}): {
  model: FormalEventReadModel;
  ready: boolean;
  error: string | null;
  applyStreamEvent: (event: WorkflowEventEnvelope) => {
    accepted: boolean;
    resyncRequired: boolean;
  };
} {
  const { teamId, runId, enabled, latestEventSequence } = options;
  const [model, setModel] = useState<FormalEventReadModel>(() =>
    emptyFormalEventReadModel(teamId, runId),
  );
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resyncNonce, setResyncNonce] = useState(0);
  const mountedRef = useRef(true);
  const modelRef = useRef(model);
  const latestSequenceRef = useRef(latestEventSequence);
  latestSequenceRef.current = latestEventSequence;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    const empty = emptyFormalEventReadModel(teamId, runId);
    modelRef.current = empty;
    setModel(empty);
    setReady(false);
    setError(null);
  }, [runId, teamId]);

  useEffect(() => {
    if (!enabled || !teamId.trim() || !runId.trim()) {
      setReady(false);
      return;
    }
    const controller = new AbortController();
    setReady(false);
    void (async () => {
      try {
        const events = await replayResearchWorkflowEvents({
          teamId,
          runId,
          signal: controller.signal,
        });
        if (controller.signal.aborted || !mountedRef.current) return;
        const next = applyFormalEventBatch(
          emptyFormalEventReadModel(teamId, runId),
          events,
        );
        const hydrated = next.events.length > 0
          ? next
          : hydrateFormalEventFromSnapshot(next, {
              teamId,
              runId,
              latestEventSequence: latestSequenceRef.current,
            });
        // A snapshot is already authoritative at latestEventSequence. Replay
        // may therefore contain only the committed prefix; never move the
        // cursor backwards and replay an already-covered prefix forever.
        const withSnapshotCursor = !hydrated.resyncRequired
          && latestSequenceRef.current > hydrated.lastSequence
          ? { ...hydrated, lastSequence: latestSequenceRef.current }
          : hydrated;
        modelRef.current = withSnapshotCursor;
        setModel(withSnapshotCursor);
        setError(withSnapshotCursor.resyncRequired ? "工作流事件序列出现缺口，正在重新同步" : null);
        setReady(true);
      } catch (reason) {
        if (controller.signal.aborted || !mountedRef.current) return;
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        const hydrated = hydrateFormalEventFromSnapshot(emptyFormalEventReadModel(teamId, runId), {
          teamId,
          runId,
          latestEventSequence: latestSequenceRef.current,
        });
        modelRef.current = hydrated;
        setModel(hydrated);
        setError(reason instanceof Error ? reason.message : String(reason));
        setReady(true);
      }
    })();
    return () => {
      controller.abort();
    };
  }, [enabled, resyncNonce, runId, teamId]);

  const applyStreamEvent = useCallback((event: WorkflowEventEnvelope) => {
    const current = modelRef.current;
    const next = applyFormalEvent(current, event);
    const sequence = Number(event.sequence) || 0;
    const accepted = next !== current
      && !next.resyncRequired
      && next.lastSequence === sequence;
    modelRef.current = next;
    setModel(next);
    if (next.resyncRequired && !current.resyncRequired) {
      queueMicrotask(() => setResyncNonce((nonce) => nonce + 1));
    }
    return { accepted, resyncRequired: next.resyncRequired };
  }, []);

  return {
    model,
    ready,
    error,
    applyStreamEvent,
  };
}
