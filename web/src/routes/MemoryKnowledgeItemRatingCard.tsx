import { BookOpen, CheckCircle2, History, PencilLine } from "lucide-react";

import type { KnowledgeItem } from "../api/types";
import { VButton, VNativeInput, VStatusChip, VStringSelect } from "../components/vui";
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
  knowledgeState: string;
  knowledgeRevision: string;
  knowledgeActive: string;
  knowledgeSuperseded: string;
  knowledgeWithdrawn: string;
  knowledgeExpired: string;
  knowledgeSourceWithdrawn: string;
  knowledgeSourceExpired: string;
  knowledgeSourceUnavailable: string;
  knowledgeStateUnknown: string;
  viewKnowledgeBody: string;
  viewOriginalSource: string;
  viewKnowledgeHistory: string;
  proposeKnowledgeRevision: string;
};

export type MemoryKnowledgeLifecycleMode = "item" | "source" | "history" | "revision";

type MemoryKnowledgeItemRatingCardProps = {
  copy: MemoryKnowledgeItemRatingCardCopy;
  item: KnowledgeItem;
  ratingDraft: MemoryKnowledgeRatingDraft;
  canRate: boolean;
  canRead: boolean;
  canPropose: boolean;
  knowledgeBusy: boolean;
  onRatingDraftChange: (draft: MemoryKnowledgeRatingDraft) => void;
  onUpdateKnowledgeRating: (item: KnowledgeItem) => void;
  onOpenLifecycleView: (item: KnowledgeItem, mode: MemoryKnowledgeLifecycleMode) => void;
};

export function MemoryKnowledgeItemRatingCard({
  copy,
  item,
  ratingDraft,
  canRate,
  canRead,
  canPropose,
  knowledgeBusy,
  onRatingDraftChange,
  onUpdateKnowledgeRating,
  onOpenLifecycleView,
}: MemoryKnowledgeItemRatingCardProps) {
  const state = String(item.knowledgeState || "unknown").toLowerCase();
  const stateCopy: Record<string, string> = {
    active: copy.knowledgeActive,
    superseded: copy.knowledgeSuperseded,
    withdrawn: copy.knowledgeWithdrawn,
    expired: copy.knowledgeExpired,
    source_withdrawn: copy.knowledgeSourceWithdrawn,
    source_expired: copy.knowledgeSourceExpired,
    source_unavailable: copy.knowledgeSourceUnavailable,
  };
  const stateTone = state === "active" ? "success" : state === "unknown" ? "neutral" : "warning";
  const canReadCurrentContent = canRead && state === "active" && !knowledgeBusy;
  const canReadHistory = canRead && !knowledgeBusy;
  return (
    <section className={styles.knowledgeItemCard}>
      <div className={styles.panelHeader}>
        <div>
          <strong>{item.title}</strong>
          <p>{item.summary || item.content}</p>
        </div>
        <div className={styles.cardStatus}>
          <VStatusChip tone={stateTone}>{stateCopy[state] ?? (state === "unknown" ? copy.knowledgeStateUnknown : state)}</VStatusChip>
          <VStatusChip tone="neutral">{item.importanceLevel}</VStatusChip>
        </div>
      </div>
      <div className={styles.metaGrid}>
        <span>{copy.knowledgeRevision}: {item.revision ?? 1}</span>
        <span>{copy.confidence}: {item.confidence}</span>
        <span>{copy.stability}: {item.stability}</span>
        <span>{copy.reviewPriority}: {item.reviewPriority}</span>
        <span>batch: {item.batchId}</span>
      </div>
      <div className={styles.lifecycleActions}>
        <VButton
          type="button"
          className={styles.detailActionButton}
          icon={<BookOpen size={14} />}
          isDisabled={!canReadCurrentContent}
          onPress={() => onOpenLifecycleView(item, "item")}
        >
          {copy.viewKnowledgeBody}
        </VButton>
        {item.sourceArtifactIds?.length ? (
          <VButton
            type="button"
            className={styles.detailActionButton}
            icon={<BookOpen size={14} />}
            isDisabled={!canReadCurrentContent}
            onPress={() => onOpenLifecycleView(item, "source")}
          >
            {copy.viewOriginalSource}
          </VButton>
        ) : null}
        <VButton
          type="button"
          className={styles.detailActionButton}
          icon={<History size={14} />}
          isDisabled={!canReadHistory}
          onPress={() => onOpenLifecycleView(item, "history")}
        >
          {copy.viewKnowledgeHistory}
        </VButton>
        <VButton
          type="button"
          className={styles.detailActionButton}
          icon={<PencilLine size={14} />}
          isDisabled={!canPropose || knowledgeBusy || state !== "active"}
          onPress={() => onOpenLifecycleView(item, "revision")}
        >
          {copy.proposeKnowledgeRevision}
        </VButton>
      </div>
      <label>
        <span>{copy.markingReason}</span>
        <VNativeInput
          value={ratingDraft.markingReason}
          onChange={(event) => onRatingDraftChange({ ...ratingDraft, markingReason: event.target.value })}
        />
      </label>
      <div className={styles.ratingControls}>
        <VStringSelect
          ariaLabel="importance"
          value={ratingDraft.importanceLevel}
          onValueChange={(importanceLevel) => onRatingDraftChange({ ...ratingDraft, importanceLevel })}
          options={["low", "medium", "high", "critical"].map((value) => ({ value, label: value }))}
        />
        <VNativeInput
          value={ratingDraft.confidence}
          onChange={(event) => onRatingDraftChange({ ...ratingDraft, confidence: event.target.value })}
          aria-label={copy.confidence}
        />
        <VStringSelect
          ariaLabel={copy.stability}
          value={ratingDraft.stability}
          onValueChange={(stability) => onRatingDraftChange({ ...ratingDraft, stability })}
          options={["temporary", "evolving", "stable", "deprecated"].map((value) => ({ value, label: value }))}
        />
        <VButton
          type="button"
          className={styles.detailActionButton}
          onClick={() => onUpdateKnowledgeRating(item)}
          isDisabled={!canRate || knowledgeBusy}

            icon={<CheckCircle2 size={14}/>}
          >
            <span>{copy.submitRatingSuggestion}</span>
          </VButton>
      </div>
    </section>
  );
}
