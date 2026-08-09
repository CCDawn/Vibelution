import { useEffect, useRef, useState } from "react";

import { researchWorkflowStreamUrl } from "../../../api/researchWorkflow";
import type { WorkflowEventLike } from "./researchWorkflowEventReducer";
import { RESEARCH_WORKFLOW_SSE_EVENT_TYPES } from "./researchWorkflowSseEventTypes";

export type ResearchWorkflowStreamState = "idle" | "connecting" | "connected" | "reconnecting";

export function useResearchWorkflowStream(options: {
  teamId: string;
  runId: string;
  onDelta: (event: WorkflowEventLike) => void;
  onSnapshot: (cursor: number) => void;
}): { state: ResearchWorkflowStreamState; error: string | null } {
  const { teamId, runId, onDelta, onSnapshot } = options;
  const [state, setState] = useState<ResearchWorkflowStreamState>("idle");
  const [error, setError] = useState<string | null>(null);
  const lastSequenceRef = useRef(0);
  const onDeltaRef = useRef(onDelta);
  const onSnapshotRef = useRef(onSnapshot);

  onDeltaRef.current = onDelta;
  onSnapshotRef.current = onSnapshot;

  useEffect(() => {
    lastSequenceRef.current = 0;
    if (!teamId.trim() || !runId.trim()) {
      setState("idle");
      setError(null);
      return;
    }
    if (typeof EventSource === "undefined") {
      setState("idle");
      setError("当前浏览器不支持工作流实时连接");
      return;
    }

    setState("connecting");
    setError(null);
    const source = new EventSource(researchWorkflowStreamUrl(runId, { teamId }));

    source.onopen = () => {
      setState("connected");
      setError(null);
    };
    source.onerror = () => {
      setState("reconnecting");
      setError("工作流实时连接中断，正在重连");
    };
    source.addEventListener("snapshot", (raw) => {
      const message = raw as MessageEvent<string>;
      try {
        const payload = JSON.parse(message.data) as { cursor?: number };
        const cursor = Number(payload.cursor) || 0;
        lastSequenceRef.current = Math.max(lastSequenceRef.current, cursor);
        onSnapshotRef.current(cursor);
      } catch {
        setError("工作流快照格式无效");
      }
    });
    const onTypedEvent = (raw: Event) => {
      const message = raw as MessageEvent<string>;
      try {
        const event = JSON.parse(message.data) as WorkflowEventLike;
        const sequence = Number(event.sequence) || 0;
        if (sequence <= lastSequenceRef.current) return;
        lastSequenceRef.current = sequence;
        onDeltaRef.current(event);
      } catch {
        setError("工作流事件格式无效");
      }
    };
    for (const type of RESEARCH_WORKFLOW_SSE_EVENT_TYPES) {
      source.addEventListener(type, onTypedEvent);
    }

    return () => {
      source.close();
    };
  }, [runId, teamId]);

  return { state, error };
}
