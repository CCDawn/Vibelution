import { useCallback, useRef, useState } from "react";

import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type {
  CreateResearchWorkflowRunInput,
  WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import { trackResearchRunCreate, trackWorkflowOfferSubmit } from "../challengeCupTelemetry";
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
      const telemetry = trackResearchRunCreate({
        teamId: input.teamId,
        questionId: input.questionId,
        idempotencyKey: input.idempotencyKey,
        safetyLimits: input.safetyLimits,
      });
      setError(null);
      try {
        const created = await createRun(input);
        telemetry.succeeded({ runId: created.runId });
        const questionId = created.questionId || input.questionId;
        const node = await fetchHypothesisFirstFocusNode(options.teamId, questionId, created.runId);
        replaceParams({
          runId: created.runId,
          questionId,
          node,
          panel: "node",
        });
      } catch (reason) {
        telemetry.failed(reason);
        const message = reason instanceof Error ? reason.message : String(reason);
        setError(message);
        throw reason;
      }
    },
    [createRun, options.teamId, replaceParams],
  );

  const submitOffer = useCallback(
    async (offer: CommandOffer) => {
      if (offerPendingRef.current) return;
      const telemetry = trackWorkflowOfferSubmit({
        teamId: options.teamId,
        runId: options.runId,
        command: offer.command,
        nodeId: offer.nodeId ?? "",
        idempotencyKey: offer.idempotencyKey,
        expectedRunVersion: offer.expectedRunVersion,
      });
      if (!submitFormalOffer) {
        const reason = new Error("正式命令通道未就绪");
        telemetry.failed(reason, { stage: "channel_unavailable" });
        setError(reason.message);
        throw reason;
      }
      offerPendingRef.current = true;
      setBusy(true);
      setError(null);
      try {
        try {
          await submitFormalOffer(offer);
        } catch (reason) {
          telemetry.failed(reason, {
            stage: "submit",
            runVersionConflict: isRunVersionConflict(reason),
          });
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
          telemetry.failed(reason, { stage: "refresh" });
          setError(commandErrorMessage(reason));
          throw reason;
        }
        telemetry.succeeded();
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
