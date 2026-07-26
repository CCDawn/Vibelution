/**
 * Evolution library proposal edit/delete mutations (T3).
 */
import { useMutation } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import type {
  EvolutionProposalBulkDeleteResponse,
  EvolutionProposalDeleteResponse,
  EvolutionProposalUpdateResponse,
} from "../../api/types";

export type UseEvolutionProposalMutationsOptions = {
  libraryView: string;
  selectedProposalRunId: string | null;
  selectedRunId: string | null;
  selectedLibraryItemId: string | null;
  selectedPendingItemId: string | null;
  setProposalEditFeedback: Dispatch<SetStateAction<string>>;
  setProposalEditDraft: Dispatch<SetStateAction<any>>;
  setProposalEditOpen: Dispatch<SetStateAction<boolean>>;
  setLibraryFeedback: Dispatch<SetStateAction<string>>;
  setRunRecordsFeedback: Dispatch<SetStateAction<string>>;
  setSelectedProposalRunIds: Dispatch<SetStateAction<string[]>>;
  setSelectedRunIds: Dispatch<SetStateAction<string[]>>;
  setSelectedRunId: Dispatch<SetStateAction<string | null>>;
  setSelectedLibraryItemId: Dispatch<SetStateAction<string | null>>;
  setSelectedPendingItemId: Dispatch<SetStateAction<string | null>>;
  proposalEditDraftFromDetail: (proposal: any) => any;
  afterProposalChanged: (sessionId: string) => Promise<unknown> | unknown;
};

export function useEvolutionProposalMutations(options: UseEvolutionProposalMutationsOptions) {
  const clearSelectionIfSession = (sessionId: string) => {
    if (options.selectedRunId === sessionId) {
      options.setSelectedRunId(null);
    }
    if (options.selectedLibraryItemId === sessionId) {
      options.setSelectedLibraryItemId(null);
    }
    if (options.selectedPendingItemId === sessionId) {
      options.setSelectedPendingItemId(null);
    }
  };

  const updateProposalMutation = useMutation({
    mutationFn: ({ sessionId, draft }: { sessionId: string; draft: Record<string, unknown> }) =>
      fetchJson<EvolutionProposalUpdateResponse>(`/api/evolution/proposals/${sessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(draft),
      }),
    onSuccess: async (payload) => {
      options.setProposalEditFeedback(payload.summary);
      options.setProposalEditDraft(options.proposalEditDraftFromDetail(payload.proposal));
      if (payload.updated) {
        options.setProposalEditOpen(false);
      }
      await options.afterProposalChanged(payload.sessionId);
    },
  });

  const deleteProposalMutation = useMutation({
    mutationFn: (sessionId: string) =>
      fetchJson<EvolutionProposalDeleteResponse>(`/api/evolution/proposals/${sessionId}`, {
        method: "DELETE",
      }),
    onSuccess: async (payload) => {
      options.setLibraryFeedback(payload.summary);
      options.setSelectedProposalRunIds((current) => current.filter((item) => item !== payload.sessionId));
      clearSelectionIfSession(payload.sessionId);
      await options.afterProposalChanged(payload.sessionId);
    },
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: (sessionIds: string[]) =>
      fetchJson<EvolutionProposalBulkDeleteResponse>("/api/evolution/proposals/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionIds }),
      }),
    onSuccess: async (payload) => {
      options.setLibraryFeedback(payload.summary);
      options.setSelectedProposalRunIds([]);
      if (
        options.selectedProposalRunId
        && payload.results.some(
          (item) => item.sessionId === options.selectedProposalRunId && item.status === "deleted",
        )
      ) {
        if (options.libraryView === "items") {
          options.setSelectedLibraryItemId(null);
        } else {
          options.setSelectedPendingItemId(null);
        }
      }
      await options.afterProposalChanged(options.selectedProposalRunId ?? "__none__");
    },
  });

  const deleteRunRecordMutation = useMutation({
    mutationFn: (sessionId: string) =>
      fetchJson<EvolutionProposalDeleteResponse>(`/api/evolution/proposals/${sessionId}`, {
        method: "DELETE",
      }),
    onSuccess: async (payload) => {
      options.setRunRecordsFeedback(payload.summary);
      options.setSelectedRunIds((current) => current.filter((item) => item !== payload.sessionId));
      options.setSelectedProposalRunIds((current) => current.filter((item) => item !== payload.sessionId));
      clearSelectionIfSession(payload.sessionId);
      await options.afterProposalChanged(payload.sessionId);
    },
  });

  const bulkDeleteRunRecordsMutation = useMutation({
    mutationFn: (sessionIds: string[]) =>
      fetchJson<EvolutionProposalBulkDeleteResponse>("/api/evolution/proposals/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionIds }),
      }),
    onSuccess: async (payload) => {
      const deletedIds = new Set(
        payload.results.filter((item) => item.status === "deleted").map((item) => item.sessionId),
      );
      options.setRunRecordsFeedback(payload.summary);
      options.setSelectedRunIds([]);
      options.setSelectedProposalRunIds((current) => current.filter((item) => !deletedIds.has(item)));
      if (options.selectedRunId && deletedIds.has(options.selectedRunId)) {
        options.setSelectedRunId(null);
      }
      if (options.selectedLibraryItemId && deletedIds.has(options.selectedLibraryItemId)) {
        options.setSelectedLibraryItemId(null);
      }
      if (options.selectedPendingItemId && deletedIds.has(options.selectedPendingItemId)) {
        options.setSelectedPendingItemId(null);
      }
      await options.afterProposalChanged(options.selectedProposalRunId ?? "__none__");
    },
  });

  return {
    updateProposalMutation,
    deleteProposalMutation,
    bulkDeleteMutation,
    deleteRunRecordMutation,
    bulkDeleteRunRecordsMutation,
  };
}
