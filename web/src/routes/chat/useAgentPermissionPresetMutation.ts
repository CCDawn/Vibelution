import { useMutation, useQueryClient } from "@tanstack/react-query";

import { updateAgentPermissionPreset } from "../../api/agents";
import { queryKeys } from "../../api/queryKeys";
import type {
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentInstance,
  AgentPermissionPreset,
} from "../../api/types";
import { updatedAgentWorkspaceCache } from "../agentWorkspaceCache";

export type UpdateAgentPermissionPresetInput = {
  agentId: string;
  sessionId: string;
  permissionPreset: AgentPermissionPreset;
  expectedConfigRevision: number;
};

type UseAgentPermissionPresetMutationOptions = {
  onSuccess?: (agent: AgentConfigWorkspaceAgent, input: UpdateAgentPermissionPresetInput) => void;
  onError?: (error: unknown, input: UpdateAgentPermissionPresetInput) => void;
};

export function useAgentPermissionPresetMutation(
  options: UseAgentPermissionPresetMutationOptions = {},
) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: UpdateAgentPermissionPresetInput) =>
      updateAgentPermissionPreset(payload),
    onSuccess: (agent, input) => {
      queryClient.setQueryData<AgentInstance[] | undefined>(
        queryKeys.agents(),
        (current) => current?.map((item) => item.agentId === agent.agentId ? agent : item),
      );
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => updatedAgentWorkspaceCache(current, agent),
      );
      queryClient.setQueryData(queryKeys.agent(agent.agentId), agent);
      options.onSuccess?.(agent, input);
    },
    onError: (error, input) => {
      options.onError?.(error, input);
    },
  });
}
