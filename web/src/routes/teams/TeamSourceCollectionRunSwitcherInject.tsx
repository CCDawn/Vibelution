/**
 * SC inject: run switcher options, empty-run hint, and historical-run jump.
 */
import type { TeamSourceCollectionRunSwitcherRun } from "../TeamSourceCollectionRunSwitcherPanel";
import { TeamSourceCollectionRunSwitcherPanel } from "./teamLazyPanels";
import type { DataProcessingRunListPayload } from "../../api/types";
import {
  buildSourceCollectionRunSwitcherOptions,
  resolveSourceCollectionRunSwitcherHint,
  sourceCollectionRunCandidateMetric,
  sourceCollectionRunHasUsableRecords,
  sourceCollectionRunRecordCount,
  type SourceCollectionRunSummaryValue,
} from "./source-collection/runModel";
import { sourceCollectionStatusLabel } from "./source-collection/presentationModel";

export type TeamSourceCollectionRunSwitcherInjectProps = {
  lang: "zh" | "en";
  runs: DataProcessingRunListPayload["runs"];
  selectedRun: SourceCollectionRunSummaryValue;
  selectedRunId: string;
  historicalRunWithRecords: SourceCollectionRunSummaryValue;
  showingHistoricalRunByDefault: boolean;
  recordsLoading: boolean;
  loadingText: string;
  runStatusLabelSource?: string;
  onRunChange: (runId: string) => void;
};

export function TeamSourceCollectionRunSwitcherInject({
  lang,
  runs,
  selectedRun,
  selectedRunId,
  historicalRunWithRecords,
  showingHistoricalRunByDefault,
  recordsLoading,
  loadingText,
  runStatusLabelSource,
  onRunChange,
}: TeamSourceCollectionRunSwitcherInjectProps) {
  if (!runs.length) {
    return null;
  }

  const selectedRecordCount = sourceCollectionRunRecordCount(selectedRun);
  const selectedCandidateCount = sourceCollectionRunCandidateMetric(selectedRun);
  const selectedRunIsEmpty = Boolean(selectedRun && !sourceCollectionRunHasUsableRecords(selectedRun));
  const canSwitchToHistoricalRun = Boolean(
    historicalRunWithRecords
    && historicalRunWithRecords.runId !== selectedRun?.runId,
  );
  const runOptions: TeamSourceCollectionRunSwitcherRun[] = buildSourceCollectionRunSwitcherOptions(runs, lang);
  const hint = resolveSourceCollectionRunSwitcherHint({
    lang,
    recordsLoading,
    showingHistoricalRunByDefault,
    selectedRunIsEmpty,
    canSwitchToHistoricalRun,
  });

  return (
    <TeamSourceCollectionRunSwitcherPanel
      lang={lang}
      runs={runOptions}
      selectedRunId={selectedRunId}
      hint={hint}
      recordMetric={recordsLoading ? loadingText : selectedRecordCount}
      candidateMetric={recordsLoading ? loadingText : selectedCandidateCount}
      statusLabel={sourceCollectionStatusLabel(runStatusLabelSource || selectedRun?.status, lang)}
      canSwitchToHistoricalRun={selectedRunIsEmpty && canSwitchToHistoricalRun && Boolean(historicalRunWithRecords)}
      onRunChange={onRunChange}
      onSwitchToHistoricalRun={() => {
        if (historicalRunWithRecords) {
          onRunChange(historicalRunWithRecords.runId);
        }
      }}
    />
  );
}
