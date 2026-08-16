/**
 * Memory item CRUD / project-update resolve / cleanup mutations (R4).
 * Knowledge proposal/rating mutations stay route-owned until their draft model is promoted.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { resolveAgentProjectMemoryUpdate } from "../../api/agents";
import {
  createMemoryItem,
  deleteMemoryItem,
  executeMemoryCleanup,
  previewMemoryCleanup,
  restoreMemoryItem,
  updateMemoryItem,
} from "../../api/memory";
import { startUserAction } from "../../app/userActionTelemetry";
import { queryKeys } from "../../api/queryKeys";
import type {
  AgentProjectMemoryUpdateProposal,
  MemoryCleanupExecuteResponse,
  MemoryCleanupPreviewResponse,
} from "../../api/types";
import { isMemoryCleanupExecutionSuccessful } from "./memoryCleanupSafety";

type Notice = { tone: "success" | "error"; text: string };

export type UseMemoryItemMutationsOptions = {
  copy: {
    mutationDone: string;
    mutationFailed: string;
    cleanupPreviewReady: string;
    cleanupExecuteDone: string;
    cleanupFailed: string;
  };
  setEditDraft: Dispatch<SetStateAction<any>>;
  setActiveSectionId: Dispatch<SetStateAction<string>>;
  setActiveItemId: Dispatch<SetStateAction<string>>;
  setMutationFeedback: Dispatch<SetStateAction<Notice | null>> | ((n: Notice) => void);
  setMemoryProposalResolutionNotes: Dispatch<SetStateAction<Record<string, string>>>;
  setCleanupPreview: Dispatch<SetStateAction<any>>;
  setCleanupExecution: Dispatch<SetStateAction<any>>;
  setCleanupConfirmationText: Dispatch<SetStateAction<string>>;
  setCleanupFeedback: Dispatch<SetStateAction<Notice | null>> | ((n: Notice) => void);
  fallbackKnowledgeActorAgentId: string;
  requestedTeamId: string;
  invalidateMemoryQueries: (queryClient: ReturnType<typeof useQueryClient>) => void;
  invalidateKnowledgeDashboard: (queryClient: ReturnType<typeof useQueryClient>, agentId: string) => void;
};

export function useMemoryItemMutations(options: UseMemoryItemMutationsOptions) {
  const queryClient = useQueryClient();

  const memoryMutation = useMutation({
    mutationFn: async (draft: {
      mode: "create" | string;
      title: string;
      summary: string;
      content: string;
      sectionId: string;
      itemId: string;
    }) => {
      if (draft.mode === "create") {
        return createMemoryItem<{ sectionId: string; itemId: string }>({
          title: draft.title,
          summary: draft.summary,
          content: draft.content,
        });
      }
      return updateMemoryItem<{ sectionId: string; itemId: string }>(draft.sectionId, draft.itemId, {
        title: draft.title,
        summary: draft.summary,
        content: draft.content,
      });
    },
    onMutate: (draft) => ({
      telemetry: startUserAction(
        draft.mode === "create" ? "memory_item_create" : "memory_item_update",
        {
          sectionId: draft.sectionId,
          itemId: draft.itemId,
        },
      ),
    }),
    onSuccess: (payload, _variables, context) => {
      context?.telemetry?.succeeded({
        sectionId: payload.sectionId,
        itemId: payload.itemId,
      });
      options.setEditDraft(null);
      options.setActiveSectionId(payload.sectionId);
      options.setActiveItemId(payload.itemId);
      options.setMutationFeedback({ tone: "success", text: options.copy.mutationDone });
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sectionId: variables.sectionId,
        itemId: variables.itemId,
      });
      options.setMutationFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const deleteMemoryMutation = useMutation({
    mutationFn: async ({ sectionId, itemId }: { sectionId: string; itemId: string }) =>
      deleteMemoryItem<{ sectionId: string; itemId: string }>(sectionId, itemId),
    onMutate: (variables) => ({
      telemetry: startUserAction("memory_item_delete", {
        sectionId: variables.sectionId,
        itemId: variables.itemId,
      }, { destructive: true }),
    }),
    onSuccess: (payload, _variables, context) => {
      context?.telemetry?.succeeded({
        sectionId: payload.sectionId,
        itemId: payload.itemId,
      });
      options.setActiveSectionId(payload.sectionId === "user-managed-memory" ? "" : payload.sectionId);
      options.setActiveItemId(payload.sectionId === "user-managed-memory" ? "" : payload.itemId);
      options.setMutationFeedback({ tone: "success", text: options.copy.mutationDone });
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sectionId: variables.sectionId,
        itemId: variables.itemId,
      });
      options.setMutationFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const restoreMemoryMutation = useMutation({
    mutationFn: async ({ sectionId, itemId }: { sectionId: string; itemId: string }) =>
      restoreMemoryItem<{ sectionId: string; itemId: string }>(sectionId, itemId),
    onMutate: (variables) => ({
      telemetry: startUserAction("memory_item_restore", {
        sectionId: variables.sectionId,
        itemId: variables.itemId,
      }),
    }),
    onSuccess: (payload, _variables, context) => {
      context?.telemetry?.succeeded({
        sectionId: payload.sectionId,
        itemId: payload.itemId,
      });
      options.setActiveSectionId(payload.sectionId);
      options.setActiveItemId(payload.itemId);
      options.setMutationFeedback({ tone: "success", text: options.copy.mutationDone });
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        sectionId: variables.sectionId,
        itemId: variables.itemId,
      });
      options.setMutationFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const projectMemoryUpdateResolveMutation = useMutation({
    mutationFn: async ({
      proposal,
      status,
      resolutionNote,
    }: {
      proposal: AgentProjectMemoryUpdateProposal;
      status: string;
      resolutionNote: string;
    }) =>
      resolveAgentProjectMemoryUpdate(proposal.agentId, proposal.proposalId, {
        status,
        resolvedBy: "user",
        resolutionNote,
      }),
    onSuccess: (proposal) => {
      options.setMutationFeedback({ tone: "success", text: `${options.copy.mutationDone} · ${proposal.status}` });
      options.setMemoryProposalResolutionNotes((current) => {
        const next = { ...current };
        delete next[proposal.proposalId];
        return next;
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentProjectMemoryUpdates("pending", "", 100) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agentProjectMemoryUpdates("", "", 100) });
    },
    onError: (error) => {
      options.setMutationFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const cleanupPreviewMutation = useMutation({
    mutationFn: async (targets: Array<Record<string, unknown>>) =>
      previewMemoryCleanup<MemoryCleanupPreviewResponse>(targets),
    onSuccess: (payload) => {
      options.setCleanupPreview(payload);
      options.setCleanupExecution(null);
      options.setCleanupFeedback({ tone: "success", text: options.copy.cleanupPreviewReady });
      void queryClient.setQueryData(queryKeys.memoryCleanupPreview(), payload);
    },
    onError: (error) => {
      options.setCleanupFeedback({
        tone: "error",
        text: `${options.copy.cleanupFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const cleanupExecuteMutation = useMutation({
    mutationFn: async ({
      targets,
      confirmationPhrase,
      previewToken,
    }: {
      targets: Array<Record<string, unknown>>;
      confirmationPhrase: string;
      previewToken: string;
    }) =>
      executeMemoryCleanup<MemoryCleanupExecuteResponse>({
        targets,
        confirmationPhrase,
        previewToken,
      }),
    onMutate: (variables) => ({
      telemetry: startUserAction("memory_cleanup_execute", {
        targetCount: variables.targets.length,
      }, { destructive: true }),
    }),
    onSuccess: (payload, variables, context) => {
      const succeeded = isMemoryCleanupExecutionSuccessful(payload);
      if (succeeded) {
        context?.telemetry?.succeeded({
          targetCount: variables.targets.length,
          outcome: payload.outcome,
        });
      } else {
        context?.telemetry?.failed(payload.outcome, {
          targetCount: variables.targets.length,
          outcome: payload.outcome,
        });
      }
      options.setCleanupPreview(null);
      options.setCleanupExecution(payload);
      options.setCleanupConfirmationText("");
      options.setCleanupFeedback({
        tone: succeeded ? "success" : "error",
        text: succeeded
          ? options.copy.cleanupExecuteDone
          : `${options.copy.cleanupFailed}: ${payload.outcome}`,
      });
      options.invalidateMemoryQueries(queryClient);
      options.invalidateKnowledgeDashboard(queryClient, options.fallbackKnowledgeActorAgentId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.memoryKnowledgeGraph(
          options.fallbackKnowledgeActorAgentId,
          "officialResearchGraph",
          options.requestedTeamId,
        ),
      });
      void queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { targetCount: variables.targets.length });
      options.setCleanupFeedback({
        tone: "error",
        text: `${options.copy.cleanupFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  return {
    memoryMutation,
    deleteMemoryMutation,
    restoreMemoryMutation,
    projectMemoryUpdateResolveMutation,
    cleanupPreviewMutation,
    cleanupExecuteMutation,
  };
}
