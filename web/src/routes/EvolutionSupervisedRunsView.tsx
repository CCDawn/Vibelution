import type { CSSProperties, ReactNode } from "react";
import { Suspense, lazy } from "react";

import type { EvolutionLibraryEntry, EvolutionRun } from "../api/types";
import { VSection, VTabs } from "../components/vui";
import type { Language } from "../i18n/dictionary";
import type { EvolutionRunRecordsLibraryView, EvolutionRunRecordsPanelLabels } from "./EvolutionRunRecordsPanel";
import { supervisedRunBucketLabel } from "./evolution/evolutionRouteModel";
import styles from "./EvolutionRoute.styles";

const EvolutionRunRecordsPanel = lazy(() =>
  import("./EvolutionRunRecordsPanel").then((module) => ({
    default: module.EvolutionRunRecordsPanel,
  })),
);

export type EvolutionSupervisedRunsViewProps = {
  lang: Language;
  labels: EvolutionRunRecordsPanelLabels;
  runFilter: "all" | "success" | "failed";
  onRunFilterChange: (filter: "all" | "success" | "failed") => void;
  filteredRunsCount: number;
  totalRunsCount: number;
  hasRuns: boolean;
  runSuccessCount: number;
  runFailedCount: number;
  runPendingCount: number;
  runDeletableCount: number;
  selectedRunCount: number;
  runsWorkspaceStyle?: CSSProperties;
  separator: ReactNode;
  queueCollapsed: boolean;
  filteredRuns: EvolutionRun[];
  hasFilteredRuns: boolean;
  filteredRunsEmpty: boolean;
  runHeaderMessage: string;
  selectedRun: EvolutionRun | null;
  selectedRunIds: string[];
  visibleDeletableRunCount: number;
  allVisibleDeletableRunsSelected: boolean;
  relatedLibraryItems: EvolutionLibraryEntry[];
  relatedPendingItems: EvolutionLibraryEntry[];
  relatedProposalCount: number;
  runLocked: boolean;
  runRecordsFeedback: string;
  deleteRunRecordError: string;
  bulkDeleteRunRecordsError: string;
  bulkDeleteRunRecordsPending: boolean;
  deleteRunRecordPending: boolean;
  actionFeedback: string;
  actionError: string;
  actionPending: boolean;
  libraryFeedback: string;
  deleteProposalError: string;
  deleteProposalPending: boolean;
  onSelectVisibleRunRecords: () => void;
  onClearRunSelection: () => void;
  onBulkDeleteRunRecords: () => void;
  onReturnToOverview: () => void;
  onShowAllRuns: () => void;
  onSelectRun: (runId: string) => void;
  onToggleRunSelection: (run: EvolutionRun) => void;
  onRunAction: (runId: string, action: string) => void;
  onOpenProposal: (item: EvolutionLibraryEntry, view: EvolutionRunRecordsLibraryView) => void;
  onDeleteProposal: (sourceRun: string) => void;
  onDeleteRunRecord: (runId: string) => void;
};

/**
 * Supervised runs secondary view: command strip + run records workspace.
 */
export function EvolutionSupervisedRunsView({
  lang,
  labels,
  runFilter,
  onRunFilterChange,
  filteredRunsCount,
  totalRunsCount,
  hasRuns,
  runSuccessCount,
  runFailedCount,
  runPendingCount,
  runDeletableCount,
  selectedRunCount,
  runsWorkspaceStyle,
  separator,
  queueCollapsed,
  filteredRuns,
  hasFilteredRuns,
  filteredRunsEmpty,
  runHeaderMessage,
  selectedRun,
  selectedRunIds,
  visibleDeletableRunCount,
  allVisibleDeletableRunsSelected,
  relatedLibraryItems,
  relatedPendingItems,
  relatedProposalCount,
  runLocked,
  runRecordsFeedback,
  deleteRunRecordError,
  bulkDeleteRunRecordsError,
  bulkDeleteRunRecordsPending,
  deleteRunRecordPending,
  actionFeedback,
  actionError,
  actionPending,
  libraryFeedback,
  deleteProposalError,
  deleteProposalPending,
  onSelectVisibleRunRecords,
  onClearRunSelection,
  onBulkDeleteRunRecords,
  onReturnToOverview,
  onShowAllRuns,
  onSelectRun,
  onToggleRunSelection,
  onRunAction,
  onOpenProposal,
  onDeleteProposal,
  onDeleteRunRecord,
}: EvolutionSupervisedRunsViewProps) {
  const { t, statusLabel } = labels;
  return (
    <div className={styles.viewStack} data-vui-region="evolution-supervised-runs">
      <VSection
        className={`${styles.surface} ${styles.runsCommandStrip}`}
        eyebrow={t("recentRunPerformance")}
        title={t("runList")}
        actions={(
          <VTabs
            density="compact"
            className={styles.filterTabs}
            listClassName={styles.filterTabsList}
            triggerClassName={styles.filterTabsTrigger}
            aria-label={t("runList")}
            value={runFilter}
            onValueChange={(value) => {
              if (value === "all" || value === "success" || value === "failed") {
                onRunFilterChange(value);
              }
            }}
            items={([
              { id: "all" as const, label: t("allRuns") },
              { id: "success" as const, label: supervisedRunBucketLabel("success", lang, statusLabel) },
              { id: "failed" as const, label: supervisedRunBucketLabel("failed", lang, statusLabel) },
            ])}
          />
        )}
      >
        <div className={styles.runsCommandMetrics}>
          <article className={styles.compactFact}>
            <span>{t("runs")}</span>
            <strong>{hasRuns ? `${filteredRunsCount} / ${totalRunsCount}` : "0 / 0"}</strong>
          </article>
          <article className={styles.compactFact}>
            <span>{supervisedRunBucketLabel("success", lang, statusLabel)}</span>
            <strong>{runSuccessCount}</strong>
          </article>
          <article className={styles.compactFact}>
            <span>{supervisedRunBucketLabel("failed", lang, statusLabel)}</span>
            <strong>{runFailedCount}</strong>
          </article>
          <article className={styles.compactFact}>
            <span>{t("pendingReview")}</span>
            <strong>{runPendingCount}</strong>
          </article>
          <article className={styles.compactFact}>
            <span>{t("deletionAllowed")}</span>
            <strong>{runDeletableCount}</strong>
          </article>
          <article className={styles.compactFact}>
            <span>{t("selectedCount")}</span>
            <strong>{selectedRunCount}</strong>
          </article>
        </div>
      </VSection>

      <Suspense fallback={<p className={styles.noticeText}>{t("loading")}</p>}>
        <EvolutionRunRecordsPanel
          className={styles.runsWorkspace}
          style={runsWorkspaceStyle}
          lang={lang}
          labels={labels}
          separator={separator}
          queueCollapsed={queueCollapsed}
          filteredRuns={filteredRuns}
          hasRuns={hasRuns}
          hasFilteredRuns={hasFilteredRuns}
          filteredRunsEmpty={filteredRunsEmpty}
          runHeaderMessage={runHeaderMessage}
          selectedRun={selectedRun}
          selectedRunIds={selectedRunIds}
          visibleDeletableRunCount={visibleDeletableRunCount}
          allVisibleDeletableRunsSelected={allVisibleDeletableRunsSelected}
          relatedLibraryItems={relatedLibraryItems}
          relatedPendingItems={relatedPendingItems}
          relatedProposalCount={relatedProposalCount}
          runLocked={runLocked}
          runRecordsFeedback={runRecordsFeedback}
          deleteRunRecordError={deleteRunRecordError}
          bulkDeleteRunRecordsError={bulkDeleteRunRecordsError}
          bulkDeleteRunRecordsPending={bulkDeleteRunRecordsPending}
          deleteRunRecordPending={deleteRunRecordPending}
          actionFeedback={actionFeedback}
          actionError={actionError}
          actionPending={actionPending}
          libraryFeedback={libraryFeedback}
          deleteProposalError={deleteProposalError}
          deleteProposalPending={deleteProposalPending}
          onSelectVisibleRunRecords={onSelectVisibleRunRecords}
          onClearRunSelection={onClearRunSelection}
          onBulkDeleteRunRecords={onBulkDeleteRunRecords}
          onReturnToOverview={onReturnToOverview}
          onShowAllRuns={onShowAllRuns}
          onSelectRun={onSelectRun}
          onToggleRunSelection={onToggleRunSelection}
          onRunAction={onRunAction}
          onOpenProposal={onOpenProposal}
          onDeleteProposal={onDeleteProposal}
          onDeleteRunRecord={onDeleteRunRecord}
        />
      </Suspense>
    </div>
  );
}
