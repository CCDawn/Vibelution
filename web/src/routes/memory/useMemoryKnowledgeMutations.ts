/**
 * Knowledge refinement / rating / source-inbox mutations for Memory workbench (S3).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import {
  bulkReviewKnowledgeRatingSuggestions,
  collectKnowledgeSourceInbox,
  createKnowledgeCentralSourceArtifact,
  createKnowledgeRatingSuggestion,
  createKnowledgeRefinementProposal,
  reviewKnowledgeRatingSuggestion,
  reviewKnowledgeRefinementProposal,
  reviewKnowledgeSourceInbox,
} from "../../api/knowledge";
import { startUserAction } from "../../app/userActionTelemetry";
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
      createKnowledgeRefinementProposal<KnowledgeRefinementProposal>(knowledgeBaseId, {
        sourceArtifactIds: options.commaList(draft.sourceArtifactIds),
        proposedByAgentId: draft.proposedByAgentId,
        title: draft.title,
        summary: draft.summary,
        content: draft.content,
        tags: options.commaList(draft.tags),
      }),
    onMutate: ({ knowledgeBaseId, draft }) => ({
      telemetry: startUserAction("memory_knowledge_proposal_create", {
        knowledgeBaseId,
        proposedByAgentId: draft.proposedByAgentId,
      }),
    }),
    onSuccess: (_payload, variables, context) => {
      context?.telemetry?.succeeded({ knowledgeBaseId: variables.knowledgeBaseId });
      options.setProposalDraft(options.newProposalDraft());
      options.setKnowledgeFeedback({ tone: "success", text: options.copy.mutationDone });
      options.invalidateKnowledgeDashboard(queryClient, options.getActiveKnowledgeActorAgentId());
      options.invalidateMemoryQueries(queryClient);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { knowledgeBaseId: variables.knowledgeBaseId });
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
      reviewKnowledgeRefinementProposal<KnowledgeReviewResponse>(knowledgeBaseId, proposalId, {
        status,
        reviewedByAgentId: options.getActiveKnowledgeActorAgentId(),
      }),
    onMutate: (variables) => ({
      telemetry: startUserAction("memory_knowledge_proposal_review", {
        knowledgeBaseId: variables.knowledgeBaseId,
        proposalId: variables.proposalId,
        status: variables.status,
      }),
    }),
    onSuccess: (payload, variables, context) => {
      context?.telemetry?.succeeded({
        knowledgeBaseId: variables.knowledgeBaseId,
        proposalId: variables.proposalId,
        status: variables.status,
      });
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
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        knowledgeBaseId: variables.knowledgeBaseId,
        proposalId: variables.proposalId,
      });
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
      createKnowledgeRatingSuggestion<KnowledgeRatingSuggestion>(knowledgeBaseId, {
        suggestedByAgentId: draft.actorAgentId,
        targetType: "knowledge_item",
        knowledgeItemId: item.knowledgeItemId,
        importanceLevel: draft.importanceLevel,
        confidence: draft.confidence.trim() ? Number(draft.confidence) : null,
        stability: draft.stability,
        reviewPriority: draft.reviewPriority,
        markingReason: draft.markingReason,
      }),
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
      reviewKnowledgeRatingSuggestion<KnowledgeRatingSuggestionReviewResponse>(
        knowledgeBaseId,
        suggestionId,
        {
          status,
          reviewedByAgentId: options.getActiveKnowledgeActorAgentId(),
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
      bulkReviewKnowledgeRatingSuggestions<KnowledgeRatingSuggestionBulkReviewResponse>(knowledgeBaseId, {
        suggestionIds,
        status,
        reviewedByAgentId: options.getActiveKnowledgeActorAgentId(),
      }),
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
      collectKnowledgeSourceInbox<KnowledgeOwnerSource>({
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
      reviewKnowledgeSourceInbox<KnowledgeSourceInboxReviewResponse>(
        options.getActiveSourceOwnerType(),
        options.getActiveSourceOwnerId(),
        source.inboxSourceId,
        {
          decision,
          reviewedByAgentId: options.getActiveKnowledgeActorAgentId(),
          resolutionNote: options.getSourceReviewNote(),
          duplicateOf: decision === "duplicate" ? options.getDuplicateCentralSourceId() : "",
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
      createKnowledgeCentralSourceArtifact<KnowledgeSourceArtifact>(
        options.getActiveKnowledgeBaseForItems(),
        {
          centralSourceId,
          actorAgentId: options.getActiveKnowledgeActorAgentId(),
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
