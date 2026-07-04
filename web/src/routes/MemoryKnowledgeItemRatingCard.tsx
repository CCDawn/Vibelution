import { CheckCircle2 } from "lucide-react";

import type { KnowledgeItem } from "../api/types";
import { VButton, VNativeInput, VNativeSelect } from "../components/vui";
import styles from "./MemoryKnowledgeItemRatingCard.styles";

export type MemoryKnowledgeRatingDraft = {
  actorAgentId: string;
  importanceLevel: string;
  confidence: string;
  stability: string;
  scope: string;
  reviewPriority: string;
  markingReason: string;
};

export type MemoryKnowledgeItemRatingCardCopy = {
  confidence: string;
  stability: string;
  reviewPriority: string;
  markingReason: string;
  submitRatingSuggestion: string;
};

type MemoryKnowledgeItemRatingCardProps = {
  copy: MemoryKnowledgeItemRatingCardCopy;
  item: KnowledgeItem;
  ratingDraft: MemoryKnowledgeRatingDraft;
  canRate: boolean;
  knowledgeBusy: boolean;
  onRatingDraftChange: (draft: MemoryKnowledgeRatingDraft) => void;
  onUpdateKnowledgeRating: (item: KnowledgeItem) => void;
};

export function MemoryKnowledgeItemRatingCard({
  copy,
  item,
  ratingDraft,
  canRate,
  knowledgeBusy,
  onRatingDraftChange,
  onUpdateKnowledgeRating,
}: MemoryKnowledgeItemRatingCardProps) {
  return (
    <section className={styles.knowledgeItemCard}>
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
        <VNativeInput
          value={ratingDraft.markingReason}
          onChange={(event) => onRatingDraftChange({ ...ratingDraft, markingReason: event.target.value })}
        />
      </label>
      <div className={styles.ratingControls}>
        <VNativeSelect
          value={ratingDraft.importanceLevel}
          onChange={(event) => onRatingDraftChange({ ...ratingDraft, importanceLevel: event.target.value })}
        >
          {["low", "medium", "high", "critical"].map((value) => <option key={value} value={value}>{value}</option>)}
        </VNativeSelect>
        <VNativeInput
          value={ratingDraft.confidence}
          onChange={(event) => onRatingDraftChange({ ...ratingDraft, confidence: event.target.value })}
          aria-label={copy.confidence}
        />
        <VNativeSelect
          value={ratingDraft.stability}
          onChange={(event) => onRatingDraftChange({ ...ratingDraft, stability: event.target.value })}
        >
          {["temporary", "evolving", "stable", "deprecated"].map((value) => <option key={value} value={value}>{value}</option>)}
        </VNativeSelect>
        <VButton
          type="button"
          className={styles.detailActionButton}
          onClick={() => onUpdateKnowledgeRating(item)}
          isDisabled={!canRate || knowledgeBusy}
        >
          <CheckCircle2 size={14} />
          <span>{copy.submitRatingSuggestion}</span>
        </VButton>
      </div>
    </section>
  );
}
