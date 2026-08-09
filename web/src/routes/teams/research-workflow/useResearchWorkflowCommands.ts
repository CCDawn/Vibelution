import { useCallback, useState } from "react";

import type {
  CreateResearchWorkflowRunInput,
  WorkflowRunRecord,
} from "../../../api/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";
import { executeNodeCommand } from "./nodeCommandAdapter";

type ReplaceParams = (patch: Record<string, string | null | undefined>) => void;

export function useResearchWorkflowCommands(options: {
  teamId: string;
  runId: string;
  selectedNodeId: string | null;
  run: WorkflowRunRecord | null;
  nodeDetail: ResearchWorkflowNodeDetail | null;
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
        setError("请先选择待处理的人工节点");
        return;
      }
      const taskId = pendingTaskId(selectedNodeId);
      if (!taskId) {
        setError("当前节点没有待处理的人工任务");
        return;
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
      }
    },
    [pendingTaskId, replaceParams, resolveHuman, selectedNodeId],
  );

  const runInspectorCommand = useCallback(
    (command: string) => {
      if (command === "open_evidence_graph") {
        replaceParams({ panel: "evidence" });
        return;
      }
      if (command === "accept_handoff") {
        void resolveCurrentHumanTask("accept");
        return;
      }
      if (command === "reject_handoff") {
        void resolveCurrentHumanTask("reject");
        return;
      }
      if (command === "revise") {
        void resolveCurrentHumanTask("revise");
        return;
      }
      if (!run || !runId || !selectedNodeId) {
        setError("当前没有可执行命令的运行节点");
        return;
      }
      const capability = nodeDetail?.commands.find((item) => item.command === command);
      if (!capability) {
        setError(`命令「${command}」后端未声明能力`);
        return;
      }
      setBusy(true);
      setError(null);
      executeNodeCommand(
        {
          runId,
          nodeId: selectedNodeId,
          teamId,
          runVersion: run.runVersion,
          pendingHumanTaskId: pendingTaskId(selectedNodeId) || undefined,
        },
        capability,
      )
        .then(() => refresh())
        .catch((reason: unknown) => {
          setError(reason instanceof Error ? reason.message : String(reason));
        })
        .finally(() => setBusy(false));
    },
    [nodeDetail, pendingTaskId, refresh, replaceParams, resolveCurrentHumanTask, run, runId, selectedNodeId, teamId],
  );

  return {
    error,
    busy,
    pendingTaskId,
    submitRun,
    runInspectorCommand,
  };
}
