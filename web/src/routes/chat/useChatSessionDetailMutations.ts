import { useMutation, type QueryClient, type UseMutationResult } from "@tanstack/react-query";
import { useRef, type Dispatch, type SetStateAction } from "react";

import { resolveAgentToolGovernanceRequest } from "../../api/agents";
import {
  isFetchJsonHttpError,
  resolveSessionToolApprovalDecision,
  updateSessionModelParameters,
  type SessionToolApprovalDecision,
} from "../../api/chat";
import { postPetAction } from "../../api/pet";
import { queryKeys } from "../../api/queryKeys";
import type {
  AgentToolGovernanceRequest,
  PetActionResponse,
  SessionDetail,
  SessionLlmOptions,
  SessionModelParametersUpdate,
  SessionToolApprovalRequest,
} from "../../api/types";
import { mergeSessionDetailMessageWindow } from "../chatSessionState";
import type { createChatWorkspaceCache } from "../chatWorkspaceCache";
import {
  SESSION_DETAIL_HISTORY_PAGE_SIZE,
  fetchSessionDetailWindow,
} from "./chatSessionDetailHelpers";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;

export type UseChatSessionDetailMutationsOptions = {
  queryClient: QueryClient;
  chatWorkspaceCache: ChatWorkspaceCache;
  lang: "zh" | "en";
  describeError: (error: unknown, fallback: string) => string;
  activeSessionId: string | null | undefined;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
};

export type UseChatSessionDetailMutationsResult = {
  sessionModelParametersMutation: UseMutationResult<
    SessionLlmOptions,
    Error,
    { sessionId: string; parameters: SessionModelParametersUpdate },
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
  resolveSessionToolApprovalMutation: UseMutationResult<
    SessionToolApprovalRequest,
    Error,
    { request: SessionToolApprovalRequest; decision: SessionToolApprovalDecision },
    unknown
  >;
};

/**
 * Session-detail local mutations: Agent model parameters, history paging,
 * and tool-approval resolve. No EventSource ownership.
 */
export function useChatSessionDetailMutations({
  queryClient,
  chatWorkspaceCache,
  lang,
  describeError,
  activeSessionId,
  setSessionComposerErrors,
}: UseChatSessionDetailMutationsOptions): UseChatSessionDetailMutationsResult {
  const approvalOperationSequence = useRef(0);
  const approvalOperations = useRef(new Map<string, number>());
  const activeSessionIdRef = useRef(activeSessionId);
  activeSessionIdRef.current = activeSessionId;
  const sessionModelParametersMutation = useMutation({
    mutationFn: (variables: { sessionId: string; parameters: SessionModelParametersUpdate }) =>
      updateSessionModelParameters(variables.sessionId, variables.parameters),
    onSuccess: (payload, variables) => {
      const expected = variables.parameters;
      const key = queryKeys.sessionLlmOptions(variables.sessionId);
      let cacheMatched = false;
      if (
        activeSessionIdRef.current === variables.sessionId
        && payload.sessionId === variables.sessionId
        && payload.agentId === expected.expectedAgentId
        && payload.model?.modelRef === expected.expectedModelRef
      ) {
        queryClient.setQueryData<SessionLlmOptions>(key, (current) => {
          if (
            !current
            || current.agentId !== expected.expectedAgentId
            || current.model?.modelRef !== expected.expectedModelRef
            || current.configRevision !== expected.expectedConfigRevision
          ) {
            return current;
          }
          cacheMatched = true;
          return payload;
        });
      }
      if (activeSessionIdRef.current === variables.sessionId && !cacheMatched) {
        void queryClient.invalidateQueries({ queryKey: key });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    },
    onError: (_error, variables) => {
      const isRevisionConflict = isFetchJsonHttpError(_error) && _error.status === 409;
      if (isRevisionConflict && activeSessionIdRef.current === variables.sessionId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.sessionLlmOptions(variables.sessionId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
        void queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
      }
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
      resolveAgentToolGovernanceRequest(request, decision),
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

  const resolveSessionToolApprovalMutation = useMutation({
    mutationFn: (
      { request, decision }: {
        request: SessionToolApprovalRequest;
        decision: SessionToolApprovalDecision;
      },
    ) =>
      resolveSessionToolApprovalDecision(request, decision),
    onMutate: async (variables) => {
      const key = queryKeys.sessionToolApprovals(variables.request.sessionId);
      const operationKey = JSON.stringify([variables.request.sessionId, variables.request.requestId]);
      const operation = ++approvalOperationSequence.current;
      approvalOperations.current.set(operationKey, operation);
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<SessionToolApprovalRequest[]>(key);
      // Drop the banner immediately so the operator is not blocked on network round-trips.
      queryClient.setQueryData<SessionToolApprovalRequest[]>(
        key,
        (current) => (current ?? []).filter((item) => item.requestId !== variables.request.requestId),
      );
      return {
        previousRequest: previous?.find((item) => item.requestId === variables.request.requestId),
        sessionId: variables.request.sessionId,
        operationKey,
        operation,
      };
    },
    onSuccess: (_payload, variables) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.sessionToolApprovals(variables.request.sessionId),
      });
      // Session detail refresh is deferred slightly so the approval UI can clear first.
      void Promise.resolve().then(() => {
        void queryClient.invalidateQueries({
          queryKey: queryKeys.session(variables.request.sessionId),
        });
        void chatWorkspaceCache.refreshSessionRuntime(variables.request.sessionId);
      });
    },
    onError: (error, variables, context) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessionToolApprovals(variables.request.sessionId) });
      if (context && approvalOperations.current.get(context.operationKey) !== context.operation) return;
      if (context?.previousRequest && approvalOperations.current.get(context.operationKey) === context.operation) {
        queryClient.setQueryData<SessionToolApprovalRequest[]>(
          queryKeys.sessionToolApprovals(context.sessionId),
          (current) => (current ?? []).some((item) => item.requestId === variables.request.requestId)
            ? current : [...(current ?? []), context.previousRequest!],
        );
      }
      setSessionComposerErrors((current) => ({
        ...current,
        [variables.request.sessionId]: describeError(
          error,
          lang === "zh" ? "处理本轮工具审批失败" : "Resolve session tool approval failed",
        ),
      }));
    },
    onSettled: (_data, _error, _variables, context) => {
      if (context && approvalOperations.current.get(context.operationKey) === context.operation) {
        approvalOperations.current.delete(context.operationKey);
      }
    },
  });

  return {
    sessionModelParametersMutation,
    loadEarlierSessionMessagesMutation,
    resolveToolApprovalMutation,
    resolveSessionToolApprovalMutation,
  };
}
