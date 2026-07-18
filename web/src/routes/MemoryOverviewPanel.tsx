import type { ReactNode } from "react";

import { VChip, VMetricStrip, VPanelHeader, VSurface, VTooltip } from "../components/vui";
import styles from "./MemoryOverviewPanel.styles";

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
      <VMetricStrip
        ariaLabel={copy.healthOverview}
        metrics={[
          { id: "sections", label: copy.sectionCount, value: summary?.sectionCount ?? 0 },
          { id: "items", label: copy.itemCount, value: summary?.itemCount ?? 0 },
          { id: "visible", label: copy.agentVisible, value: summary?.agentVisibleCount ?? 0 },
          { id: "runtime", label: copy.runtimeInjected, value: summary?.runtimeInjectedCount ?? 0 },
          { id: "managed", label: copy.managedMemory, value: managedStateCount },
          { id: "overrides", label: copy.disabledOrOverridden, value: disabledOrOverriddenCount },
        ]}
      />

      {warningStrip}

      <VSurface className={styles.reviewQueuePanel} elevation="panel" tone="rail">
        <VPanelHeader
          eyebrow={copy.healthOverview}
          title={copy.reviewQueue}
          actions={<VChip tone="neutral">{priorityReviewCount}</VChip>}
        />
        <VTooltip content={copy.reviewQueueHint} width="wide">
          <div tabIndex={0} aria-label={`${copy.reviewQueue} · ${copy.reviewQueueHint}`}>
            {reviewQueue}
          </div>
        </VTooltip>
      </VSurface>

      {projectMemoryQueue}

      <div className={styles.overviewGrid}>
        <VSurface className={styles.overviewPanel} elevation="panel" tone="rail">
          <VPanelHeader
            eyebrow={copy.healthOverview}
            title={copy.affectedRuntimeMemory}
            actions={<VChip tone="neutral">{runtimeMemoryCount}</VChip>}
          />
          {runtimeMemoryList}
        </VSurface>

        <VSurface className={styles.overviewPanel} elevation="panel" tone="rail">
          <VPanelHeader
            eyebrow={copy.healthOverview}
            title={copy.needsReview}
            actions={<VChip tone="neutral">{reviewMemoryCount}</VChip>}
          />
          {reviewMemoryList}
        </VSurface>
      </div>
    </>
  );
}
