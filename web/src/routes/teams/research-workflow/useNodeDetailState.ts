/**
 * Node-detail state hook for the research workflow inspector.
 *
 * Owns the fetch lifecycle for ONE selected node:
 * - loading / empty / error(retryable) states are distinct and visible;
 * - switching nodes CLEARS the previous detail before the new fetch starts,
 *   so stale info from the previous node never flashes on the new one;
 * - failures never silently clear the last good detail: the error state
 *   keeps the request context and offers a retry.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { fetchResearchWorkflowNodeDetail } from "../../../api/research-workflow/runs";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";

export type NodeDetailState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "empty"; nodeId: string }
  | { kind: "ready"; detail: ResearchWorkflowNodeDetail }
  | { kind: "error"; nodeId: string; message: string };

export function useNodeDetailState(
  teamId: string,
  runId: string,
  nodeId: string | null,
  runVersion: number | null = null,
): {
  state: NodeDetailState;
  retry: () => void;
} {
  const [state, setState] = useState<NodeDetailState>({ kind: "idle" });
  const [retryTick, setRetryTick] = useState(0);
  const fetchGenRef = useRef(0);

  const load = useCallback(
    async (targetRunId: string, targetNodeId: string) => {
      const gen = ++fetchGenRef.current;
      setState({ kind: "loading" });
      try {
        const detail = await fetchResearchWorkflowNodeDetail({
          runId: targetRunId,
          nodeId: targetNodeId,
          teamId,
        });
        if (gen !== fetchGenRef.current) {
          return;
        }
        if (!detail || !detail.nodeId) {
          setState({ kind: "empty", nodeId: targetNodeId });
          return;
        }
        setState({ kind: "ready", detail });
      } catch (err) {
        if (gen !== fetchGenRef.current) {
          return;
        }
        setState({
          kind: "error",
          nodeId: targetNodeId,
          message: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [teamId],
  );

  useEffect(() => {
    fetchGenRef.current += 1;
    if (!runId || !nodeId) {
      setState({ kind: "idle" });
      return;
    }
    void load(runId, nodeId);
  }, [teamId, runId, nodeId, runVersion, load, retryTick]);

  const retry = useCallback(() => {
    if (runId && nodeId) {
      setRetryTick((tick) => tick + 1);
    }
  }, [runId, nodeId]);

  let visible = state;
  if (visible.kind !== "idle" && visible.kind !== "loading") {
    if (visible.kind === "ready") {
      if (visible.detail.runId !== runId || visible.detail.nodeId !== nodeId) {
        visible = { kind: "loading" };
      }
    } else if (visible.nodeId !== nodeId) {
      visible = { kind: "loading" };
    }
  }

  return { state: visible, retry };
}
