/**
 * Knowledge refinement / rating / source-inbox mutations for Memory workbench (S3).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  KnowledgeItem,
  KnowledgeOwnerSource,
  KnowledgeRatingSuggestion,
  KnowledgeRatingSuggestionBulkReviewResponse,
  KnowledgeRatingSuggestionReviewResponse,
  KnowledgeRefinementProposal,
  KnowledgeReviewResponse,
  KnowledgeSourceArtifact,
  KnowledgeSourceInboxReviewResponse,
} from "../../api/types";

type Notice = { tone: "success" | "error"; text: string };

export type UseMemoryKnowledgeMutationsOptions = {
  copy: {
    mutationDone: string;
    mutationFailed: string;
    skippedSuggestions?: string;
  };
  setProposalDraft: Dispatch<SetStateAction<any>>;
  setOwnerSourceDraft: Dispatch<SetStateAction<any>>;
  setKnowledgeFeedback: Dispatch<SetStateAction<Notice | null>> | ((n: Notice) => void);
  setSelectedRatingSuggestionIds: Dispatch<SetStateAction<string[]>>;
  newProposalDraft: () => any;
  newOwnerSourceDraft: () => any;
  commaList: (value: string) => string[];
  parseJsonObject: (value: string) => Record<string, unknown>;
  getActiveKnowledgeActorAgentId: () => string;
  getActiveKnowledgeBaseForItems: () => string;
  getKnowledgeSearchDraft: () => { query: string; tags: string; searchMode: string };
  getActiveSourceOwnerType: () => string;
  getActiveSourceOwnerId: () => string;
  getActiveSourceInboxStatus: () => string;
  getSourceReviewNote: () => string;
  getDuplicateCentralSourceId: () => string;
  invalidateMemoryQueries: (queryClient: ReturnType<typeof useQueryClient>) => void;
  invalidateKnowledgeDashboard: (queryClient: ReturnType<typeof useQueryClient>, agentId: string) => void;
};

export function useMemoryKnowledgeMutations(options: UseMemoryKnowledgeMutationsOptions) {
  const queryClient = useQueryClient();

  const proposalMutation = useMutation({
    mutationFn: async ({ knowledgeBaseId, draft }: { knowledgeBaseId: string; draft: any }) =>
      fetchJson<KnowledgeRefinementProposal>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/refinement-proposals`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sourceArtifactIds: options.commaList(draft.sourceArtifactIds),
            proposedByAgentId: draft.proposedByAgentId,
            title: draft.title,
            summary: draft.summary,
            content: draft.content,
            tags: options.commaList(draft.tags),
          }),
        },
      ),
    onSuccess: () => {
      options.setProposalDraft(options.newProposalDraft());
      options.setKnowledgeFeedback({ tone: "success", text: options.copy.mutationDone });
      options.invalidateKnowledgeDashboard(queryClient, options.getActiveKnowledgeActorAgentId());
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      options.setKnowledgeFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const reviewMutation = useMutation({
    mutationFn: async ({
      knowledgeBaseId,
      proposalId,
      status,
    }: {
      knowledgeBaseId: string;
      proposalId: string;
      status: string;
    }) =>
      fetchJson<KnowledgeReviewResponse>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/refinement-proposals/${encodeURIComponent(proposalId)}/review`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, reviewedByAgentId: options.getActiveKnowledgeActorAgentId() }),
        },
      ),
    onSuccess: (payload) => {
      options.setKnowledgeFeedback({
        tone: "success",
        text: payload.item ? `${options.copy.mutationDone} · ${payload.item.title}` : options.copy.mutationDone,
      });
      const actor = options.getActiveKnowledgeActorAgentId();
      const baseId = options.getActiveKnowledgeBaseForItems();
      const search = options.getKnowledgeSearchDraft();
      options.invalidateKnowledgeDashboard(queryClient, actor);
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(baseId, actor) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeSearch(baseId, actor, search.query, search.tags, search.searchMode),
      });
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      options.setKnowledgeFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const ratingMutation = useMutation({
    mutationFn: async ({
      knowledgeBaseId,
      item,
      draft,
    }: {
      knowledgeBaseId: string;
      item: KnowledgeItem;
      draft: any;
    }) =>
      fetchJson<KnowledgeRatingSuggestion>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/rating-suggestions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            suggestedByAgentId: draft.actorAgentId,
            targetType: "knowledge_item",
            knowledgeItemId: item.knowledgeItemId,
            importanceLevel: draft.importanceLevel,
            confidence: draft.confidence.trim() ? Number(draft.confidence) : null,
            stability: draft.stability,
            reviewPriority: draft.reviewPriority,
            markingReason: draft.markingReason,
          }),
        },
      ),
    onSuccess: () => {
      options.setKnowledgeFeedback({ tone: "success", text: options.copy.mutationDone });
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "rating-suggestions"] });
      options.invalidateKnowledgeDashboard(queryClient, options.getActiveKnowledgeActorAgentId());
    },
    onError: (error) => {
      options.setKnowledgeFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const ratingSuggestionReviewMutation = useMutation({
    mutationFn: async ({
      knowledgeBaseId,
      suggestionId,
      status,
    }: {
      knowledgeBaseId: string;
      suggestionId: string;
      status: "applied" | "rejected";
    }) =>
      fetchJson<KnowledgeRatingSuggestionReviewResponse>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/rating-suggestions/${encodeURIComponent(suggestionId)}/review`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, reviewedByAgentId: options.getActiveKnowledgeActorAgentId() }),
        },
      ),
    onSuccess: () => {
      options.setKnowledgeFeedback({ tone: "success", text: options.copy.mutationDone });
      const actor = options.getActiveKnowledgeActorAgentId();
      const baseId = options.getActiveKnowledgeBaseForItems();
      const search = options.getKnowledgeSearchDraft();
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "rating-suggestions"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(baseId, actor) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeSearch(baseId, actor, search.query, search.tags, search.searchMode),
      });
      options.invalidateKnowledgeDashboard(queryClient, actor);
    },
    onError: (error) => {
      options.setKnowledgeFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const ratingSuggestionBulkReviewMutation = useMutation({
    mutationFn: async ({
      knowledgeBaseId,
      suggestionIds,
      status,
    }: {
      knowledgeBaseId: string;
      suggestionIds: string[];
      status: "applied" | "rejected";
    }) =>
      fetchJson<KnowledgeRatingSuggestionBulkReviewResponse>(
        `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/rating-suggestions/review-batch`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            suggestionIds,
            status,
            reviewedByAgentId: options.getActiveKnowledgeActorAgentId(),
          }),
        },
      ),
    onSuccess: (payload) => {
      options.setSelectedRatingSuggestionIds([]);
      options.setKnowledgeFeedback({
        tone: "success",
        text: `${options.copy.mutationDone} · ${payload.summary.reviewedCount}/${payload.summary.requestedCount}${
          payload.summary.skippedCount
            ? ` · ${options.copy.skippedSuggestions ?? "skipped"}: ${payload.summary.skippedCount}`
            : ""
        }`,
      });
      const actor = options.getActiveKnowledgeActorAgentId();
      const baseId = options.getActiveKnowledgeBaseForItems();
      const search = options.getKnowledgeSearchDraft();
      void queryClient.invalidateQueries({ queryKey: ["knowledge", "rating-suggestions"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.knowledgeItems(baseId, actor) });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeSearch(baseId, actor, search.query, search.tags, search.searchMode),
      });
      options.invalidateKnowledgeDashboard(queryClient, actor);
    },
    onError: (error) => {
      options.setKnowledgeFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const sourceInboxCollectMutation = useMutation({
    mutationFn: async (draft: any) =>
      fetchJson<KnowledgeOwnerSource>("/api/knowledge/sources/inbox", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ownerType: options.getActiveSourceOwnerType(),
          ownerId: options.getActiveSourceOwnerId(),
          sourceType: draft.sourceType,
          sourceRef: options.parseJsonObject(draft.sourceRef),
          originalContent: draft.originalContent,
          originalFilename: draft.originalFilename,
          sourceCreatedAt: draft.sourceCreatedAt,
          capturedBy: draft.capturedBy.trim() || options.getActiveKnowledgeActorAgentId(),
          sourceHash: draft.sourceHash,
          evidenceRange: options.parseJsonObject(draft.evidenceRange),
          title: draft.title,
          summary: draft.summary,
          actorAgentId: options.getActiveKnowledgeActorAgentId(),
        }),
      }),
    onSuccess: () => {
      options.setOwnerSourceDraft(options.newOwnerSourceDraft());
      options.setKnowledgeFeedback({ tone: "success", text: options.copy.mutationDone });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeSourceInbox(
          options.getActiveSourceOwnerType(),
          options.getActiveSourceOwnerId(),
          options.getActiveKnowledgeActorAgentId(),
          options.getActiveSourceInboxStatus(),
        ),
      });
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      options.setKnowledgeFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const sourceInboxReviewMutation = useMutation({
    mutationFn: async ({
      source,
      decision,
    }: {
      source: KnowledgeOwnerSource;
      decision: "accepted" | "rejected" | "duplicate" | "needs_more_context";
    }) =>
      fetchJson<KnowledgeSourceInboxReviewResponse>(
        `/api/knowledge/sources/inbox/${encodeURIComponent(options.getActiveSourceOwnerType())}/${encodeURIComponent(options.getActiveSourceOwnerId())}/${encodeURIComponent(source.inboxSourceId)}/review`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision,
            reviewedByAgentId: options.getActiveKnowledgeActorAgentId(),
            resolutionNote: options.getSourceReviewNote(),
            duplicateOf: decision === "duplicate" ? options.getDuplicateCentralSourceId() : "",
          }),
        },
      ),
    onSuccess: (payload) => {
      options.setKnowledgeFeedback({
        tone: "success",
        text: payload.centralSource?.centralSourceId
          ? `${options.copy.mutationDone} · ${payload.centralSource.centralSourceId}`
          : options.copy.mutationDone,
      });
      const actor = options.getActiveKnowledgeActorAgentId();
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeSourceInbox(
          options.getActiveSourceOwnerType(),
          options.getActiveSourceOwnerId(),
          actor,
          options.getActiveSourceInboxStatus(),
        ),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeCentralSources(
          actor,
          options.getActiveSourceOwnerType(),
          options.getActiveSourceOwnerId(),
        ),
      });
      options.invalidateKnowledgeDashboard(queryClient, actor);
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      options.setKnowledgeFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const centralSourceAttachMutation = useMutation({
    mutationFn: async (centralSourceId: string) =>
      fetchJson<KnowledgeSourceArtifact>(
        `/api/knowledge-bases/${encodeURIComponent(options.getActiveKnowledgeBaseForItems())}/central-source-artifacts`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            centralSourceId,
            actorAgentId: options.getActiveKnowledgeActorAgentId(),
          }),
        },
      ),
    onSuccess: (payload) => {
      options.setProposalDraft((current: any) => ({
        ...current,
        sourceArtifactIds: [...options.commaList(current.sourceArtifactIds), payload.sourceArtifactId].join(", "),
      }));
      options.setKnowledgeFeedback({
        tone: "success",
        text: `${options.copy.mutationDone} · ${payload.sourceArtifactId}`,
      });
      const actor = options.getActiveKnowledgeActorAgentId();
      options.invalidateKnowledgeDashboard(queryClient, actor);
      void queryClient.invalidateQueries({
        queryKey: queryKeys.knowledgeItems(options.getActiveKnowledgeBaseForItems(), actor),
      });
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error) => {
      options.setKnowledgeFeedback({
        tone: "error",
        text: `${options.copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  return {
    proposalMutation,
    reviewMutation,
    ratingMutation,
    ratingSuggestionReviewMutation,
    ratingSuggestionBulkReviewMutation,
    sourceInboxCollectMutation,
    sourceInboxReviewMutation,
    centralSourceAttachMutation,
  };
}
