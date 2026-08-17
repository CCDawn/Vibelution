import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  fetchAgentConfigWorkspace,
  promoteAgentModel,
  updateAgent,
} from "../../../api/agents";
import { putResearchWorkflowAgentBindings } from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
import type { AgentConfigWorkspaceAgent, AgentModelChoice } from "../../../api/types";
import { CHALLENGE_CUP_WORKFLOW_ID, type EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import {
  FALLBACK_AGENT_LLM_SLOTS,
  agentLlmSlots,
  updateAgentLlmSlotBinding,
} from "../../agents/agentRouteLlmModel";
import { agentDisplayInitial, mergeNodeOverrideLayer } from "./nodeInspectorOpsModel";

export function useNodeInspectorOpsResources(agentId: string) {
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const workspaceQuery = useQuery({
    queryKey: queryKeys.agentConfigWorkspace(),
    queryFn: () => fetchAgentConfigWorkspace({ includeRuntime: false }),
    staleTime: 60_000,
  });
  const workspace = workspaceQuery.data;
  const agent = (workspace?.agents ?? []).find((item) => item.agentId === agentId) ?? null;
  const dialogueSlot = agentLlmSlots(workspace).find((slot) => slot.slot === "dialogue")
    ?? FALLBACK_AGENT_LLM_SLOTS[0];

  const updateModel = useMutation({
    mutationFn: async (payload: { kind: "pinned"; modelRef: string } | { kind: "promote"; candidate: AgentModelChoice }) => {
      if (!agent) {
        throw new Error("尚未指定 Agent");
      }
      if (payload.kind === "pinned") {
        return updateAgent(agent.agentId, {
          llmBindings: updateAgentLlmSlotBinding(agent.llmBindings, dialogueSlot, payload.modelRef),
          expectedUpdatedAt: agent.updatedAt,
          expectedConfigRevision: agent.configRevision,
        });
      }
      return promoteAgentModel(agent.agentId, "dialogue", {
        modelRef: payload.candidate.modelRef,
        expectedBaseHash: workspace?.operatorConfigHash ?? "",
        expectedAgentUpdatedAt: agent.updatedAt,
        confirmed: true,
      }).then((result) => result.agent);
    },
    onSuccess: async () => {
      setNotice(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    },
    onError: (error) => {
      setNotice(error instanceof Error ? error.message : String(error));
    },
  });

  const bindAgent = useMutation({
    mutationFn: async (payload: {
      teamId: string;
      nodeId: string;
      agentId: string;
      bindings: EffectiveAgentBinding[] | null;
    }) => putResearchWorkflowAgentBindings(CHALLENGE_CUP_WORKFLOW_ID, {
      teamId: payload.teamId,
      nodeOverrides: mergeNodeOverrideLayer(payload.bindings, payload.nodeId, payload.agentId),
    }),
    onSuccess: async (_result, variables) => {
      setNotice(null);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.researchWorkflowBindings(CHALLENGE_CUP_WORKFLOW_ID, variables.teamId),
      });
    },
    onError: (error) => {
      setNotice(error instanceof Error ? error.message : String(error));
    },
  });

  return {
    workspace,
    agent,
    dialogueModel: agent?.dialogueModel ?? null,
    candidates: workspace?.agentModelChoices ?? [],
    pendingModelRef: updateModel.isPending
      ? (updateModel.variables?.kind === "promote"
        ? updateModel.variables.candidate.modelRef
        : updateModel.variables?.modelRef ?? "")
      : "",
    modelPending: updateModel.isPending || bindAgent.isPending,
    notice,
    bindAgent: (input: {
      teamId: string;
      nodeId: string;
      agentId: string;
      bindings: EffectiveAgentBinding[] | null;
    }) => bindAgent.mutate(input),
    selectPinned: (modelRef: string) => updateModel.mutate({ kind: "pinned", modelRef }),
    promote: (candidate: AgentModelChoice) => updateModel.mutate({ kind: "promote", candidate }),
  };
}

export function inspectorAgentOptions(agents: AgentConfigWorkspaceAgent[] | undefined) {
  return (agents ?? [])
    .filter((item) => item.status !== "archived")
    .map((item) => ({
      id: item.agentId,
      name: item.displayName || item.agentId,
      initial: agentDisplayInitial(item.displayName || item.agentId),
    }));
}
