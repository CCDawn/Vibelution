import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  cancelAgentPerceptionRun,
  fetchAgentPerceptionConfiguration,
  fetchAgentPerceptionRuntime,
  saveAgentPerceptionConfiguration,
} from "../api/agentPerception";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { AgentPerceptionPanel } from "./agentPerception/AgentPerceptionPanel";
import { agentPerceptionQueryKeys } from "./agentPerception/queryKeys";
import type { AgentPerceptionPolicy } from "./agentPerception/types";
import type { AgentPerceptionDraftStore } from "./agentPerception/useAgentPerceptionDraft";

type SaveVariables = {
  agentId: string;
  policy: AgentPerceptionPolicy;
  expectedAgentUpdatedAt: string;
};

type CancelVariables = {
  agentId: string;
  runId: string;
};

function errorMessage(error: unknown, lang: "zh" | "en") {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return lang === "zh" ? "请求失败，请重试。" : "The request failed. Please retry.";
}

export function AgentPerceptionPane({
  agentId,
  lang,
  onOpenSession,
  draftStore,
}: {
  agentId: string;
  lang: "zh" | "en";
  onOpenSession: (sessionId: string) => void;
  draftStore?: AgentPerceptionDraftStore;
}) {
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const configurationQuery = useQuery({
    queryKey: agentPerceptionQueryKeys.configuration(agentId),
    queryFn: ({ signal }) => fetchAgentPerceptionConfiguration(agentId, { signal }),
    enabled: Boolean(agentId),
    retry: false,
  });
  const runtimeQuery = useQuery({
    queryKey: agentPerceptionQueryKeys.runtime(agentId),
    queryFn: ({ signal }) => fetchAgentPerceptionRuntime(agentId, { signal }),
    enabled: Boolean(agentId),
    refetchInterval: resolvePollingInterval(pageVisible, 10_000),
    refetchIntervalInBackground: false,
    retry: false,
  });
  const saveMutation = useMutation({
    mutationFn: ({ agentId: targetAgentId, policy, expectedAgentUpdatedAt }: SaveVariables) =>
      saveAgentPerceptionConfiguration(targetAgentId, policy, expectedAgentUpdatedAt),
    onSuccess: async (configuration, variables) => {
      if (configuration.agentId === variables.agentId) {
        queryClient.setQueryData(agentPerceptionQueryKeys.configuration(variables.agentId), configuration);
      } else {
        // A mismatched response must never replace another Agent's cached configuration.
        await queryClient.invalidateQueries({ queryKey: agentPerceptionQueryKeys.configuration(variables.agentId) });
      }
      await queryClient.invalidateQueries({ queryKey: agentPerceptionQueryKeys.runtime(variables.agentId) });
    },
    onError: async (_error, variables) => {
      // A failed compare-and-swap may mean another writer advanced the policy.
      // Refresh the authoritative revision before allowing another save.
      await queryClient.invalidateQueries({ queryKey: agentPerceptionQueryKeys.configuration(variables.agentId) });
    },
  });
  const cancelMutation = useMutation({
    mutationFn: ({ agentId: targetAgentId, runId }: CancelVariables) => cancelAgentPerceptionRun(targetAgentId, runId),
    onSuccess: async (_result, variables) => {
      await queryClient.invalidateQueries({ queryKey: agentPerceptionQueryKeys.runtime(variables.agentId) });
    },
  });
  const saveBelongsToAgent = saveMutation.variables?.agentId === agentId;
  const cancelBelongsToAgent = cancelMutation.variables?.agentId === agentId;

  return (
    <AgentPerceptionPanel
      agentId={agentId}
      lang={lang}
      configuration={configurationQuery.data ?? null}
      configurationPending={configurationQuery.isPending}
      configurationError={configurationQuery.isError ? errorMessage(configurationQuery.error, lang) : null}
      onRetryConfiguration={() => { void configurationQuery.refetch(); }}
      runtime={runtimeQuery.data ?? null}
      runtimePending={runtimeQuery.isPending}
      runtimeError={runtimeQuery.isError ? errorMessage(runtimeQuery.error, lang) : null}
      onRetryRuntime={() => { void runtimeQuery.refetch(); }}
      savePending={saveMutation.isPending && saveBelongsToAgent}
      saveError={saveMutation.isError && saveBelongsToAgent ? errorMessage(saveMutation.error, lang) : null}
      onSave={(policy, expectedAgentUpdatedAt) => saveMutation.mutate({ agentId, policy, expectedAgentUpdatedAt })}
      onOpenSession={onOpenSession}
      draftStore={draftStore}
      cancelPending={cancelMutation.isPending && cancelBelongsToAgent}
      cancelError={cancelMutation.isError && cancelBelongsToAgent ? errorMessage(cancelMutation.error, lang) : null}
      onCancelRun={(runId) => cancelMutation.mutate({ agentId, runId })}
    />
  );
}
