/**
 * Memory item CRUD / project-update resolve / cleanup mutations (R4).
 * Knowledge proposal/rating mutations stay route-owned until their draft model is promoted.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type { AgentProjectMemoryUpdateProposal } from "../../api/types";

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
  memoryMutationEndpoint: (sectionId: string, itemId: string, suffix?: string) => string;
  projectMemoryProposalResolveEndpoint: (proposal: AgentProjectMemoryUpdateProposal) => string;
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
      const body = JSON.stringify({
        title: draft.title,
        summary: draft.summary,
        content: draft.content,
      });
      if (draft.mode === "create") {
        return fetchJson<{ sectionId: string; itemId: string }>("/api/memory/items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        });
      }
      return fetchJson<{ sectionId: string; itemId: string }>(
        options.memoryMutationEndpoint(draft.sectionId, draft.itemId),
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body,
        },
      );
    },
    onSuccess: (payload) => {
      options.setEditDraft(null);
      options.setActiveSectionId(payload.sectionId);
      options.setActiveItemId(payload.itemId);
      options.setMutationFeedback({ tone: "success", text: options.copy.mutationDone });
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      options.setMutationFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const deleteMemoryMutation = useMutation({
    mutationFn: async ({ sectionId, itemId }: { sectionId: string; itemId: string }) =>
      fetchJson<{ sectionId: string; itemId: string }>(options.memoryMutationEndpoint(sectionId, itemId), {
        method: "DELETE",
      }),
    onSuccess: (payload) => {
      options.setActiveSectionId(payload.sectionId === "user-managed-memory" ? "" : payload.sectionId);
      options.setActiveItemId(payload.sectionId === "user-managed-memory" ? "" : payload.itemId);
      options.setMutationFeedback({ tone: "success", text: options.copy.mutationDone });
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      options.setMutationFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const restoreMemoryMutation = useMutation({
    mutationFn: async ({ sectionId, itemId }: { sectionId: string; itemId: string }) =>
      fetchJson<{ sectionId: string; itemId: string }>(
        options.memoryMutationEndpoint(sectionId, itemId, "/restore"),
        { method: "POST" },
      ),
    onSuccess: (payload) => {
      options.setActiveSectionId(payload.sectionId);
      options.setActiveItemId(payload.itemId);
      options.setMutationFeedback({ tone: "success", text: options.copy.mutationDone });
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
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
      fetchJson<AgentProjectMemoryUpdateProposal>(options.projectMemoryProposalResolveEndpoint(proposal), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status,
          resolvedBy: "user",
          resolutionNote,
        }),
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
      fetchJson<Record<string, unknown>>("/api/memory/cleanup/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targets }),
      }),
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
    }: {
      targets: Array<Record<string, unknown>>;
      confirmationPhrase: string;
    }) =>
      fetchJson<Record<string, unknown>>("/api/memory/cleanup/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ targets, confirmationPhrase }),
      }),
    onSuccess: (payload) => {
      options.setCleanupPreview(payload);
      options.setCleanupExecution(payload);
      options.setCleanupConfirmationText("");
      options.setCleanupFeedback({ tone: "success", text: options.copy.cleanupExecuteDone });
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
    onError: (error) => {
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
