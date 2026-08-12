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
  applyStreamEvent: (event: WorkflowEventEnvelope) => void;
} {
  const { teamId, runId, enabled, latestEventSequence } = options;
  const [model, setModel] = useState<FormalEventReadModel>(() =>
    emptyFormalEventReadModel(teamId, runId),
  );
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resyncNonce, setResyncNonce] = useState(0);
  const mountedRef = useRef(true);
  const latestSequenceRef = useRef(latestEventSequence);
  latestSequenceRef.current = latestEventSequence;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    setModel(emptyFormalEventReadModel(teamId, runId));
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
        if (next.events.length > 0) {
          setModel(next);
        } else {
          setModel(
            hydrateFormalEventFromSnapshot(next, {
              teamId,
              runId,
              latestEventSequence: latestSequenceRef.current,
            }),
          );
        }
        setError(next.resyncRequired ? "工作流事件序列出现缺口，正在重新同步" : null);
        setReady(true);
      } catch (reason) {
        if (controller.signal.aborted || !mountedRef.current) return;
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setModel(
          hydrateFormalEventFromSnapshot(emptyFormalEventReadModel(teamId, runId), {
            teamId,
            runId,
            latestEventSequence: latestSequenceRef.current,
          }),
        );
        setError(reason instanceof Error ? reason.message : String(reason));
        setReady(true);
      }
    })();
    return () => {
      controller.abort();
    };
  }, [enabled, resyncNonce, runId, teamId]);

  const applyStreamEvent = useCallback((event: WorkflowEventEnvelope) => {
    setModel((current) => {
      const next = applyFormalEvent(current, event);
      if (next.resyncRequired && !current.resyncRequired) {
        queueMicrotask(() => setResyncNonce((nonce) => nonce + 1));
      }
      return next;
    });
  }, []);

  return {
    model,
    ready,
    error,
    applyStreamEvent,
  };
}
