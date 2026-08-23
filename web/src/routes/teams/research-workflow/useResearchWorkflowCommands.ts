import { useCallback, useRef, useState } from "react";

import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type {
  CreateResearchWorkflowRunInput,
  WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";

type ReplaceParams = (patch: Record<string, string | null | undefined>) => void;

function commandErrorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function isRunVersionConflict(reason: unknown): boolean {
  return commandErrorMessage(reason).includes("run_version_conflict");
}

export function useResearchWorkflowCommands(options: {
  teamId: string;
  runId: string;
  selectedNodeId: string | null;
  run: WorkflowRunRecord | null;
  nodeDetail: ResearchWorkflowNodeDetail | null;
  commandOffers?: CommandOffer[];
  submitFormalOffer?: (offer: CommandOffer) => Promise<unknown>;
  createRun: (input: CreateResearchWorkflowRunInput) => Promise<WorkflowRunRecord>;
  refresh: () => Promise<void>;
  replaceParams: ReplaceParams;
}) {
  const {
    run,
    nodeDetail,
    commandOffers,
    submitFormalOffer,
    createRun,
    refresh,
    replaceParams,
  } = options;
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const offerPendingRef = useRef(false);

  const pendingTaskId = useCallback(
    (nodeId: string): string | null => {
      const pending = (run?.humanTasks ?? []).find(
        (task) => String(task.status) === "pending" && String(task.nodeId) === nodeId,
      );
      return pending ? String(pending.taskId || "") || null : null;
    },
    [run],
  );

  const submitRun = useCallback(
    async (input: CreateResearchWorkflowRunInput) => {
      setError(null);
      try {
        const created = await createRun(input);
        const questionId = created.questionId || input.questionId;
        const node = await fetchHypothesisFirstFocusNode(options.teamId, questionId);
        replaceParams({
          runId: created.runId,
          questionId,
          node,
          panel: "node",
        });
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : String(reason);
        setError(message);
        throw reason;
      }
    },
    [createRun, options.teamId, replaceParams],
  );

  const submitOffer = useCallback(
    async (offer: CommandOffer) => {
      if (!submitFormalOffer) {
        const reason = new Error("正式命令通道未就绪");
        setError(reason.message);
        throw reason;
      }
      if (offerPendingRef.current) return;
      offerPendingRef.current = true;
      setBusy(true);
      setError(null);
      try {
        try {
          await submitFormalOffer(offer);
        } catch (reason) {
          setError(commandErrorMessage(reason));
          if (isRunVersionConflict(reason)) {
            try {
              await refresh();
            } catch {
              // The signed offer conflict remains authoritative even if resync also fails.
            }
          }
          throw reason;
        }
        try {
          await refresh();
        } catch (reason) {
          setError(commandErrorMessage(reason));
          throw reason;
        }
      } finally {
        offerPendingRef.current = false;
        setBusy(false);
      }
    },
    [refresh, submitFormalOffer],
  );

  return {
    error,
    busy,
    pendingTaskId,
    submitRun,
    submitOffer,
    nodeOffers: nodeDetail?.commandOffers ?? commandOffers ?? [],
  };
}
