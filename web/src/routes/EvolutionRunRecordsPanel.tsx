import { ArrowUpRight, CheckCircle2, LoaderCircle, Sparkles, Trash2 } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import type { EvolutionLibraryEntry, EvolutionRun } from "../api/types";
import { VButton, VCheckbox, VTooltip } from "../components/vui";
import type { Language, TranslationKey } from "../i18n/dictionary";
import { buildSupervisedRunRecordDisplay, supervisedDecisionLabel } from "./supervisedRunRecordLabel";
import styles from "./EvolutionRunRecordsPanel.styles";

type Lang = Language;
export type EvolutionRunRecordsLibraryView = "items" | "pending";

export type EvolutionRunRecordsPanelLabels = {
  t: (key: TranslationKey) => string;
  statusLabel: (status: string) => string;
  decisionLabel: (decision: string) => string;
  riskLabel: (risk: string) => string;
  proposalActionLabel: (action: string) => string;
};

export type EvolutionRunRecordsPanelProps = {
  className: string;
  style?: CSSProperties;
  lang: Lang;
  labels: EvolutionRunRecordsPanelLabels;
  separator: ReactNode;
  queueCollapsed: boolean;
  filteredRuns: EvolutionRun[];
  hasRuns: boolean;
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

function supervisedRunBucketLabel(status: string, lang: Lang, statusLabel: (status: string) => string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (normalized === "failed") {
    return lang === "zh" ? "异常收口" : "closed with issues";
  }
  return statusLabel(status);
}

function supervisedProposalStatusLabel(status: string, fallback: string, lang: Lang) {
  const raw = String(status || fallback || "").trim();
  const normalized = raw.toLowerCase();
  if (normalized === "rejected" || normalized === "reject") {
    return lang === "zh" ? "未入库" : "not stored";
  }
  if (normalized === "missing") {
    return lang === "zh" ? "无提案" : "no proposal";
  }
  return fallback || raw || "--";
}

function displaySupervisedRunStatus(run: EvolutionRun, lang: Lang, statusLabel: (status: string) => string) {
  return run.runSemantics?.runStatusLabel || supervisedRunBucketLabel(run.status, lang, statusLabel);
}

function displaySupervisedTechnicalText(
  value: string,
  decision: string,
  lang: Lang,
  decisionLabel: (decision: string) => string,
) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const decisionText = supervisedDecisionLabel(decision, lang, decisionLabel);
  const rejectedText = lang === "zh" ? "未入库" : "not stored";
  const riskGateText = lang === "zh" ? "风险 gate" : "risk gate";
  const judgmentNoteText = lang === "zh" ? "判定说明:" : "judgment note:";
  return text
    .replace(/\bdecision\s*=\s*REJECT\b/gi, lang === "zh" ? `治理结论=${decisionText}` : `governance=${decisionText}`)
    .replace(/\bagent_judgment\s+fail:?/gi, judgmentNoteText)
    .replace(/\bREJECT\b/g, decisionText)
    .replace(/\brejected\b/g, rejectedText)
    .replace(/失败\s*gate/g, riskGateText)
    .replace(/失败项/g, lang === "zh" ? "问题项" : "issue items")
    .replace(/监督结论/g, lang === "zh" ? "治理结论" : "governance result");
}

function displaySupervisedRunSummary(
  run: EvolutionRun,
  lang: Lang,
  decisionLabel: (decision: string) => string,
) {
  return displaySupervisedTechnicalText(run.summary, run.decision, lang, decisionLabel);
}

function compactCaseObject(value: Record<string, unknown> | undefined) {
  if (!value || Object.keys(value).length === 0) {
    return "";
  }
  const text = JSON.stringify(value);
  return text.length > 160 ? `${text.slice(0, 159)}...` : text;
}

export function EvolutionRunRecordsPanel({
  className,
  style,
  lang,
  labels,
  separator,
  queueCollapsed,
  filteredRuns,
  hasRuns,
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
}: EvolutionRunRecordsPanelProps) {
  const { t, statusLabel, decisionLabel, riskLabel, proposalActionLabel } = labels;
  const selectedRunIdSet = new Set(selectedRunIds);
  const displayDecisionLabel = (decision: string) => supervisedDecisionLabel(decision, lang, decisionLabel);
  const queueClassName = queueCollapsed
    ? `${styles.surface} ${styles.runQueuePanel} ${styles.paneCollapsed}`
    : `${styles.surface} ${styles.runQueuePanel}`;

  const renderProposalLink = (item: EvolutionLibraryEntry, view: EvolutionRunRecordsLibraryView) => (
    <article key={item.id} className={styles.relatedRow}>
      <div className={styles.listRowTop}>
        <strong>{item.title}</strong>
        <span>{statusLabel(item.proposalStatus)}</span>
      </div>
      <p>{item.changeSummary || item.headline}</p>
      <div className={styles.actionRow}>
        <VButton
          type="button"
          className={styles.inlineAction}
          onClick={() => onOpenProposal(item, view)}
        >
          <ArrowUpRight size={15} />
          {t("openProposal")}
        </VButton>
        <VButton
          type="button"
          variant="danger"
          className={styles.inlineAction}
          isDisabled={!item.canDelete || deleteProposalPending}
          tooltip={lang === "zh" ? "删除这条提案记录。" : "Delete this proposal record."}
          disabledReason={!item.canDelete ? item.deleteBlockReason || (lang === "zh" ? "当前提案不可删除。" : "This proposal cannot be deleted.") : deleteProposalPending ? (lang === "zh" ? "提案正在删除。" : "Proposal deletion is in progress.") : undefined}
          onClick={() => onDeleteProposal(item.sourceRun)}
        >
          <Trash2 size={15} />
          {t("deleteProposal")}
        </VButton>
      </div>
      {!item.canDelete && item.deleteBlockReason ? (
        <p>{item.deleteBlockReason}</p>
      ) : null}
    </article>
  );

  return (
    <div className={className} style={style}>
      <section className={queueClassName} aria-hidden={queueCollapsed}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.eyebrow}>{t("runQueue")}</p>
            <h2 className={styles.sectionTitle}>{t("runs")}</h2>
          </div>
          <span className={styles.secondaryPill}>{filteredRuns.length}</span>
        </div>
        {hasFilteredRuns ? (
          <div className={styles.bulkToolbar}>
            <div className={styles.bulkToolbarText}>
              <strong>{t("selectedCount")}</strong>
              <span>{selectedRunIds.length}</span>
            </div>
            <div className={styles.actionRow}>
              <VButton
                type="button"
                className={styles.inlineAction}
                isDisabled={visibleDeletableRunCount === 0 || allVisibleDeletableRunsSelected}
                disabledReason={visibleDeletableRunCount === 0 ? (lang === "zh" ? "当前列表没有可删除的运行记录。" : "There are no deletable run records in this list.") : (lang === "zh" ? "当前可删除记录已全部选中。" : "All deletable records are already selected.")}
                onClick={onSelectVisibleRunRecords}
              >
                <CheckCircle2 size={15} />
                {t("selectVisibleRuns")}
              </VButton>
              <VButton
                type="button"
                className={styles.inlineAction}
                isDisabled={selectedRunIds.length === 0}
                disabledReason={lang === "zh" ? "当前没有已选运行记录。" : "No run records are selected."}
                onClick={onClearRunSelection}
              >
                {t("clearSelection")}
              </VButton>
              <VButton
                type="button"
                variant="danger"
                className={styles.inlineAction}
                isDisabled={selectedRunIds.length === 0 || bulkDeleteRunRecordsPending}
                tooltip={t("runBatchDeleteHint")}
                disabledReason={selectedRunIds.length === 0 ? (lang === "zh" ? "先选择运行记录。" : "Select run records first.") : bulkDeleteRunRecordsPending ? (lang === "zh" ? "批量删除正在进行。" : "Bulk deletion is in progress.") : undefined}
                onClick={onBulkDeleteRunRecords}
              >
                {bulkDeleteRunRecordsPending ? <LoaderCircle size={15} /> : <Trash2 size={15} />}
                {t("deleteSelectedRuns")}
              </VButton>
            </div>
            <p className={styles.bulkToolbarHint}>{t("runBatchDeleteHint")}</p>
          </div>
        ) : (
          <p className={styles.noticeText}>{runHeaderMessage}</p>
        )}
        {runRecordsFeedback ? <p className={styles.feedbackText}>{runRecordsFeedback}</p> : null}
        {deleteRunRecordError ? <p className={styles.errorText}>{deleteRunRecordError}</p> : null}
        {bulkDeleteRunRecordsError ? <p className={styles.errorText}>{bulkDeleteRunRecordsError}</p> : null}
        {!hasRuns ? (
          <div className={styles.structuredEmptyState}>
            <h3>{t("noSupervisedRunsYet")}</h3>
            <p>{t("noRunsRecordedHint")}</p>
            <div className={styles.actionRow}>
              <VButton
                type="button"
                className={styles.inlineAction}
                onClick={onReturnToOverview}
              >
                <ArrowUpRight size={15} />
                {t("returnToOverview")}
              </VButton>
            </div>
          </div>
        ) : filteredRunsEmpty ? (
          <div className={styles.structuredEmptyState}>
            <h3>{t("noRunMatches")}</h3>
            <p>{t("runFilterEmptyHint")}</p>
            <div className={styles.actionRow}>
              <VButton
                type="button"
                className={styles.inlineAction}
                onClick={onShowAllRuns}
              >
                {t("allRuns")}
              </VButton>
            </div>
          </div>
        ) : (
          <div className={styles.runListScrollable}>
            {filteredRuns.map((run) => {
              const runDisplay = buildSupervisedRunRecordDisplay(run, lang, {
                statusLabel,
                decisionLabel: displayDecisionLabel,
              });
              return (
                <article
                  key={run.id}
                  className={
                    selectedRun?.id === run.id
                      ? `${styles.runItem} ${styles.runItemActive} ${styles.runRecordCard}`
                      : `${styles.runItem} ${styles.runRecordCard}`
                  }
                >
                  <div className={styles.selectionBar}>
                    <VCheckbox
                      className={styles.batchToggle}
                      isSelected={selectedRunIdSet.has(run.id)}
                      isDisabled={!run.canDelete}
                      onChange={() => onToggleRunSelection(run)}
                    >
                      {t("selectRunForDelete")}
                    </VCheckbox>
                    <span className={run.canDelete ? styles.secondaryPill : styles.statusPill}>
                      {run.canDelete ? t("deletionAllowed") : t("deletionBlocked")}
                    </span>
                  </div>
                  <VButton
                    type="button"
                    contentLayout="plain"
                    className={styles.runCardButton}
                    tooltip={run.nextAction || undefined}
                    onClick={() => onSelectRun(run.id)}
                  >
                    <div className={`${styles.listRowTop} ${styles.runRecordTitleRow}`}>
                      <div className={styles.runRecordIdentity}>
                        <strong>{runDisplay.title}</strong>
                        <span>{runDisplay.idLabel}</span>
                      </div>
                      <span className={styles.secondaryPill}>{displayDecisionLabel(run.decision)}</span>
                    </div>
                    <div className={styles.metaRow}>
                      <span>{displaySupervisedRunStatus(run, lang, statusLabel)}</span>
                      <span>{supervisedProposalStatusLabel(run.outcomeSemantics.proposalStatus, run.outcomeSemantics.proposalStatusLabel, lang)}</span>
                    </div>
                    <div className={styles.scoreRow}>
                      <span>{runDisplay.subtitle}</span>
                      <strong>{run.candidateScore}</strong>
                    </div>
                    <p>{displaySupervisedRunSummary(run, lang, decisionLabel)}</p>
                    <div className={styles.cardFooter}>
                      <span>{riskLabel(run.riskLevel)}</span>
                      <span>
                        {displaySupervisedTechnicalText(run.nextAction, run.decision, lang, decisionLabel) || "--"}
                      </span>
                    </div>
                  </VButton>
                  {!run.canDelete && run.deleteBlockReason ? (
                    <p className={styles.noticeText}>{run.deleteBlockReason}</p>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </section>

      {separator}

      <section className={`${styles.surface} ${styles.runDetailPanel}`}>
        {selectedRun ? (
          <>
            <div className={styles.detailHeader}>
              <div>
                <p className={styles.eyebrow}>{t("runDetail")}</p>
                <h2 className={styles.detailTitle}>
                  {buildSupervisedRunRecordDisplay(selectedRun, lang, { statusLabel, decisionLabel: displayDecisionLabel }).title}
                </h2>
                <p className={styles.detailSubtleId}>{selectedRun.id}</p>
              </div>
              <div className={styles.detailHeaderActions}>
                <span className={styles.secondaryPill}>{displayDecisionLabel(selectedRun.decision)}</span>
                <span className={styles.secondaryPill}>
                  {supervisedProposalStatusLabel(
                    selectedRun.outcomeSemantics.proposalStatus,
                    selectedRun.outcomeSemantics.proposalStatusLabel,
                    lang,
                  )}
                </span>
              </div>
            </div>

            <div className={styles.runDetailOverview}>
              <div className={styles.runScorePanel}>
                <span>{t("candidateScore")}</span>
                <p className={styles.detailLead}>{selectedRun.candidateScore}</p>
                <p>{displaySupervisedRunSummary(selectedRun, lang, decisionLabel)}</p>
                <div className={styles.runScoreDiagnosis}>
                  <span>{t("diagnosis")}</span>
                  <p>{selectedRun.diagnosis}</p>
                </div>
                <div className={styles.runScoreFacts}>
                  <span>
                    {t("baselineScore")}
                    <strong>{selectedRun.baselineScore}</strong>
                  </span>
                  <span>
                    {t("scoreDelta")}
                    <strong>{selectedRun.deltaScore}</strong>
                  </span>
                  <span>
                    {t("linkedItems")}
                    <strong>{relatedProposalCount}</strong>
                  </span>
                </div>
              </div>
              <div className={styles.runSignalStack}>
                <h3>{t("resultLayersTitle")}</h3>
                <div className={styles.runSignalGrid}>
                  <article className={styles.compactFact}>
                    <span>{t("runLayer")}</span>
                    <strong>{displaySupervisedRunStatus(selectedRun, lang, statusLabel)}</strong>
                  </article>
                  <article className={styles.compactFact}>
                    <span>{t("decision")}</span>
                    <strong>{displayDecisionLabel(selectedRun.outcomeSemantics.decision || selectedRun.decision)}</strong>
                  </article>
                  <article className={styles.compactFact}>
                    <span>{t("proposalLayer")}</span>
                    <strong>
                      {supervisedProposalStatusLabel(
                        selectedRun.outcomeSemantics.proposalStatus,
                        selectedRun.outcomeSemantics.proposalStatusLabel,
                        lang,
                      )}
                    </strong>
                  </article>
                  <article className={styles.compactFact}>
                    <span>{t("runtimeLayer")}</span>
                    <strong>{selectedRun.outcomeSemantics.runtimeEffectLabel}</strong>
                  </article>
                  <article className={styles.compactFact}>
                    <span>{t("nextRecommendedAction")}</span>
                    <VTooltip content={selectedRun.runSemantics.nextAction || "--"} width="wide">
                      <strong tabIndex={0}>
                        {displaySupervisedTechnicalText(selectedRun.runSemantics.nextAction, selectedRun.decision, lang, decisionLabel) || "--"}
                      </strong>
                    </VTooltip>
                  </article>
                  <article className={styles.compactFact}>
                    <span>{t("riskLevel")}</span>
                    <strong>{riskLabel(selectedRun.riskLevel)}</strong>
                  </article>
                </div>
              </div>
            </div>

            <div className={`${styles.detailSection} ${styles.detailSectionCompact}`}>
              <div className={styles.runRuntimeNote}>
                <VTooltip content={selectedRun.outcomeSemantics.runtimeExplanation} width="wide">
                  <p tabIndex={0}>
                    {displaySupervisedTechnicalText(selectedRun.outcomeSemantics.runtimeExplanation, selectedRun.decision, lang, decisionLabel)}
                  </p>
                </VTooltip>
                {selectedRun.riskReasons.length > 0 ? (
                  <VTooltip content={selectedRun.riskReasons.join(" / ")} width="wide">
                    <p tabIndex={0}>
                      {displaySupervisedTechnicalText(selectedRun.riskReasons.join(" / "), selectedRun.decision, lang, decisionLabel)}
                    </p>
                  </VTooltip>
                ) : null}
              </div>
              {selectedRun.availableActions.length > 0 ? (
                <div className={styles.actionRow}>
                  {selectedRun.availableActions.map((action) => (
                    <VButton
                      key={action}
                      type="button"
                      className={styles.inlineAction}
                      isDisabled={runLocked || actionPending}
                      disabledReason={runLocked ? (lang === "zh" ? "运行仍被锁定，暂不能执行提案动作。" : "The run is locked, so proposal actions are unavailable.") : actionPending ? (lang === "zh" ? "提案动作正在执行。" : "A proposal action is in progress.") : undefined}
                      onClick={() => onRunAction(selectedRun.id, action)}
                    >
                      <Sparkles size={15} />
                      {proposalActionLabel(action)}
                    </VButton>
                  ))}
                </div>
              ) : null}
              {actionFeedback ? <p className={styles.feedbackText}>{actionFeedback}</p> : null}
              {actionError ? <p className={styles.errorText}>{actionError}</p> : null}
            </div>

            <div className={styles.detailSection}>
              <h3>{t("caseDiagnostics")}</h3>
              {selectedRun.caseDiagnostics.length > 0 ? (
                <div className={styles.relatedList}>
                  {selectedRun.caseDiagnostics.slice(0, 3).map((item) => (
                    <article key={item.caseId || item.summary} className={styles.relatedRow}>
                      <div className={styles.listRowTop}>
                        <strong>{item.caseId || "--"}</strong>
                        <span>{item.caseType && item.caseType !== "static" ? item.caseType : item.decisionSignal || "--"}</span>
                      </div>
                      <p>{item.summary}</p>
                      {compactCaseObject(item.expectedFinalState) ? (
                        <p>expected final: {compactCaseObject(item.expectedFinalState)}</p>
                      ) : null}
                      {compactCaseObject(item.expectedInfeasibleOutcome) ? (
                        <p>expected infeasible: {compactCaseObject(item.expectedInfeasibleOutcome)}</p>
                      ) : null}
                    </article>
                  ))}
                </div>
              ) : (
                <p>{t("noCaseDiagnostics")}</p>
              )}
            </div>

            <div className={styles.detailSection}>
              <h3>{t("outputsWorthPromoting")}</h3>
              {relatedLibraryItems.length === 0 && relatedPendingItems.length === 0 ? (
                <p>{t("noPromotionCandidates")}</p>
              ) : (
                <div className={styles.relatedList}>
                  {relatedLibraryItems.map((item) => renderProposalLink(item, "items"))}
                  {relatedPendingItems.map((item) => renderProposalLink(item, "pending"))}
                </div>
              )}
              {libraryFeedback ? <p className={styles.feedbackText}>{libraryFeedback}</p> : null}
              {deleteProposalError ? <p className={styles.errorText}>{deleteProposalError}</p> : null}
            </div>

            <div className={`${styles.detailSection} ${styles.dangerDetailSection}`}>
              <h3>{t("deleteAndCleanup")}</h3>
              <div className={styles.relatedList}>
                <article className={styles.relatedRow}>
                  <strong>{selectedRun.canDelete ? t("deletionAllowed") : t("deletionBlocked")}</strong>
                  <span>
                    {selectedRun.canDelete
                      ? t("deleteRunRecord")
                      : selectedRun.deleteBlockReason || "--"}
                  </span>
                </article>
              </div>
              <p>{t("runDeleteImpact")}</p>
              <div className={styles.actionRow}>
                <VButton
                  type="button"
                  variant="danger"
                  className={styles.inlineAction}
                  isDisabled={!selectedRun.canDelete || deleteRunRecordPending}
                  tooltip={t("runDeleteImpact")}
                  disabledReason={!selectedRun.canDelete ? selectedRun.deleteBlockReason || (lang === "zh" ? "当前运行记录不可删除。" : "This run record cannot be deleted.") : deleteRunRecordPending ? (lang === "zh" ? "运行记录正在删除。" : "Run record deletion is in progress.") : undefined}
                  onClick={() => onDeleteRunRecord(selectedRun.id)}
                >
                  {deleteRunRecordPending ? <LoaderCircle size={15} /> : <Trash2 size={15} />}
                  {t("deleteRunRecord")}
                </VButton>
              </div>
            </div>
          </>
        ) : (
          <div className={styles.structuredEmptyState}>
            <p className={styles.eyebrow}>{t("runDetail")}</p>
            <h3>{hasRuns ? t("noRunMatches") : t("noSupervisedRunsYet")}</h3>
            <p>{hasRuns ? t("runDetailFilterHint") : t("runDetailPlaceholder")}</p>
            <div className={styles.detailFactGrid}>
              <article className={styles.relatedRow}>
                <strong>{t("score")}</strong>
                <span>--</span>
              </article>
              <article className={styles.relatedRow}>
                <strong>{t("proposalStatus")}</strong>
                <span>--</span>
              </article>
            </div>
            <div className={styles.actionRow}>
              {!hasRuns ? (
                <VButton
                  type="button"
                  className={styles.inlineAction}
                  onClick={onReturnToOverview}
                >
                  <ArrowUpRight size={15} />
                  {t("returnToOverview")}
                </VButton>
              ) : (
                <VButton
                  type="button"
                  className={styles.inlineAction}
                  onClick={onShowAllRuns}
                >
                  {t("allRuns")}
                </VButton>
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
