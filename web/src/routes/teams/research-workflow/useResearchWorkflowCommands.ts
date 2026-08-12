import { useCallback, useState } from "react";

import type { CommandOffer } from "../../../api/types/research-workflow/commands";
import type {
  CreateResearchWorkflowRunInput,
  WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";
import {
  childRunIdFromCommandResult,
  executeNodeCommand,
} from "./nodeCommandAdapter";

type ReplaceParams = (patch: Record<string, string | null | undefined>) => void;

const LEGACY_TO_FORMAL_COMMAND: Record<string, CommandOffer["command"]> = {
  start_agent_task: "start_node",
  retry_execution: "retry_node",
  rebind_node: "rebind_node",
  fork_evidence_remediation: "fork_revision",
  accept_handoff: "resolve_human_task",
  reject_handoff: "resolve_human_task",
  revise: "resolve_human_task",
};

function findFormalOffer(
  offers: CommandOffer[] | undefined,
  legacyCommand: string,
  nodeId: string | null,
): CommandOffer | null {
  if (!offers?.length) return null;
  const formalKind = LEGACY_TO_FORMAL_COMMAND[legacyCommand];
  if (!formalKind) return null;
  return (
    offers.find(
      (offer) =>
        offer.command === formalKind
        && offer.available
        && (offer.nodeId == null || offer.nodeId === nodeId),
    ) ?? null
  );
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
  resolveHuman: (
    taskId: string,
    decision: "accept" | "reject" | "revise",
  ) => Promise<WorkflowRunRecord>;
  refresh: () => Promise<void>;
  replaceParams: ReplaceParams;
}) {
  const {
    teamId,
    runId,
    selectedNodeId,
    run,
    nodeDetail,
    commandOffers,
    submitFormalOffer,
    createRun,
    resolveHuman,
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

  const resolveCurrentHumanTask = useCallback(
    async (decision: "accept" | "reject" | "revise") => {
      if (!selectedNodeId) {
        const reason = new Error("请先选择待处理的人工节点");
        setError(reason.message);
        throw reason;
      }
      const taskId = pendingTaskId(selectedNodeId);
      if (!taskId) {
        const reason = new Error("当前节点没有待处理的人工任务");
        setError(reason.message);
        throw reason;
      }
      setError(null);
      try {
        const updated = await resolveHuman(taskId, decision);
        const next = (updated.humanTasks ?? []).find(
          (task) => String(task.status) === "pending",
        );
        if (next?.nodeId) {
          replaceParams({ node: String(next.nodeId), panel: "node" });
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
        throw reason;
      }
    },
    [pendingTaskId, replaceParams, resolveHuman, selectedNodeId],
  );

  const runInspectorCommand = useCallback(
    async (command: string, payload?: Record<string, unknown>) => {
      if (command === "open_evidence_graph") {
        replaceParams({ panel: "evidence" });
        return;
      }
      if (command === "accept_handoff") {
        await resolveCurrentHumanTask("accept");
        return;
      }
      if (command === "reject_handoff") {
        await resolveCurrentHumanTask("reject");
        return;
      }
      if (command === "revise") {
        await resolveCurrentHumanTask("revise");
        return;
      }
      if (!run || !runId || !selectedNodeId) {
        const reason = new Error("当前没有可执行命令的运行节点");
        setError(reason.message);
        throw reason;
      }

      const formalOffer = findFormalOffer(commandOffers, command, selectedNodeId);
      if (formalOffer && submitFormalOffer) {
        setBusy(true);
        setError(null);
        try {
          const receipt = await submitFormalOffer({
            ...formalOffer,
            payload: { ...(formalOffer.payload ?? {}), ...(payload ?? {}) },
          });
          if (command === "fork_evidence_remediation") {
            const childRunIds = (receipt as { childRunIds?: unknown }).childRunIds;
            const childRunId = Array.isArray(childRunIds)
              ? childRunIds
                  .map((item) => String(item).trim())
                  .filter((item) => item && item !== runId)
                  .at(-1) ?? null
              : childRunIdFromCommandResult(
                  { command, message: "ok", raw: receipt as Record<string, unknown> },
                  runId,
                );
            if (!childRunId) {
              throw new Error("证据补救子运行已提交，但响应缺少 childRunIds，无法安全跳转");
            }
            replaceParams({ runId: childRunId, node: "source_extraction", panel: "node" });
            return;
          }
          await refresh();
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : String(reason));
          throw reason;
        } finally {
          setBusy(false);
        }
        return;
      }

      const capability = nodeDetail?.commands.find((item) => item.command === command);
      if (!capability) {
        const reason = new Error(`命令「${command}」后端未声明能力`);
        setError(reason.message);
        throw reason;
      }
      setBusy(true);
      setError(null);
      try {
        const result = await executeNodeCommand(
          {
            runId,
            nodeId: selectedNodeId,
            teamId,
            runVersion: run.runVersion,
            pendingHumanTaskId: pendingTaskId(selectedNodeId) || undefined,
          },
          {
            ...capability,
            payload: { ...(capability.payload ?? {}), ...(payload ?? {}) },
          },
        );
        if (command === "fork_evidence_remediation") {
          const childRunId = childRunIdFromCommandResult(result, runId);
          if (!childRunId) {
            throw new Error("证据补救子运行已提交，但响应缺少 childRunIds，无法安全跳转");
          }
          replaceParams({ runId: childRunId, node: "source_extraction", panel: "node" });
          return;
        }
        await refresh();
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
        throw reason;
      } finally {
        setBusy(false);
      }
    },
    [
      commandOffers,
      nodeDetail,
      pendingTaskId,
      refresh,
      replaceParams,
      resolveCurrentHumanTask,
      run,
      runId,
      selectedNodeId,
      submitFormalOffer,
      teamId,
    ],
  );

  return {
    error,
    busy,
    pendingTaskId,
    submitRun,
    runInspectorCommand,
  };
}
