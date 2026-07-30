/**
 * Agent Center config draft + core config write mutations.
 * Pure mappers / draft sync remain injectable from AgentsRoute until promoted.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  AgentConfigChanges,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentLlmSlotDefinition,
  AgentModelChoice,
} from "../../api/types";
import type { AgentConfigDraft } from "../AgentCoreConfigPanel";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";

type Notice = { tone: "success" | "error"; text: string };
type ChatCache = ReturnType<typeof createChatWorkspaceCache>;

export type AgentModelPromotionResult = {
  agent: AgentConfigWorkspaceAgent;
  modelRef: string;
  [key: string]: unknown;
};

export type UseAgentConfigDraftMutationsOptions = {
  lang: "zh" | "en";
  setNotice: Dispatch<SetStateAction<Notice | null>> | ((notice: Notice) => void);
  chatWorkspaceCache: ChatCache;
  setConfigDraft: Dispatch<SetStateAction<AgentConfigDraft>>;
  draftSyncSourceRef: MutableRefObject<unknown>;
  getWorkspace: () => AgentConfigWorkspace | undefined;
  draftFromAgent: (agent: AgentConfigWorkspaceAgent | null | undefined) => AgentConfigDraft;
  draftSyncSourceFromAgent: (
    workspace: AgentConfigWorkspace | undefined,
    agent: AgentConfigWorkspaceAgent | null | undefined,
  ) => unknown;
  normalizeAgentLlmBindings: (bindings: AgentConfigDraft["llmBindings"]) => AgentConfigDraft["llmBindings"];
  contextCompressionPolicyFromDraft: (draft: AgentConfigDraft["contextCompressionPolicy"]) => unknown;
  agentMetadataWithReasoningEffort: (
    draft: AgentConfigDraft,
    models: AgentModelChoice[] | null | undefined,
  ) => Record<string, unknown>;
  agentLabel: (agent: AgentConfigWorkspaceAgent | null | undefined) => string;
  updatedAgentWorkspaceCache: (
    current: AgentConfigWorkspace | undefined,
    agent: AgentConfigWorkspaceAgent,
  ) => AgentConfigWorkspace | undefined;
};

export function useAgentConfigDraftMutations(options: UseAgentConfigDraftMutationsOptions) {
  const queryClient = useQueryClient();

  const saveAgentConfigDraftMutation = useMutation({
    mutationFn: (payload: { agentId: string; baseUpdatedAt: string; snapshot: Record<string, unknown> }) =>
      fetchJson<NonNullable<AgentConfigChanges["activeDraft"]>>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/config-drafts`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            baseUpdatedAt: payload.baseUpdatedAt,
            snapshot: payload.snapshot,
            summary: options.lang === "zh" ? "来自 Agent Center 配置编辑器。" : "Saved from the Agent Center configuration editor.",
          }),
        },
      ),
    onSuccess: async (_, variables) => {
      options.setNotice({
        tone: "success",
        text: options.lang === "zh" ? "当前配置已保存为草稿，尚未影响运行。" : "The current configuration was saved as a draft and is not running yet.",
      });
      await queryClient.invalidateQueries({ queryKey: ["agents", "config-changes", variables.agentId] });
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : String(error);
      options.setNotice({
        tone: "error",
        text: message.includes("agent_draft_conflict")
          ? (options.lang === "zh" ? "草稿基线已过期，请刷新后重新保存。" : "The draft baseline is stale. Refresh before saving again.")
          : message,
      });
    },
  });

  const discardAgentConfigDraftMutation = useMutation({
    mutationFn: (payload: { agentId: string; draftId: string }) =>
      fetchJson<{ draftId: string; status: string }>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/config-drafts/${encodeURIComponent(payload.draftId)}`,
        { method: "DELETE" },
      ),
    onSuccess: async (_, variables) => {
      options.setNotice({
        tone: "success",
        text: options.lang === "zh" ? "草稿已放弃，发布记录保留不变。" : "Draft discarded; published revisions remain unchanged.",
      });
      await queryClient.invalidateQueries({ queryKey: ["agents", "config-changes", variables.agentId] });
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateAgentMutation = useMutation({
    mutationFn: (payload: {
      agentId: string;
      agent: AgentConfigWorkspaceAgent;
      draft: AgentConfigDraft;
      modelChoices: AgentModelChoice[];
      sourceDraftId: string;
    }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          displayName: payload.draft.displayName,
          llmBindings: options.normalizeAgentLlmBindings(payload.draft.llmBindings),
          promptTemplateId: payload.draft.promptTemplateId,
          toolPolicyId: payload.draft.toolPolicyId,
          memoryPolicyId: payload.draft.memoryPolicyId,
          permissionPreset: payload.draft.permissionPreset,
          contextCompressionPolicy: options.contextCompressionPolicyFromDraft(payload.draft.contextCompressionPolicy),
          metadata: options.agentMetadataWithReasoningEffort(payload.draft, payload.modelChoices),
          status: payload.draft.status,
          expectedUpdatedAt: payload.agent.updatedAt,
          expectedConfigRevision: payload.agent.configRevision,
          sourceDraftId: payload.sourceDraftId,
        }),
      }),
    onSuccess: (agent, variables) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.updatedAgentWorkspaceCache(current, agent),
      );
      options.setNotice({
        tone: "success",
        text: options.lang === "zh"
          ? `已保存 ${options.agentLabel(agent)} 的 Agent 配置`
          : `Saved config for ${options.agentLabel(agent)}`,
      });
      void queryClient.invalidateQueries({ queryKey: ["agents", "config-changes", variables.agentId] });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : String(error);
      options.setNotice({
        tone: "error",
        text: message.includes("agent_update_conflict")
          ? (options.lang === "zh" ? "配置已被其他编辑更新，请刷新后再保存。" : "Configuration changed elsewhere. Refresh before saving again.")
          : message,
      });
    },
  });

  const promoteAgentModelMutation = useMutation({
    mutationFn: (payload: {
      agent: AgentConfigWorkspaceAgent;
      slot: AgentLlmSlotDefinition;
      candidate: AgentModelChoice;
      expectedBaseHash: string;
    }) =>
      fetchJson<AgentModelPromotionResult>(
        `/api/agents/${encodeURIComponent(payload.agent.agentId)}/llm-bindings/${encodeURIComponent(payload.slot.slot)}/promote`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            modelRef: payload.candidate.modelRef,
            expectedBaseHash: payload.expectedBaseHash,
            expectedAgentUpdatedAt: payload.agent.updatedAt,
            confirmed: true,
          }),
        },
      ),
    onSuccess: async (result) => {
      options.setConfigDraft(options.draftFromAgent(result.agent));
      options.draftSyncSourceRef.current = options.draftSyncSourceFromAgent(options.getWorkspace(), result.agent);
      options.setNotice({
        tone: "success",
        text: options.lang === "zh"
          ? `已固定 ${result.modelRef} 并绑定到当前 Agent`
          : `Pinned ${result.modelRef} and bound it to this Agent`,
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.agentSummary(true) }),
      ]);
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  return {
    saveAgentConfigDraftMutation,
    discardAgentConfigDraftMutation,
    updateAgentMutation,
    promoteAgentModelMutation,
  };
}
