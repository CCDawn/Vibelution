import { CheckCircle2, Eye, Pencil, Square, SquareCheckBig, XCircle } from "lucide-react";

import type { KnowledgeRatingSuggestion, TeamKnowledgeBase } from "../api/types";
import { VButton, VNativeInput, VNativeSelect, VNativeTextarea } from "../components/vui";
import styles from "./MemoryRoute.styles";

export type MemoryKnowledgeProposalDraft = {
  proposedByAgentId: string;
  sourceArtifactIds: string;
  title: string;
  summary: string;
  content: string;
  tags: string;
};

export type MemoryKnowledgeRatingSuggestionStatusFilter = "pending" | "applied" | "rejected" | "all";
export type MemoryKnowledgeRatingSuggestionPriorityFilter = "all" | "urgent" | "elevated" | "normal";

export type MemoryKnowledgeReviewPanelCopy = {
  refinementProposal: string;
  pendingProposals: string;
  submitProposal: string;
  proposalTitle: string;
  capturedBy: string;
  sourceArtifacts: string;
  tags: string;
  summaryField: string;
  proposalContent: string;
  approveProposal: string;
  rejectProposal: string;
  noIssues: string;
  ratingSuggestions: string;
  governance: string;
  status: string;
  applySuggestion: string;
  rejectSuggestion: string;
  allStatuses: string;
  priority: string;
  allPriorities: string;
  selectedSuggestions: string;
  selectAllVisibleSuggestions: string;
  clearSuggestionSelection: string;
  bulkApplySuggestions: string;
  bulkRejectSuggestions: string;
  selectSuggestion: string;
  confidence: string;
};

type MemoryKnowledgeReviewPanelProps = {
  copy: MemoryKnowledgeReviewPanelCopy;
  activeKnowledgeBase: TeamKnowledgeBase | null | undefined;
  proposalDraft: MemoryKnowledgeProposalDraft;
  ratingSuggestions: KnowledgeRatingSuggestion[];
  pendingVisibleRatingSuggestions: KnowledgeRatingSuggestion[];
  selectedRatingSuggestionIds: string[];
  selectedVisibleRatingSuggestionIds: string[];
  ratingSuggestionStatus: MemoryKnowledgeRatingSuggestionStatusFilter;
  ratingSuggestionPriority: MemoryKnowledgeRatingSuggestionPriorityFilter;
  ratingSuggestionsPending: boolean;
  knowledgeBusy: boolean;
  onProposalDraftChange: (draft: MemoryKnowledgeProposalDraft) => void;
  onSubmitRefinementProposal: () => void;
  onReviewProposal: (proposalId: string, status: "approved" | "rejected") => void;
  onRatingSuggestionStatusChange: (status: MemoryKnowledgeRatingSuggestionStatusFilter) => void;
  onRatingSuggestionPriorityChange: (priority: MemoryKnowledgeRatingSuggestionPriorityFilter) => void;
  onToggleVisibleRatingSuggestions: () => void;
  onClearRatingSuggestionSelection: () => void;
  onReviewSelectedRatingSuggestions: (status: "applied" | "rejected") => void;
  onToggleRatingSuggestionSelection: (suggestionId: string) => void;
  onReviewRatingSuggestion: (suggestionId: string, status: "applied" | "rejected") => void;
};

export function MemoryKnowledgeReviewPanel({
  copy,
  activeKnowledgeBase,
  proposalDraft,
  ratingSuggestions,
  pendingVisibleRatingSuggestions,
  selectedRatingSuggestionIds,
  selectedVisibleRatingSuggestionIds,
  ratingSuggestionStatus,
  ratingSuggestionPriority,
  ratingSuggestionsPending,
  knowledgeBusy,
  onProposalDraftChange,
  onSubmitRefinementProposal,
  onReviewProposal,
  onRatingSuggestionStatusChange,
  onRatingSuggestionPriorityChange,
  onToggleVisibleRatingSuggestions,
  onClearRatingSuggestionSelection,
  onReviewSelectedRatingSuggestions,
  onToggleRatingSuggestionSelection,
  onReviewRatingSuggestion,
}: MemoryKnowledgeReviewPanelProps) {
  const canPropose = Boolean(activeKnowledgeBase?.permissions.canPropose);
  const canReview = Boolean(activeKnowledgeBase?.permissions.canReview);
  const canRate = Boolean(activeKnowledgeBase?.permissions.canRate);

  return (
    <>
      <section className={styles.managementPanel}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.refinementProposal}</p>
            <h2>{copy.pendingProposals}</h2>
          </div>
          <VButton
            type="button"
            className={styles.primaryActionButton}
            onClick={onSubmitRefinementProposal}
            isDisabled={!canPropose || knowledgeBusy}
          >
            <Pencil size={15} />
            <span>{copy.submitProposal}</span>
          </VButton>
        </div>
        <div className={styles.knowledgeFormGrid}>
          <label>
            <span>{copy.proposalTitle}</span>
            <VNativeInput value={proposalDraft.title} onChange={(event) => onProposalDraftChange({ ...proposalDraft, title: event.target.value })} />
          </label>
          <label>
            <span>{copy.capturedBy}</span>
            <VNativeInput value={proposalDraft.proposedByAgentId} onChange={(event) => onProposalDraftChange({ ...proposalDraft, proposedByAgentId: event.target.value })} />
          </label>
          <label>
            <span>{copy.sourceArtifacts}</span>
            <VNativeInput value={proposalDraft.sourceArtifactIds} onChange={(event) => onProposalDraftChange({ ...proposalDraft, sourceArtifactIds: event.target.value })} />
          </label>
          <label>
            <span>{copy.tags}</span>
            <VNativeInput value={proposalDraft.tags} onChange={(event) => onProposalDraftChange({ ...proposalDraft, tags: event.target.value })} />
          </label>
          <label className={styles.wideField}>
            <span>{copy.summaryField}</span>
            <VNativeTextarea rows={2} value={proposalDraft.summary} onChange={(event) => onProposalDraftChange({ ...proposalDraft, summary: event.target.value })} />
          </label>
          <label className={styles.wideField}>
            <span>{copy.proposalContent}</span>
            <VNativeTextarea rows={4} value={proposalDraft.content} onChange={(event) => onProposalDraftChange({ ...proposalDraft, content: event.target.value })} />
          </label>
        </div>
        <div className={styles.knowledgeProposalList}>
          {(activeKnowledgeBase?.pendingProposals ?? []).map((proposal) => (
            <section key={proposal.proposalId} className={styles.knowledgeRow}>
              <strong>{proposal.title}</strong>
              <span>{proposal.summary || proposal.content}</span>
              <VButton
                type="button"
                className={styles.detailActionButton}
                isDisabled={!canReview || knowledgeBusy}
                onClick={() => onReviewProposal(proposal.proposalId, "approved")}
              >
                <CheckCircle2 size={14} />
                <span>{copy.approveProposal}</span>
              </VButton>
              <VButton
                type="button"
                className={styles.detailActionButton}
                isDisabled={!canReview || knowledgeBusy}
                onClick={() => onReviewProposal(proposal.proposalId, "rejected")}
              >
                <XCircle size={14} />
                <span>{copy.rejectProposal}</span>
              </VButton>
            </section>
          ))}
          {activeKnowledgeBase && activeKnowledgeBase.pendingProposals.length === 0 ? (
            <section className={styles.emptyDetail}>
              <Eye size={20} />
              <strong>{copy.noIssues}</strong>
            </section>
          ) : null}
        </div>
      </section>

      <section className={styles.managementPanel}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.ratingSuggestions}</p>
            <h2>{copy.governance}</h2>
          </div>
          <span className={styles.countPill}>{ratingSuggestions.length}</span>
        </div>
        <div className={styles.queueToolbar}>
          <label>
            <span>{copy.status}</span>
            <VNativeSelect value={ratingSuggestionStatus} onChange={(event) => onRatingSuggestionStatusChange(event.target.value as MemoryKnowledgeRatingSuggestionStatusFilter)}>
              <option value="pending">{copy.pendingProposals}</option>
              <option value="applied">{copy.applySuggestion}</option>
              <option value="rejected">{copy.rejectSuggestion}</option>
              <option value="all">{copy.allStatuses}</option>
            </VNativeSelect>
          </label>
          <label>
            <span>{copy.priority}</span>
            <VNativeSelect value={ratingSuggestionPriority} onChange={(event) => onRatingSuggestionPriorityChange(event.target.value as MemoryKnowledgeRatingSuggestionPriorityFilter)}>
              <option value="all">{copy.allPriorities}</option>
              <option value="urgent">urgent</option>
              <option value="elevated">elevated</option>
              <option value="normal">normal</option>
            </VNativeSelect>
          </label>
        </div>
        <div className={styles.bulkActionBar}>
          <span className={styles.countPill}>{copy.selectedSuggestions}: {selectedVisibleRatingSuggestionIds.length}</span>
          <VButton type="button" className={styles.detailActionButton} onClick={onToggleVisibleRatingSuggestions} isDisabled={!pendingVisibleRatingSuggestions.length || knowledgeBusy}>
            <SquareCheckBig size={14} />
            <span>{copy.selectAllVisibleSuggestions}</span>
          </VButton>
          <VButton type="button" className={styles.detailActionButton} onClick={onClearRatingSuggestionSelection} isDisabled={!selectedVisibleRatingSuggestionIds.length || knowledgeBusy}>
            <Square size={14} />
            <span>{copy.clearSuggestionSelection}</span>
          </VButton>
          <VButton
            type="button"
            className={styles.detailActionButton}
            isDisabled={!canRate || !selectedVisibleRatingSuggestionIds.length || knowledgeBusy}
            onClick={() => onReviewSelectedRatingSuggestions("applied")}
          >
            <CheckCircle2 size={14} />
            <span>{copy.bulkApplySuggestions}</span>
          </VButton>
          <VButton
            type="button"
            className={styles.detailActionButton}
            isDisabled={!canRate || !selectedVisibleRatingSuggestionIds.length || knowledgeBusy}
            onClick={() => onReviewSelectedRatingSuggestions("rejected")}
          >
            <XCircle size={14} />
            <span>{copy.bulkRejectSuggestions}</span>
          </VButton>
        </div>
        <div className={styles.knowledgeProposalList}>
          {ratingSuggestions.map((suggestion) => (
            <section key={suggestion.suggestionId} className={styles.knowledgeRow}>
              <label className={styles.inlineCheck}>
                <VNativeInput
                  type="checkbox"
                  aria-label={copy.selectSuggestion}
                  checked={selectedRatingSuggestionIds.includes(suggestion.suggestionId)}
                  disabled={suggestion.status !== "pending" || knowledgeBusy}
                  onChange={() => onToggleRatingSuggestionSelection(suggestion.suggestionId)}
                />
                <span>{copy.selectSuggestion}</span>
              </label>
              <strong>{suggestion.importanceLevel} · {suggestion.reviewPriority}</strong>
              <span>{suggestion.markingReason || suggestion.suggestionId}</span>
              <small>{suggestion.status} · {suggestion.targetType} · {suggestion.knowledgeItemId || suggestion.proposalId} · {copy.confidence}: {suggestion.confidence}</small>
              <VButton
                type="button"
                className={styles.detailActionButton}
                isDisabled={!canRate || suggestion.status !== "pending" || knowledgeBusy}
                onClick={() => onReviewRatingSuggestion(suggestion.suggestionId, "applied")}
              >
                <CheckCircle2 size={14} />
                <span>{copy.applySuggestion}</span>
              </VButton>
              <VButton
                type="button"
                className={styles.detailActionButton}
                isDisabled={!canRate || suggestion.status !== "pending" || knowledgeBusy}
                onClick={() => onReviewRatingSuggestion(suggestion.suggestionId, "rejected")}
              >
                <XCircle size={14} />
                <span>{copy.rejectSuggestion}</span>
              </VButton>
            </section>
          ))}
          {!ratingSuggestionsPending && !ratingSuggestions.length ? (
            <section className={styles.emptyDetail}>
              <CheckCircle2 size={20} />
              <strong>{copy.noIssues}</strong>
            </section>
          ) : null}
        </div>
      </section>
    </>
  );
}
