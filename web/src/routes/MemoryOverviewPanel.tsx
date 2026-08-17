import type { ReactNode } from "react";

import { VChip, VMetricStrip, VPanelHeader, VSurface } from "../components/vui";
import styles from "./MemoryOverviewPanel.styles";

export type MemoryOverviewPanelCopy = {
  sectionCount: string;
  sectionCountHint: string;
  itemCount: string;
  itemCountHint: string;
  agentVisible: string;
  agentVisibleHint: string;
  runtimeInjected: string;
  runtimeInjectedHint: string;
  managedMemory: string;
  managedMemoryHint: string;
  disabledOrOverridden: string;
  disabledOrOverriddenHint: string;
  healthOverview: string;
  reviewQueue: string;
  reviewQueueHint: string;
  affectedRuntimeMemory: string;
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
  warningStrip: ReactNode;
  reviewQueue: ReactNode;
  projectMemoryQueue: ReactNode;
  runtimeMemoryList: ReactNode;
};

export function MemoryOverviewPanel({
  copy,
  summary,
  managedStateCount,
  disabledOrOverriddenCount,
  priorityReviewCount,
  runtimeMemoryCount,
  warningStrip,
  reviewQueue,
  projectMemoryQueue,
  runtimeMemoryList,
}: MemoryOverviewPanelProps) {
  return (
    <div className={styles.overviewStack}>
      <VMetricStrip
        ariaLabel={copy.healthOverview}
        metrics={[
          { id: "sections", label: copy.sectionCount, value: summary?.sectionCount ?? 0, detail: copy.sectionCountHint },
          { id: "items", label: copy.itemCount, value: summary?.itemCount ?? 0, detail: copy.itemCountHint },
          { id: "visible", label: copy.agentVisible, value: summary?.agentVisibleCount ?? 0, detail: copy.agentVisibleHint },
          { id: "runtime", label: copy.runtimeInjected, value: summary?.runtimeInjectedCount ?? 0, detail: copy.runtimeInjectedHint },
          { id: "managed", label: copy.managedMemory, value: managedStateCount, detail: copy.managedMemoryHint },
          { id: "overrides", label: copy.disabledOrOverridden, value: disabledOrOverriddenCount, detail: copy.disabledOrOverriddenHint },
        ]}
      />

      {warningStrip}

      <VSurface className={styles.reviewQueuePanel} elevation="panel" tone="rail" padding="compact">
        <VPanelHeader
          eyebrow={copy.healthOverview}
          title={copy.reviewQueue}
          tooltip={copy.reviewQueueHint}
          tooltipLabel={`${copy.reviewQueue} details`}
          actions={<VChip tone="neutral">{priorityReviewCount}</VChip>}
        />
        <div className={styles.reviewQueueScroll}>{reviewQueue}</div>
      </VSurface>

      <div className={styles.projectMemorySlot}>{projectMemoryQueue}</div>

      <div className={styles.overviewGrid}>
        <VSurface className={styles.overviewPanel} elevation="panel" tone="rail">
          <VPanelHeader
            eyebrow={copy.healthOverview}
            title={copy.affectedRuntimeMemory}
            tooltip={copy.runtimeInjectedHint}
            tooltipLabel={`${copy.affectedRuntimeMemory} details`}
            actions={<VChip tone="neutral">{runtimeMemoryCount}</VChip>}
          />
          <div className={styles.reviewQueueScroll}>{runtimeMemoryList}</div>
        </VSurface>
      </div>
    </div>
  );
}
