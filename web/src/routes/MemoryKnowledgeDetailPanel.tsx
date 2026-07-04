import { FileText } from "lucide-react";

import type { KnowledgeItem, KnowledgeTracePayload, TeamKnowledgeBase } from "../api/types";
import { VNativeInput } from "../components/vui";
import styles from "./MemoryKnowledgeDetailPanel.styles";
import { MemoryKnowledgeItemRatingCard, type MemoryKnowledgeRatingDraft } from "./MemoryKnowledgeItemRatingCard";

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
          <MemoryKnowledgeItemRatingCard
            key={item.knowledgeItemId}
            copy={copy}
            item={item}
            ratingDraft={ratingDraft}
            canRate={Boolean(activeKnowledgeBase?.permissions.canRate)}
            knowledgeBusy={knowledgeBusy}
            onRatingDraftChange={onRatingDraftChange}
            onUpdateKnowledgeRating={onUpdateKnowledgeRating}
          />
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
