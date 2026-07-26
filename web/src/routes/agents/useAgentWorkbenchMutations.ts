/**
 * Remaining Agent Center write mutations (profile/lifecycle/policy/inbox).
 * Config-draft cluster lives in useAgentConfigDraftMutations.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  AgentAvatarUploadResponse,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentDelegationPolicy,
  AgentInboxMessage,
  AgentModeBindings,
  AgentPurgeResponse,
  AgentSupervisionPolicy,
  AgentToolGovernanceRequest,
  MemoryPolicy,
  ToolPolicy,
} from "../../api/types";
import type { AgentModeMembershipDraft } from "../AgentModeMembershipPanel";
import type { AgentMemoryPolicyDraft } from "../AgentMemoryPolicyPanel";
import type { AgentResetOptions } from "../AgentDebugResetPanel";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";

type Notice = { tone: "success" | "error"; text: string };
type ChatCache = ReturnType<typeof createChatWorkspaceCache>;
type AgentResetSummary = {
  resetDirectSession?: boolean;
  previousDirectSessionId?: unknown;
  replacementDirectSessionId?: unknown;
  [key: string]: unknown;
};

export type UseAgentWorkbenchMutationsOptions = {
  lang: "zh" | "en";
  copy: any;
  setNotice: Dispatch<SetStateAction<Notice | null>> | ((notice: Notice) => void);
  chatWorkspaceCache: ChatCache;
  setPersonaDraft: Dispatch<SetStateAction<any>>;
  setTaskDraft: Dispatch<SetStateAction<any>>;
  draftSyncSourceRef: MutableRefObject<unknown>;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setActivePane: Dispatch<SetStateAction<any>>;
  setResettingAgentIds: Dispatch<SetStateAction<Set<string>>>;
  setResetOptions: Dispatch<SetStateAction<AgentResetOptions>>;
  setMembershipDraft: Dispatch<SetStateAction<AgentModeMembershipDraft>>;
  setToolGovernanceDraft: Dispatch<SetStateAction<any>>;
  getWorkspace: () => AgentConfigWorkspace | undefined;
  getSelectedAgentId: () => string;
  getActivePane: () => string;
  getSelectedAgent: () => AgentConfigWorkspaceAgent | null | undefined;
  reconcileResetDirectSession: (summary: AgentResetSummary) => void;
  encodeArrayBufferBase64: (buffer: ArrayBuffer) => string;
  updatedAgentWorkspaceCache: (current: AgentConfigWorkspace | undefined, agent: AgentConfigWorkspaceAgent) => AgentConfigWorkspace | undefined;
  archivedWorkspaceCache: (current: AgentConfigWorkspace | undefined, agent: AgentConfigWorkspaceAgent) => AgentConfigWorkspace | undefined;
  purgedWorkspaceCache: (current: AgentConfigWorkspace | undefined, agentId: string) => AgentConfigWorkspace | undefined;
  optimisticArchivedAgent: (agent: AgentConfigWorkspaceAgent) => AgentConfigWorkspaceAgent;
  personaProfileFromDraft: (draft: any) => unknown;
  personaDraftFromAgent: (agent: AgentConfigWorkspaceAgent | null | undefined) => any;
  taskProfileFromDraft: (draft: any) => unknown;
  taskDraftFromAgent: (agent: AgentConfigWorkspaceAgent | null | undefined) => any;
  draftSyncSourceFromAgent: (workspace: AgentConfigWorkspace | undefined, agent: AgentConfigWorkspaceAgent | null | undefined) => unknown;
  agentLabel: (agent: AgentConfigWorkspaceAgent | null | undefined) => string;
  defaultToolPolicy: (policyId?: string) => ToolPolicy;
  defaultMemoryPolicy: (policyId?: string) => MemoryPolicy;
  sortedIds: (values: string[]) => string[];
  toolPolicyDeltaFromDraft: (draft: any, agent: AgentConfigWorkspaceAgent | null | undefined) => any;
  toolGovernanceDraftFromAgent: (agent: AgentConfigWorkspaceAgent | null | undefined) => any;
  governanceStatusLabel: (status: string, lang: "zh" | "en") => string;
  DEFAULT_AGENT_RESET_OPTIONS: AgentResetOptions;
  stringValue: (value: unknown) => string;
};

export function useAgentWorkbenchMutations(options: UseAgentWorkbenchMutationsOptions) {
  const queryClient = useQueryClient();

  const updatePersonaMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: any }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          personaProfile: options.personaProfileFromDraft(payload.draft),
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.updatedAgentWorkspaceCache(current, agent),
      );
      options.setPersonaDraft(options.personaDraftFromAgent(agent));
      options.draftSyncSourceRef.current = options.draftSyncSourceFromAgent(options.getWorkspace(), agent);
      options.setNotice({ tone: "success", text: options.copy.personaUpdateSuccess });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateTaskMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: any }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          taskProfile: options.taskProfileFromDraft(payload.draft),
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.updatedAgentWorkspaceCache(current, agent),
      );
      options.setTaskDraft(options.taskDraftFromAgent(agent));
      options.draftSyncSourceRef.current = options.draftSyncSourceFromAgent(options.getWorkspace(), agent);
      options.setNotice({ tone: "success", text: options.copy.taskUpdateSuccess });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const archiveAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "DELETE",
      }),
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      const previousWorkspace = queryClient.getQueryData<AgentConfigWorkspace>(queryKeys.agentConfigWorkspace());
      const previousSelectedAgentId = options.getSelectedAgentId();
      const previousActivePane = options.getActivePane();
      const optimisticAgent = previousWorkspace?.agents.find((agent) => agent.agentId === payload.agentId) ?? options.getSelectedAgent();
      if (optimisticAgent) {
        queryClient.setQueryData<AgentConfigWorkspace | undefined>(
          queryKeys.agentConfigWorkspace(),
          (current) => options.archivedWorkspaceCache(current, options.optimisticArchivedAgent(optimisticAgent)),
        );
      }
      options.setSelectedAgentId("");
      options.setActivePane("overview");
      return { previousWorkspace, previousSelectedAgentId, previousActivePane };
    },
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.archivedWorkspaceCache(current, agent),
      );
      options.setSelectedAgentId("");
      options.setActivePane("overview");
      options.setNotice({
        tone: "success",
        text: options.lang === "zh" ? `已安全归档 ${options.agentLabel(agent)}` : `Archived ${options.agentLabel(agent)}`,
      });
      void options.chatWorkspaceCache.afterAgentArchived();
    },
    onError: (error, _variables, context) => {
      if (context?.previousWorkspace) {
        queryClient.setQueryData(queryKeys.agentConfigWorkspace(), context.previousWorkspace);
      }
      options.setSelectedAgentId(context?.previousSelectedAgentId ?? "");
      options.setActivePane(context?.previousActivePane ?? "overview");
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
      void options.chatWorkspaceCache.afterAgentArchived();
    },
  });

  const purgeAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string }) =>
      fetchJson<AgentPurgeResponse>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/purge`,
        { method: "DELETE" },
      ),
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      const previousWorkspace = queryClient.getQueryData<AgentConfigWorkspace>(queryKeys.agentConfigWorkspace());
      const previousSelectedAgentId = options.getSelectedAgentId();
      const previousActivePane = options.getActivePane();
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.purgedWorkspaceCache(current, payload.agentId),
      );
      options.setSelectedAgentId("");
      options.setActivePane("overview");
      return { previousWorkspace, previousSelectedAgentId, previousActivePane };
    },
    onSuccess: (result) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.purgedWorkspaceCache(current, result.agentId),
      );
      options.setSelectedAgentId("");
      options.setActivePane("overview");
      options.setNotice({
        tone: "success",
        text: result.purgeSummary.sessions.cleanupPending
          ? (options.lang === "zh"
            ? "Agent 与绑定会话已删除；部分私有文件因系统占用等待后续清理"
            : "The Agent and bound sessions were deleted; some private files remain pending cleanup because they are in use")
          : (options.lang === "zh" ? "已彻底删除归档 Agent" : "Permanently deleted archived Agent"),
      });
      void options.chatWorkspaceCache.afterAgentArchived();
    },
    onError: (error, _variables, context) => {
      if (context?.previousWorkspace) {
        queryClient.setQueryData(queryKeys.agentConfigWorkspace(), context.previousWorkspace);
      }
      options.setSelectedAgentId(context?.previousSelectedAgentId ?? "");
      options.setActivePane(context?.previousActivePane ?? "overview");
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
      void options.chatWorkspaceCache.afterAgentArchived();
    },
  });

  const resetAgentMutation = useMutation({
    mutationFn: (payload: { agentId: string; options: AgentResetOptions }) =>
      fetchJson<{ agent: AgentConfigWorkspaceAgent; resetSummary: AgentResetSummary }>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/reset`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload.options),
        },
      ),
    onMutate: (payload) => {
      options.setResettingAgentIds((current) => {
        const next = new Set(current);
        next.add(payload.agentId);
        return next;
      });
    },
    onSuccess: (result) => {
      const agent = result.agent;
      const previousDirectSessionId = options.stringValue(result.resetSummary.previousDirectSessionId);
      options.reconcileResetDirectSession(result.resetSummary);
      options.setNotice({ tone: "success", text: options.copy.resetAgentSuccess });
      options.setResetOptions(options.DEFAULT_AGENT_RESET_OPTIONS);
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
      if (result.resetSummary.resetDirectSession) {
        if (previousDirectSessionId) {
          queryClient.removeQueries({ queryKey: queryKeys.session(previousDirectSessionId), exact: true });
        }
        void options.chatWorkspaceCache.afterChatWorkspaceReset();
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentRuns(agent.agentId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentMessages(agent.agentId, "pending") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentRuntimeEvidence(agent.agentId) });
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
    onSettled: (_result, _error, payload) => {
      options.setResettingAgentIds((current) => {
        const next = new Set(current);
        next.delete(payload.agentId);
        return next;
      });
    },
  });

  const updateAvatarMutation = useMutation({
    mutationFn: (payload: { agentId: string; avatarImagePath?: string; resetToDefault?: boolean }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}/avatar`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          avatarImagePath: payload.avatarImagePath ?? "",
          resetToDefault: Boolean(payload.resetToDefault),
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.updatedAgentWorkspaceCache(current, agent),
      );
      options.setNotice({ tone: "success", text: options.copy.avatarUpdateSuccess });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const uploadAvatarMutation = useMutation({
    mutationFn: async (payload: { agentId: string; file: File }) =>
      fetchJson<AgentAvatarUploadResponse>(`/api/agents/${encodeURIComponent(payload.agentId)}/avatar-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: payload.file.name,
          contentType: payload.file.type || "image/png",
          dataBase64: options.encodeArrayBufferBase64(await payload.file.arrayBuffer()),
        }),
      }),
    onSuccess: (result) => {
      const agent = result.agent as AgentConfigWorkspaceAgent;
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.updatedAgentWorkspaceCache(current, agent),
      );
      options.setNotice({ tone: "success", text: options.copy.avatarUpdateSuccess });
      void queryClient.invalidateQueries({ queryKey: ["agent-avatar-options"] });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateMembershipMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentModeMembershipDraft }) =>
      fetchJson<AgentModeBindings>(`/api/agents/${encodeURIComponent(payload.agentId)}/mode-membership`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload.draft),
      }),
    onSuccess: (payload, variables) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => current
          ? {
              ...current,
              modeBindings: payload.modes ?? current.modeBindings,
            }
          : current,
      );
      options.setMembershipDraft(variables.draft);
      options.setNotice({
        tone: "success",
        text: options.lang === "zh" ? "已保存 Agent 使用位置" : "Saved Agent mode membership",
      });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateToolPolicyMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: any; basePolicy: ToolPolicy | undefined }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          toolPolicy: {
            ...options.defaultToolPolicy(payload.basePolicy?.policyId || "default"),
            ...(payload.basePolicy ?? {}),
            allowedTools: options.sortedIds(payload.draft.allowedTools),
            preferredTools: options.sortedIds(payload.draft.preferredTools),
            blockedTools: options.sortedIds(payload.draft.blockedTools),
            readScopes: options.sortedIds(payload.draft.readScopes),
            writeScopes: options.sortedIds(payload.draft.writeScopes),
          },
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.updatedAgentWorkspaceCache(current, agent),
      );
      options.setNotice({
        tone: "success",
        text: options.lang === "zh" ? `已保存 ${options.agentLabel(agent)} 的工具能力` : `Saved tool permissions for ${options.agentLabel(agent)}`,
      });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const createToolGovernanceMutation = useMutation({
    mutationFn: (payload: {
      agentId: string;
      draft: any;
      delta: any;
    }) =>
      fetchJson<AgentToolGovernanceRequest>(`/api/agents/${encodeURIComponent(payload.agentId)}/tool-governance-requests`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          proposedByAgentId: payload.draft.proposedByAgentId,
          grantTools: options.sortedIds(payload.delta.grantTools),
          revokeTools: options.sortedIds(payload.delta.revokeTools),
          blockTools: options.sortedIds(payload.delta.blockTools),
          unblockTools: options.sortedIds(payload.delta.unblockTools),
          reason: payload.draft.reason,
          applyMode: payload.draft.applyMode,
        }),
      }),
    onSuccess: (request) => {
      options.setNotice({
        tone: "success",
        text: `${options.copy.toolGovernanceSuccess}: ${options.governanceStatusLabel(request.status, options.lang)}`,
      });
      options.setToolGovernanceDraft(options.toolGovernanceDraftFromAgent(options.getSelectedAgent()));
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const resolveToolGovernanceMutation = useMutation({
    mutationFn: (payload: { agentId: string; requestId: string; decision: "approve" | "reject" }) =>
      fetchJson<AgentToolGovernanceRequest>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/tool-governance-requests/${encodeURIComponent(payload.requestId)}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision: payload.decision,
            resolvedBy: "user",
            resolutionNote: payload.decision,
          }),
        },
      ),
    onSuccess: () => {
      options.setNotice({ tone: "success", text: options.copy.toolGovernanceResolved });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateMemoryPolicyMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentMemoryPolicyDraft; basePolicy: MemoryPolicy | undefined }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          memoryPolicy: {
            ...options.defaultMemoryPolicy(payload.basePolicy?.policyId || ""),
            ...(payload.basePolicy ?? {}),
            readSharedGroups: options.sortedIds(payload.draft.readSharedGroups),
            writeSharedGroups: options.sortedIds(payload.draft.writeSharedGroups),
            readKnowledgeBaseIds: options.sortedIds(payload.draft.readKnowledgeBaseIds),
            proposeKnowledgeBaseIds: options.sortedIds(payload.draft.proposeKnowledgeBaseIds),
            reviewKnowledgeBaseIds: options.sortedIds(payload.draft.reviewKnowledgeBaseIds),
            rateKnowledgeBaseIds: options.sortedIds(payload.draft.rateKnowledgeBaseIds),
          },
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.updatedAgentWorkspaceCache(current, agent),
      );
      options.setNotice({
        tone: "success",
        text: options.lang === "zh" ? `已保存 ${options.agentLabel(agent)} 的记忆设置` : `Saved memory policy for ${options.agentLabel(agent)}`,
      });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const updateRuntimePolicyMutation = useMutation({
    mutationFn: (payload: {
      agentId: string;
      delegationPolicy: AgentDelegationPolicy;
      supervisionPolicy: AgentSupervisionPolicy;
    }) =>
      fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          delegationPolicy: {
            allowSubagents: payload.delegationPolicy.allowSubagents,
            maxConcurrent: payload.delegationPolicy.maxConcurrent,
            maxDepth: payload.delegationPolicy.maxDepth,
            allowWakeMessages: payload.delegationPolicy.allowWakeMessages,
            allowedContextModes: options.sortedIds(payload.delegationPolicy.allowedContextModes),
          },
          supervisionPolicy: {
            supervisionEnabled: payload.supervisionPolicy.supervisionEnabled,
            requiresReview: payload.supervisionPolicy.requiresReview,
            reviewMode: payload.supervisionPolicy.reviewMode,
            evidenceLevel: payload.supervisionPolicy.evidenceLevel,
          },
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentConfigWorkspace | undefined>(
        queryKeys.agentConfigWorkspace(),
        (current) => options.updatedAgentWorkspaceCache(current, agent),
      );
      options.setNotice({
        tone: "success",
        text: options.lang === "zh" ? `已保存 ${options.agentLabel(agent)} 的运行策略` : `Saved runtime policy for ${options.agentLabel(agent)}`,
      });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentRuns(agent.agentId) });
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const consumeMessageMutation = useMutation({
    mutationFn: (payload: { agentId: string; messageId: string; sessionId: string }) =>
      fetchJson<AgentInboxMessage>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/messages/${encodeURIComponent(payload.messageId)}/consume`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            consumedBySessionId: payload.sessionId,
            consumedByTurnId: "agent-center",
          }),
        },
      ),
    onSuccess: (_message, variables) => {
      options.setNotice({
        tone: "success",
        text: options.lang === "zh" ? "已标记消息为已处理" : "Marked message as consumed",
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentMessages(variables.agentId, "pending") });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const consumeAllMessagesMutation = useMutation({
    mutationFn: (payload: { agentId: string; sessionId: string }) =>
      fetchJson<{ agentId: string; consumed: boolean; consumedCount: number; remainingPendingCount: number }>(
        `/api/agents/${encodeURIComponent(payload.agentId)}/messages/consume-all`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            consumedBySessionId: payload.sessionId,
            consumedByTurnId: "agent-center",
          }),
        },
      ),
    onSuccess: (result, variables) => {
      options.setNotice({
        tone: "success",
        text: options.lang === "zh" ? `已处理 ${result.consumedCount} 条 Inbox 消息` : `Consumed ${result.consumedCount} inbox messages`,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentMessages(result.agentId || variables.agentId, "pending") });
      void options.chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error) => {
      options.setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  return {
    updatePersonaMutation,
    updateTaskMutation,
    archiveAgentMutation,
    purgeAgentMutation,
    resetAgentMutation,
    updateAvatarMutation,
    uploadAvatarMutation,
    updateMembershipMutation,
    updateToolPolicyMutation,
    createToolGovernanceMutation,
    resolveToolGovernanceMutation,
    updateMemoryPolicyMutation,
    updateRuntimePolicyMutation,
    consumeMessageMutation,
    consumeAllMessagesMutation,
  };
}
