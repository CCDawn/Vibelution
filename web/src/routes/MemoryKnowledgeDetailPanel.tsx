import { CheckCircle2, FileText } from "lucide-react";

import type { KnowledgeItem, KnowledgeTracePayload, TeamKnowledgeBase } from "../api/types";
import { VButton, VNativeInput, VNativeSelect } from "../components/vui";
import styles from "./MemoryKnowledgeDetailPanel.styles";

export type MemoryKnowledgeRatingDraft = {
  actorAgentId: string;
  importanceLevel: string;
  confidence: string;
  stability: string;
  scope: string;
  reviewPriority: string;
  markingReason: string;
};

export type MemoryKnowledgeDetailPanelCopy = {
  formalKnowledge: string;
  selectedKnowledgeDetail: string;
  sourceChain: string;
  traceability: string;
  sourceArtifacts: string;
  pendingProposals: string;
  ratingSuggestions: string;
  loading: string;
  confidence: string;
  stability: string;
  reviewPriority: string;
  markingReason: string;
  submitRatingSuggestion: string;
  noMatches: string;
};

type MemoryKnowledgeDetailPanelProps = {
  copy: MemoryKnowledgeDetailPanelCopy;
  activeKnowledgeBase: TeamKnowledgeBase | null | undefined;
  traceTargetId: string;
  trace: KnowledgeTracePayload | undefined;
  knowledgeItems: KnowledgeItem[];
  knowledgeItemsPending: boolean;
  ratingDraft: MemoryKnowledgeRatingDraft;
  knowledgeBusy: boolean;
  onTraceTargetChange: (value: string) => void;
  onRatingDraftChange: (draft: MemoryKnowledgeRatingDraft) => void;
  onUpdateKnowledgeRating: (item: KnowledgeItem) => void;
};

export function MemoryKnowledgeDetailPanel({
  copy,
  activeKnowledgeBase,
  traceTargetId,
  trace,
  knowledgeItems,
  knowledgeItemsPending,
  ratingDraft,
  knowledgeBusy,
  onTraceTargetChange,
  onRatingDraftChange,
  onUpdateKnowledgeRating,
}: MemoryKnowledgeDetailPanelProps) {
  return (
    <aside className={styles.detailPanel}>
      <div className={styles.detailHeader}>
        <p className={styles.panelEyebrow}>{copy.formalKnowledge}</p>
        <h2>{activeKnowledgeBase?.name ?? copy.selectedKnowledgeDetail}</h2>
      </div>
      <section className={styles.managementPanel}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.sourceChain}</p>
            <h2>{copy.traceability}</h2>
          </div>
        </div>
        <label>
          <span>{copy.traceability}</span>
          <VNativeInput value={traceTargetId} onChange={(event) => onTraceTargetChange(event.target.value)} placeholder="source / proposal / item / rating id" />
        </label>
        {trace ? (
          <div className={styles.metaGrid}>
            <span>{copy.sourceArtifacts}: {trace.summary.sourceArtifacts ?? 0}</span>
            <span>{copy.pendingProposals}: {trace.summary.proposals ?? 0}</span>
            <span>{copy.formalKnowledge}: {trace.summary.items ?? 0}</span>
            <span>{copy.ratingSuggestions}: {trace.summary.ratingSuggestions ?? 0}</span>
          </div>
        ) : null}
      </section>
      {knowledgeItemsPending ? <div className={styles.emptyState}>{copy.loading}</div> : null}
      <div className={styles.knowledgeItems}>
        {knowledgeItems.map((item) => (
          <section key={item.knowledgeItemId} className={styles.knowledgeItemCard}>
            <div className={styles.panelHeader}>
              <div>
                <strong>{item.title}</strong>
                <p>{item.summary || item.content}</p>
              </div>
              <span className={styles.statusPill}>{item.importanceLevel}</span>
            </div>
            <div className={styles.metaGrid}>
              <span>{copy.confidence}: {item.confidence}</span>
              <span>{copy.stability}: {item.stability}</span>
              <span>{copy.reviewPriority}: {item.reviewPriority}</span>
              <span>batch: {item.batchId}</span>
            </div>
            <label>
              <span>{copy.markingReason}</span>
              <VNativeInput value={ratingDraft.markingReason} onChange={(event) => onRatingDraftChange({ ...ratingDraft, markingReason: event.target.value })} />
            </label>
            <div className={styles.ratingControls}>
              <VNativeSelect value={ratingDraft.importanceLevel} onChange={(event) => onRatingDraftChange({ ...ratingDraft, importanceLevel: event.target.value })}>
                {["low", "medium", "high", "critical"].map((value) => <option key={value} value={value}>{value}</option>)}
              </VNativeSelect>
              <VNativeInput value={ratingDraft.confidence} onChange={(event) => onRatingDraftChange({ ...ratingDraft, confidence: event.target.value })} aria-label={copy.confidence} />
              <VNativeSelect value={ratingDraft.stability} onChange={(event) => onRatingDraftChange({ ...ratingDraft, stability: event.target.value })}>
                {["temporary", "evolving", "stable", "deprecated"].map((value) => <option key={value} value={value}>{value}</option>)}
              </VNativeSelect>
              <VButton
                type="button"
                className={styles.detailActionButton}
                onClick={() => onUpdateKnowledgeRating(item)}
                isDisabled={!activeKnowledgeBase?.permissions.canRate || knowledgeBusy}
              >
                <CheckCircle2 size={14} />
                <span>{copy.submitRatingSuggestion}</span>
              </VButton>
            </div>
          </section>
        ))}
        {!knowledgeItemsPending && !knowledgeItems.length ? (
          <section className={styles.emptyDetail}>
            <FileText size={22} />
            <strong>{copy.noMatches}</strong>
          </section>
        ) : null}
      </div>
    </aside>
  );
}
