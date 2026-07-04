import { FileText, Pencil } from "lucide-react";
import { NavLink } from "react-router-dom";

import styles from "./MemoryReviewQueuePanel.styles";

export type MemoryReviewQueueItemView = {
  id: string;
  rank: number;
  title: string;
  origin: string;
  summary: string;
  reasons: string[];
  updatedAt: string;
  auditHref: string;
  manageHref?: string;
};

export type MemoryReviewQueuePanelCopy = {
  loading: string;
  loadFailed: string;
  noIssues: string;
  reviewReason: string;
  auditMemory: string;
  manageMemoryAction: string;
};

type MemoryReviewQueuePanelProps = {
  copy: MemoryReviewQueuePanelCopy;
  isLoading: boolean;
  errorText: string;
  items: MemoryReviewQueueItemView[];
  onOpenItem: (itemId: string) => void;
};

export function MemoryReviewQueuePanel({ copy, isLoading, errorText, items, onOpenItem }: MemoryReviewQueuePanelProps) {
  if (isLoading) {
    return <div className={styles.emptyState}>{copy.loading}</div>;
  }
  if (errorText) {
    return (
      <div className={styles.emptyState}>
        {copy.loadFailed}: {errorText}
      </div>
    );
  }
  if (!items.length) {
    return <div className={styles.emptyState}>{copy.noIssues}</div>;
  }
  return (
    <div className={styles.reviewQueueList}>
      {items.map((item) => (
        <article key={item.id} className={styles.reviewQueueItem}>
          <div className={styles.reviewRank}>{item.rank}</div>
          <div className={styles.reviewQueueBody}>
            <div className={styles.reviewQueueTitleLine}>
              <strong>{item.title}</strong>
              <span>{item.origin}</span>
            </div>
          </div>
          <span className={styles.reviewQueueSummary}>{item.summary}</span>
          <div className={styles.reviewReasonList} aria-label={copy.reviewReason}>
            {item.reasons.map((reason) => (
              <span key={`${item.id}:${reason}`} className={styles.reviewReasonPill}>
                {reason}
              </span>
            ))}
          </div>
          <span className={styles.reviewQueueTime}>{item.updatedAt}</span>
          <div className={styles.reviewQueueActions}>
            <NavLink
              className={styles.detailActionButton}
              to={item.auditHref}
              onClick={() => onOpenItem(item.id)}
              title={copy.auditMemory}
              aria-label={`${copy.auditMemory}: ${item.title}`}
            >
              <FileText size={14} />
              <span>{copy.auditMemory}</span>
            </NavLink>
            {item.manageHref ? (
              <NavLink
                className={styles.detailActionButton}
                to={item.manageHref}
                onClick={() => onOpenItem(item.id)}
                title={copy.manageMemoryAction}
                aria-label={`${copy.manageMemoryAction}: ${item.title}`}
              >
                <Pencil size={14} />
                <span>{copy.manageMemoryAction}</span>
              </NavLink>
            ) : null}
          </div>
        </article>
      ))}
    </div>
  );
}
