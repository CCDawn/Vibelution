import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  AgentToolGovernanceRequest,
  PetActionResponse,
  SessionDetail,
  SessionLlmOptions,
  SessionSummary,
} from "../../api/types";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";
import { updateSessionSummaryCaches } from "../chatSessionIndexQuery";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import {
  SESSION_DETAIL_HISTORY_PAGE_SIZE,
  fetchSessionDetailWindow,
} from "./chatSessionDetailHelpers";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;
type PetInteractionAction = "feed" | "talk" | "care";

export type UseChatSessionDetailMutationsOptions = {
  queryClient: QueryClient;
  chatWorkspaceCache: ChatWorkspaceCache;
  lang: "zh" | "en";
  describeError: (error: unknown, fallback: string) => string;
  activeSessionId: string | null | undefined;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  setPetActionFeedback: Dispatch<SetStateAction<string>>;
};

export type UseChatSessionDetailMutationsResult = {
  sessionReasoningEffortMutation: UseMutationResult<
    SessionLlmOptions,
    Error,
    { sessionId: string; reasoningEffort: string },
    unknown
  >;
  loadEarlierSessionMessagesMutation: UseMutationResult<
    SessionDetail,
    Error,
    { sessionId: string; beforeMessageIndex: number },
    unknown
  >;
  resolveToolApprovalMutation: UseMutationResult<
    AgentToolGovernanceRequest,
    Error,
    { request: AgentToolGovernanceRequest; decision: "approve" | "reject" },
    unknown
  >;
  petActionMutation: UseMutationResult<
    PetActionResponse,
    Error,
    { action: PetInteractionAction },
    unknown
  >;
};

/**
 * Session-detail local mutations: reasoning effort, history paging,
 * tool-approval resolve, and pet actions. No EventSource ownership.
 */
export function useChatSessionDetailMutations({
  queryClient,
  chatWorkspaceCache,
  lang,
  describeError,
  activeSessionId,
  setSessionComposerErrors,
  setPetActionFeedback,
}: UseChatSessionDetailMutationsOptions): UseChatSessionDetailMutationsResult {
  const sessionReasoningEffortMutation = useMutation({
    mutationFn: (variables: { sessionId: string; reasoningEffort: string }) =>
      fetchJson<SessionLlmOptions>(`/api/sessions/${encodeURIComponent(variables.sessionId)}/reasoning-effort`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reasoningEffort: variables.reasoningEffort }),
      }),
    onMutate: (variables) => {
      setSessionComposerErrors((current) => ({ ...current, [variables.sessionId]: "" }));
    },
    onSuccess: (payload, variables) => {
      queryClient.setQueryData(queryKeys.sessionLlmOptions(variables.sessionId), payload);
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (current) => current ? {
        ...current,
        reasoningEffort: payload.currentReasoningEffort,
      } : current);
      updateSessionSummaryCaches(queryClient, (sessions: SessionSummary[] | undefined) => sessions?.map((session) => session.id === variables.sessionId ? {
        ...session,
        reasoningEffort: payload.currentReasoningEffort,
      } : session));
    },
    onError: (error, variables) => {
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.sessionId]: describeError(error, lang === "zh" ? "推理强度切换失败" : "Failed to change reasoning effort"),
      }));
    },
  });

  const loadEarlierSessionMessagesMutation = useMutation({
    mutationFn: (variables: { sessionId: string; beforeMessageIndex: number }) =>
      fetchSessionDetailWindow(variables.sessionId, {
        messageLimit: SESSION_DETAIL_HISTORY_PAGE_SIZE,
        beforeMessageIndex: variables.beforeMessageIndex,
        transcriptScope: "window",
      }),
    onSuccess: (page, variables) => {
      queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (current) =>
        mergeSessionDetailMessageWindow(current, page),
      );
    },
  });

  const resolveToolApprovalMutation = useMutation({
    mutationFn: async (
      { request, decision }: {
        request: AgentToolGovernanceRequest;
        decision: "approve" | "reject";
      },
    ) =>
      fetchJson<AgentToolGovernanceRequest>(
        `/api/agents/${encodeURIComponent(request.targetAgentId)}/tool-governance-requests/${encodeURIComponent(request.requestId)}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            decision,
            resolvedBy: "user",
            resolutionNote: decision === "approve" ? "会话内批准" : "会话内拒绝",
          }),
        },
      ),
    onSuccess: (_payload, variables) => {
      const sessionId = activeSessionId || variables.request.sourceSessionId || "";
      setSessionComposerErrors((current) => (sessionId ? { ...current, [sessionId]: "" } : current));
      if (sessionId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(sessionId) });
        void chatWorkspaceCache.refreshSessionRuntime(sessionId);
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      void chatWorkspaceCache.afterSessionChanged({ sessionId });
    },
    onError: (error, variables) => {
      const sessionId = activeSessionId || variables.request.sourceSessionId || "__sessions__";
      setSessionComposerErrors((current) => ({
        ...current,
        [sessionId]: describeError(error, lang === "zh" ? "处理工具审批失败" : "Resolve tool approval failed"),
      }));
    },
  });

  const petActionMutation = useMutation({
    mutationFn: async ({ action }: { action: PetInteractionAction }) =>
      fetchJson<PetActionResponse>("/api/pet/actions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ action }),
      }),
    onSuccess: (payload) => {
      setPetActionFeedback(payload.message);
      queryClient.setQueryData(queryKeys.petSummary(), payload.summary);
      void queryClient.invalidateQueries({ queryKey: queryKeys.petSummary() });
    },
    onError: (error) => {
      setPetActionFeedback(describeError(error, lang === "zh" ? "宠物互动失败" : "Pet interaction failed"));
      void queryClient.invalidateQueries({ queryKey: queryKeys.petSummary() });
    },
  });

  return {
    sessionReasoningEffortMutation,
    loadEarlierSessionMessagesMutation,
    resolveToolApprovalMutation,
    petActionMutation,
  };
}
