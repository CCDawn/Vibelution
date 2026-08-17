/**
 * Agent Center config draft + core config write mutations.
 * Pure mappers / draft sync remain injectable from AgentsRoute until promoted.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import {
  discardAgentConfigDraft,
  promoteAgentModel,
  saveAgentConfigDraft,
  updateAgent,
} from "../../api/agents";
import { startUserAction } from "../../app/userActionTelemetry";
import { queryKeys } from "../../api/queryKeys";
import type {
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
  /** When false, omit contextCompressionPolicy so untouched compression is not a fake edit. */
  contextCompressionPolicyChangedInDraft?: (
    draft: AgentConfigDraft,
    agent: AgentConfigWorkspaceAgent | null | undefined,
  ) => boolean;
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
      saveAgentConfigDraft(payload.agentId, {
        baseUpdatedAt: payload.baseUpdatedAt,
        snapshot: payload.snapshot,
        summary: options.lang === "zh" ? "来自 Agent Center 配置编辑器。" : "Saved from the Agent Center configuration editor.",
      }),
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
      discardAgentConfigDraft(payload.agentId, payload.draftId),
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
      updateAgent(payload.agentId, (() => {
          // Full-form save used to always send compression; inherit mode then failed even when
          // the user only changed unrelated fields. Only patch compression when the form differs.
          const body: Record<string, unknown> = {
            displayName: payload.draft.displayName,
            llmBindings: options.normalizeAgentLlmBindings(payload.draft.llmBindings),
            promptTemplateId: payload.draft.promptTemplateId,
            toolPolicyId: payload.draft.toolPolicyId,
            memoryPolicyId: payload.draft.memoryPolicyId,
            permissionPreset: payload.draft.permissionPreset,
            metadata: options.agentMetadataWithReasoningEffort(payload.draft, payload.modelChoices),
            status: payload.draft.status,
            expectedUpdatedAt: payload.agent.updatedAt,
            expectedConfigRevision: payload.agent.configRevision,
            sourceDraftId: payload.sourceDraftId,
          };
          const compressionChanged = options.contextCompressionPolicyChangedInDraft
            ? options.contextCompressionPolicyChangedInDraft(payload.draft, payload.agent)
            : true;
          if (compressionChanged) {
            body.contextCompressionPolicy = options.contextCompressionPolicyFromDraft(
              payload.draft.contextCompressionPolicy,
            );
          }
          return body;
        })()),
    onMutate: (variables) => ({
      telemetry: startUserAction("agent_update", { agentId: variables.agentId }),
    }),
    onSuccess: (agent, variables, context) => {
      context?.telemetry?.succeeded({ agentId: agent.agentId });
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
      // Config PATCH already setQueryData'd the workspace agent — do not thrash chat sessions.
      void options.chatWorkspaceCache.afterAgentConfigSaved(variables.agentId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { agentId: variables.agentId });
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
      promoteAgentModel<AgentModelPromotionResult>(
        payload.agent.agentId,
        payload.slot.slot,
        {
          modelRef: payload.candidate.modelRef,
          expectedBaseHash: payload.expectedBaseHash,
          expectedAgentUpdatedAt: payload.agent.updatedAt,
          confirmed: true,
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
      void options.chatWorkspaceCache.afterAgentConfigSaved(result.agent.agentId);
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
