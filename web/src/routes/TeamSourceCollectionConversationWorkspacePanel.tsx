/**
 * Source-collection conversation / raw-records workspace body.
 * Wave 8K: extracted from TeamsRoute.tsx for domain componentization.
 */
import type { ReactNode } from "react";
import { Play, RefreshCw, Search } from "lucide-react";

import type { Team } from "../api/types";
import { VButton } from "../components/vui";
import {
  TeamSourceEmptyState,
  TeamSourceResultItem,
  TeamSourceResultList,
  type TeamSourceEmptyStateFact,
} from "../components/vui/product/team-management";
import {
  sourceCollectionRecordProvenance,
  sourceCollectionSourceTypeLabel,
} from "./teams/source-collection/evidenceModel";
import {
  candidateSourceQualityAssessmentSummary,
  sourceCollectionResultTone,
  sourceCollectionSimpleRecordStatusLabel,
} from "./teams/source-collection/presentationModel";
import {
  sourceCollectionRunCandidateMetric,
  sourceCollectionRunHasUsableRecords,
  sourceCollectionRunRecordCount,
  sourceCollectionRunTitleLabel,
} from "./teams/source-collection/runModel";
import type { SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionConversationPanel } from "./TeamSourceCollectionConversationPanel";

type Lang = "zh" | "en";

export type TeamSourceCollectionConversationWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPageItems: (stageId: SourceCollectionStageModuleId, items: any[]) => { items: any[]; start: number; end: number };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionFilteredRecords: any[];
  sourceCollectionRecordsDataLoading: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionRecords: any[];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionRun: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionHistoricalRunWithRecords: any;
  sourceCollectionLoadingText: string;
  sourceCollectionRawRecordCount: number;
  sourceCollectionRecordClickableSourceCount: number;
  sourceCollectionRecordLocalFileCount: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageModules: Array<{ id: string; actionLabel?: string; actionDisabled?: boolean; onAction?: () => void }>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageActionReadinessFor: (stageId: SourceCollectionStageModuleId) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionDraft: { title: string };
  sourceCollectionCollectedCountLabel: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionStorageArtifacts: any;
  sourceCollectionBoardNextStepLabel: string;
  sourceCollectionSourceFilter: string;
  setSourceCollectionSourceFilter: (value: any) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionRecordFilterCounts: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionFilterBar: (...args: any[]) => ReactNode;
  sourceCollectionCollectedCountText: string;
  sourceCollectionDisplayedCandidateCountText: string;
  sourceCollectionPendingCandidateImportCount: number;
  sourceCollectionRecordMissingSourceCount: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionPagination: (stageId: SourceCollectionStageModuleId, total: number) => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidatesByRecordId: Map<string, any>;
  selectedSourceCollectionCandidateId: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectSourceCollectionCandidate: (candidate: any) => void;
  setSelectedSourceCollectionRunId: (runId: string) => void;
};

export function TeamSourceCollectionConversationWorkspacePanel(props: TeamSourceCollectionConversationWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionPageItems,
    sourceCollectionFilteredRecords,
    sourceCollectionRecordsDataLoading,
    sourceCollectionRecords,
    selectedSourceCollectionRun,
    sourceCollectionHistoricalRunWithRecords,
    sourceCollectionLoadingText,
    sourceCollectionRawRecordCount,
    sourceCollectionRecordClickableSourceCount,
    sourceCollectionRecordLocalFileCount,
    sourceCollectionStageModules,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionDraft,
    sourceCollectionCollectedCountLabel,
    selectedSourceCollectionStorageArtifacts,
    sourceCollectionBoardNextStepLabel,
    sourceCollectionSourceFilter,
    setSourceCollectionSourceFilter,
    sourceCollectionActionDisabledTitle,
    sourceCollectionRecordFilterCounts,
    renderSourceCollectionFilterBar,
    sourceCollectionCollectedCountText,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionPendingCandidateImportCount,
    sourceCollectionRecordMissingSourceCount,
    renderSourceCollectionPagination,
    sourceCollectionCandidatesByRecordId,
    selectedSourceCollectionCandidateId,
    selectSourceCollectionCandidate,
    setSelectedSourceCollectionRunId,
  } = props;


    const pagedResults = sourceCollectionPageItems("finding", sourceCollectionFilteredRecords);
    const visibleResults = pagedResults.items;
    const sourceCollectionConversationHasVisibleResults = visibleResults.length > 0;
    const sourceCollectionConversationCompact = !sourceCollectionConversationHasVisibleResults;
    const selectedRunEmptyWithHistorical = Boolean(
      !sourceCollectionRecordsDataLoading
      && !sourceCollectionRecords.length
      && selectedSourceCollectionRun
      && !sourceCollectionRunHasUsableRecords(selectedSourceCollectionRun)
      && sourceCollectionHistoricalRunWithRecords
      && sourceCollectionHistoricalRunWithRecords.runId !== selectedSourceCollectionRun.runId,
    );
    const rawRecordRangeText = sourceCollectionRecordsDataLoading
      ? sourceCollectionLoadingText
      : `${pagedResults.start}-${pagedResults.end} / ${sourceCollectionFilteredRecords.length}`;
    const rawRecordHeaderText = sourceCollectionRecordsDataLoading
      ? (lang === "zh" ? "加载中" : "Loading")
      : lang === "zh"
        ? `${visibleResults.length}/${sourceCollectionFilteredRecords.length}，共 ${sourceCollectionRawRecordCount}`
        : `${visibleResults.length}/${sourceCollectionFilteredRecords.length}, ${sourceCollectionRawRecordCount} total`;
    const sourceCollectionRecordClickableSourceCountText = sourceCollectionRecordsDataLoading
      ? sourceCollectionLoadingText
      : String(sourceCollectionRecordClickableSourceCount);
    const sourceCollectionRecordLocalFileCountText = sourceCollectionRecordsDataLoading
      ? sourceCollectionLoadingText
      : String(sourceCollectionRecordLocalFileCount);
    const findingStageModule = sourceCollectionStageModules.find((module: any) => module.id === "finding");
    const findingStageReadiness = sourceCollectionStageActionReadinessFor("finding");
    const findingStageActionLabel = findingStageModule?.actionLabel ?? (lang === "zh" ? "开始搜索" : "Start search");
    const rawRecordEmptyFacts: TeamSourceEmptyStateFact[] = [
      {
        key: "run",
        label: lang === "zh" ? "当前批次" : "Run",
        value: sourceCollectionRecordsDataLoading
          ? sourceCollectionLoadingText
          : sourceCollectionRunTitleLabel(selectedSourceCollectionRun?.title || sourceCollectionDraft.title, lang),
      },
      {
        key: "records",
        label: lang === "zh" ? "原始资料" : "Raw records",
        value: sourceCollectionRecordsDataLoading ? sourceCollectionLoadingText : sourceCollectionCollectedCountLabel,
      },
      {
        key: "files",
        label: lang === "zh" ? "文件产物" : "Files",
        value: selectedSourceCollectionStorageArtifacts
          ? (lang === "zh" ? "已连接本轮产物" : "Artifacts linked")
          : (lang === "zh" ? "搜索完成后生成" : "Created after search"),
      },
      {
        key: "next",
        label: lang === "zh" ? "下一步" : "Next",
        value: sourceCollectionBoardNextStepLabel,
      },
    ];
    const rawRecordEmptyTitle = sourceCollectionRecordsDataLoading
      ? (lang === "zh" ? "正在读取当前批次资料" : "Loading run records")
      : sourceCollectionRecords.length
        ? (lang === "zh" ? "当前筛选没有资料" : "No records match this filter")
        : selectedSourceCollectionRun
          ? (lang === "zh" ? "当前批次还没有原始资料" : "This run has no raw records yet")
          : (lang === "zh" ? "还没有开始资料搜集" : "Source collection has not started");
    const rawRecordEmptyDescription = sourceCollectionRecordsDataLoading
      ? (lang === "zh" ? "正在读取记录、候选和文件产物，完成后会在这里进入列表视图。" : "Records, candidates, and artifacts are loading.")
      : sourceCollectionRecords.length
        ? (lang === "zh" ? "资料已经读取完成，但当前来源过滤没有命中；切回全部即可继续查看。" : "Records are loaded, but the selected source filter has no matches.")
        : (lang === "zh"
            ? "点击开始搜索后，原始资料、候选资料和文件产物会按同一批次写入这里。"
            : "Start a search to write raw records, candidates, and file artifacts into this run.");
    const rawRecordEmptyActions = sourceCollectionRecordsDataLoading
      ? null
      : sourceCollectionRecords.length
        ? (
            <VButton
              type="button"
              density="compact"
              variant="secondary"
              icon={<RefreshCw size={13} />}
              isDisabled={sourceCollectionSourceFilter === "all"}
              onPress={() => setSourceCollectionSourceFilter("all")}
            >
              {lang === "zh" ? "查看全部来源" : "Show all sources"}
            </VButton>
          )
        : (
            <VButton
              type="button"
              density="compact"
              variant="primary"
              icon={<Play size={13} />}
              isDisabled={findingStageModule?.actionDisabled ?? true}
              onPress={findingStageModule?.onAction}
              title={sourceCollectionActionDisabledTitle(findingStageReadiness, findingStageActionLabel)}
            >
              {findingStageActionLabel}
            </VButton>
          );
    return (
      <TeamSourceCollectionConversationPanel
        lang={lang}
        rangeText={rawRecordRangeText}
        headerText={rawRecordHeaderText}
        filterBar={renderSourceCollectionFilterBar(sourceCollectionRecordFilterCounts, lang === "zh" ? "资料来源过滤" : "Source filters", sourceCollectionRecordsDataLoading)}
        stats={[
          { key: "raw", label: lang === "zh" ? "原始记录" : "raw records", value: sourceCollectionCollectedCountText },
          { key: "imported", label: lang === "zh" ? "已入候选" : "imported to candidates", value: sourceCollectionDisplayedCandidateCountText },
          { key: "clickable", label: lang === "zh" ? "可点击来源" : "clickable sources", value: sourceCollectionRecordClickableSourceCountText },
          { key: "local", label: lang === "zh" ? "本地文件" : "local files", value: sourceCollectionRecordLocalFileCountText },
        ]}
        pendingCandidateImportCount={sourceCollectionPendingCandidateImportCount}
        missingSourceCount={sourceCollectionRecordMissingSourceCount}
        compact={sourceCollectionConversationCompact}
        pagination={sourceCollectionRecordsDataLoading ? null : renderSourceCollectionPagination("finding", sourceCollectionFilteredRecords.length)}
      >
          {sourceCollectionConversationHasVisibleResults ? (
            <TeamSourceResultList ariaLabel={lang === "zh" ? "原始资料记录" : "Raw source records"}>
              {visibleResults.map((record: any) => {
                const linkedCandidate = sourceCollectionCandidatesByRecordId.get(record.recordId) ?? null;
                const sourceQualitySummary = linkedCandidate ? candidateSourceQualityAssessmentSummary(linkedCandidate) : null;
                const provenance = sourceCollectionRecordProvenance(record, lang);
                const selected = Boolean(linkedCandidate && selectedSourceCollectionCandidateId === linkedCandidate.candidateId);
                const resultStatusLabel = sourceCollectionSimpleRecordStatusLabel(linkedCandidate, sourceQualitySummary, lang);
                const resultStatusRaw = linkedCandidate
                  ? (sourceQualitySummary?.decision || linkedCandidate.qualityStatus || linkedCandidate.currentState)
                  : "candidate_pending";
                const resultScoreLabel = sourceQualitySummary
                  ? `${sourceQualitySummary.overallScore}/100`
                  : linkedCandidate
                    ? (lang === "zh" ? "已提炼" : "extracted")
                    : (lang === "zh" ? "待提炼" : "extract");
                return (
                  <TeamSourceResultItem
                    key={record.recordId}
                    tone={linkedCandidate ? sourceCollectionResultTone(linkedCandidate.qualityStatus) : "warning"}
                    statusLabel={resultStatusLabel}
                    statusTitle={resultStatusRaw}
                    title={record.title || record.recordId}
                    titleTooltip={[record.title || record.recordId, record.summary || ""].filter(Boolean).join("\n")}
                    meta={[
                      { key: "type", label: sourceCollectionSourceTypeLabel(record.sourceType, lang) },
                      { key: "score", label: resultScoreLabel },
                    ]}
                    source={{
                      label: provenance.label,
                      value: provenance.value,
                      href: provenance.href,
                      title: provenance.href || provenance.value,
                      missing: provenance.kind === "missing",
                    }}
                    selected={selected}
                    onActivate={linkedCandidate ? () => selectSourceCollectionCandidate(linkedCandidate) : undefined}
                    activateTitle={linkedCandidate ? (lang === "zh" ? "点击查看候选详情" : "Open candidate detail") : undefined}
                  />
                );
              })}
            </TeamSourceResultList>
          ) : selectedRunEmptyWithHistorical && sourceCollectionHistoricalRunWithRecords ? (
            <TeamSourceEmptyState
              title={lang === "zh" ? "当前批次暂无资料" : "This run has no records"}
              description={lang === "zh"
                ? `上一轮有资料：${sourceCollectionRunRecordCount(sourceCollectionHistoricalRunWithRecords)} 条资料 / ${sourceCollectionRunCandidateMetric(sourceCollectionHistoricalRunWithRecords)} 个候选。`
                : `Another run has records: ${sourceCollectionRunRecordCount(sourceCollectionHistoricalRunWithRecords)} records / ${sourceCollectionRunCandidateMetric(sourceCollectionHistoricalRunWithRecords)} candidates.`}
              facts={rawRecordEmptyFacts}
              actions={(
                <VButton
                  type="button"
                  density="compact"
                  variant="secondary"
                  icon={<Search size={13} />}
                  onPress={() => setSelectedSourceCollectionRunId(sourceCollectionHistoricalRunWithRecords.runId)}
                >
                  {lang === "zh" ? "切换到有资料批次" : "Show run with records"}
                </VButton>
              )}
            />
          ) : (
            <TeamSourceEmptyState
              title={rawRecordEmptyTitle}
              description={rawRecordEmptyDescription}
              facts={rawRecordEmptyFacts}
              actions={rawRecordEmptyActions}
              footer={lang === "zh"
                ? "资料列表只展示真实写入的记录；没有记录时不再撑出空白列表。"
                : "The source list only renders real records; empty runs stay compact."}
            />
          )}
      </TeamSourceCollectionConversationPanel>
    );

}
