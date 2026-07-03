import type { ReactNode } from "react";

import styles from "./MemoryRoute.styles";

export type MemoryOverviewPanelCopy = {
  sectionCount: string;
  itemCount: string;
  agentVisible: string;
  runtimeInjected: string;
  managedMemory: string;
  disabledOrOverridden: string;
  healthOverview: string;
  reviewQueue: string;
  reviewQueueHint: string;
  affectedRuntimeMemory: string;
  needsReview: string;
};

export type MemoryOverviewSummary = {
  sectionCount: number;
  itemCount: number;
  agentVisibleCount: number;
  runtimeInjectedCount: number;
};

type MemoryOverviewPanelProps = {
  copy: MemoryOverviewPanelCopy;
  summary?: MemoryOverviewSummary | null;
  managedStateCount: number;
  disabledOrOverriddenCount: number;
  priorityReviewCount: number;
  runtimeMemoryCount: number;
  reviewMemoryCount: number;
  warningStrip: ReactNode;
  reviewQueue: ReactNode;
  projectMemoryQueue: ReactNode;
  runtimeMemoryList: ReactNode;
  reviewMemoryList: ReactNode;
};

export function MemoryOverviewPanel({
  copy,
  summary,
  managedStateCount,
  disabledOrOverriddenCount,
  priorityReviewCount,
  runtimeMemoryCount,
  reviewMemoryCount,
  warningStrip,
  reviewQueue,
  projectMemoryQueue,
  runtimeMemoryList,
  reviewMemoryList,
}: MemoryOverviewPanelProps) {
  return (
    <>
      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.sectionCount}</span>
          <strong>{summary?.sectionCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.itemCount}</span>
          <strong>{summary?.itemCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.agentVisible}</span>
          <strong>{summary?.agentVisibleCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.runtimeInjected}</span>
          <strong>{summary?.runtimeInjectedCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.managedMemory}</span>
          <strong>{managedStateCount}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.disabledOrOverridden}</span>
          <strong>{disabledOrOverriddenCount}</strong>
        </section>
      </div>

      {warningStrip}

      <section className={styles.reviewQueuePanel}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.healthOverview}</p>
            <h2>{copy.reviewQueue}</h2>
          </div>
          <span className={styles.countPill}>{priorityReviewCount}</span>
        </div>
        <div title={copy.reviewQueueHint}>{reviewQueue}</div>
      </section>

      {projectMemoryQueue}

      <div className={styles.overviewGrid}>
        <section className={styles.overviewPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.healthOverview}</p>
              <h2>{copy.affectedRuntimeMemory}</h2>
            </div>
            <span className={styles.countPill}>{runtimeMemoryCount}</span>
          </div>
          {runtimeMemoryList}
        </section>

        <section className={styles.overviewPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.healthOverview}</p>
              <h2>{copy.needsReview}</h2>
            </div>
            <span className={styles.countPill}>{reviewMemoryCount}</span>
          </div>
          {reviewMemoryList}
        </section>
      </div>
    </>
  );
}
