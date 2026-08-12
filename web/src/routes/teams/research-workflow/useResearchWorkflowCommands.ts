import { useCallback, useState } from "react";

import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type {
  CreateResearchWorkflowRunInput,
  WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";

type ReplaceParams = (patch: Record<string, string | null | undefined>) => void;

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
        replaceParams({
          runId: created.runId,
          node: created.runtimeCurrentNodeIds?.[0] || "source_finding",
          panel: "node",
        });
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : String(reason);
        setError(message);
        throw reason;
      }
    },
    [createRun, replaceParams],
  );

  const submitOffer = useCallback(
    async (offer: CommandOffer) => {
      if (!submitFormalOffer) {
        const reason = new Error("正式命令通道未就绪");
        setError(reason.message);
        throw reason;
      }
      setBusy(true);
      setError(null);
      try {
        await submitFormalOffer(offer);
        await refresh();
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
        throw reason;
      } finally {
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
