import { Suspense, lazy, type CSSProperties } from "react";
import { ArrowUpRight, Pencil, Save, Trash2, X } from "lucide-react";

import type { EvolutionLibraryEntry, EvolutionProposalDetail } from "../api/types";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import {
  VButton,
  VCheckbox,
  VInput,
  VStateSurface,
  VStringSelect,
  VSurface,
  VTextarea,
  VTooltip,
} from "../components/vui";
import type { Language, TranslationKey } from "../i18n/dictionary";
import {
  compactCaseObject,
  compactTimestamp,
  displaySupervisedTechnicalText,
  proposalDisplaySourceRun,
  type ProposalEditDraft,
} from "./evolution/evolutionRouteModel";
import styles from "./EvolutionRoute.styles";

const EvolutionProposalActionBandsPanel = lazy(() =>
  import("./EvolutionProposalActionBandsPanel").then((module) => ({
    default: module.EvolutionProposalActionBandsPanel,
  })),
);

export type EvolutionLibraryViewMode = "items" | "pending";
export type EvolutionLibraryStatusFilter =
  | "all"
  | "proposed"
  | "applied"
  | "active"
  | "superseded"
  | "rolled_back"
  | "missing";
export type EvolutionLibraryDeleteFilter = "all" | "deletable" | "blocked";

const LIBRARY_STATUS_FILTERS: EvolutionLibraryStatusFilter[] = [
  "all",
  "proposed",
  "applied",
  "active",
  "superseded",
  "rolled_back",
  "missing",
];

export type EvolutionSupervisedLibraryViewProps = {
  lang: Language;
  t: (key: TranslationKey) => string;
  statusLabel: (status: string) => string;
  decisionLabel: (decision: string) => string;
  riskLabel: (risk: string) => string;
  intakeModeLabel: (mode: string) => string;
  proposalActionLabel: (action: string) => string;
  displayDecisionLabel: (decision: string) => string;
  libraryView: EvolutionLibraryViewMode;
  onLibraryViewChange: (view: EvolutionLibraryViewMode) => void;
  libraryItems: EvolutionLibraryEntry[];
  pendingItems: EvolutionLibraryEntry[];
  filteredLibraryItems: EvolutionLibraryEntry[];
  filteredPendingItems: EvolutionLibraryEntry[];
  visibleLibraryEntries: EvolutionLibraryEntry[];
  currentLibraryEntries: EvolutionLibraryEntry[];
  selectedLibraryItem: EvolutionLibraryEntry | null;
  selectedPendingItem: EvolutionLibraryEntry | null;
  selectedProposalSummary: EvolutionLibraryEntry | null;
  selectedProposalIsSelfCandidate: boolean;
  selectedProposalDisplaySourceRun: string;
  selectedProposalCanOpenSourceRun: boolean;
  selectedProposalRunIds: string[];
  libraryWorkspaceStyle?: CSSProperties;
  libraryListCollapsed: boolean;
  libraryListWidth: number;
  libraryListMinWidth: number;
  libraryListMaxWidth: number;
  libraryDragging: boolean;
  resizeLibraryListLabel: string;
  onToggleLibraryListCollapsed: () => void;
  onLibraryResizePointerDown: (event: any) => void;
  onLibraryResizeKeyDown: (event: any) => void;
  librarySearchInput: string;
  onLibrarySearchInputChange: (value: string) => void;
  libraryStatusFilter: EvolutionLibraryStatusFilter;
  onLibraryStatusFilterChange: (value: EvolutionLibraryStatusFilter) => void;
  libraryDeleteFilter: EvolutionLibraryDeleteFilter;
  onLibraryDeleteFilterChange: (value: EvolutionLibraryDeleteFilter) => void;
  hasLibraryFilters: boolean;
  onClearLibraryFilters: () => void;
  libraryHeaderMessage: string;
  libraryDeletableCount: number;
  libraryBlockedCount: number;
  currentIntakeMode: string;
  latestRunId?: string;
  libraryFeedback: string;
  bulkDeleteError?: string;
  bulkDeletePending: boolean;
  onClearProposalSelection: () => void;
  onBulkDelete: () => void;
  onSelectLibraryItem: (id: string) => void;
  onSelectPendingItem: (id: string) => void;
  onToggleProposalSelection: (item: EvolutionLibraryEntry) => void;
  proposalSelected: (sessionId: string) => boolean;
  proposalDetail: EvolutionProposalDetail | null | undefined;
  proposalDetailError?: string;
  proposalDetailLoading: boolean;
  proposalEditOpen: boolean;
  proposalEditDraft: ProposalEditDraft;
  proposalEditFeedback: string;
  updateProposalPending: boolean;
  updateProposalError: string;
  deleteProposalPending: boolean;
  deleteProposalError: string;
  actionFeedback: string;
  actionError: string;
  actionPending: boolean;
  runLocked: boolean;
  onBeginProposalEdit: (detail: EvolutionProposalDetail) => void;
  onCancelProposalEdit: (detail: EvolutionProposalDetail) => void;
  onUpdateProposalEditDraft: (field: keyof ProposalEditDraft, value: string) => void;
  onTriggerProposalUpdate: (sessionId: string) => void;
  onRunAction: (sessionId: string, action: string) => void;
  onDeleteProposal: (sessionId: string) => void;
  onOpenRun: (runId: string | null) => void;
  formatAvailableActions: (actions: string[] | undefined) => string;
};

export function EvolutionSupervisedLibraryView(props: EvolutionSupervisedLibraryViewProps) {
  const {
    lang, t, statusLabel, decisionLabel, riskLabel, intakeModeLabel, proposalActionLabel, displayDecisionLabel,
    libraryView, onLibraryViewChange, libraryItems, pendingItems, filteredLibraryItems, filteredPendingItems,
    visibleLibraryEntries, currentLibraryEntries, selectedLibraryItem, selectedPendingItem, selectedProposalSummary,
    selectedProposalIsSelfCandidate, selectedProposalDisplaySourceRun, selectedProposalCanOpenSourceRun,
    selectedProposalRunIds, libraryWorkspaceStyle, libraryListCollapsed, libraryListWidth, libraryListMinWidth,
    libraryListMaxWidth, libraryDragging, resizeLibraryListLabel, onToggleLibraryListCollapsed,
    onLibraryResizePointerDown, onLibraryResizeKeyDown, librarySearchInput, onLibrarySearchInputChange,
    libraryStatusFilter, onLibraryStatusFilterChange, libraryDeleteFilter, onLibraryDeleteFilterChange,
    hasLibraryFilters, onClearLibraryFilters, libraryHeaderMessage, libraryDeletableCount, libraryBlockedCount,
    currentIntakeMode, latestRunId, libraryFeedback, bulkDeleteError, bulkDeletePending, onClearProposalSelection,
    onBulkDelete, onSelectLibraryItem, onSelectPendingItem, onToggleProposalSelection, proposalSelected,
    proposalDetail, proposalDetailError, proposalDetailLoading: _proposalDetailLoading, proposalEditOpen, proposalEditDraft,
    proposalEditFeedback, updateProposalPending, updateProposalError, deleteProposalPending, deleteProposalError, actionFeedback,
    actionError, actionPending, runLocked, onBeginProposalEdit, onCancelProposalEdit, onUpdateProposalEditDraft,
    onTriggerProposalUpdate, onRunAction, onDeleteProposal, onOpenRun, formatAvailableActions,
  } = props;

  function renderReviewList(lines: string[]) {
    if (lines.length === 0) {
      return <p>--</p>;
    }
    return (
      <ul className={styles.detailList}>
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    );
  }

  function renderRawJson(title: string, payload: Record<string, unknown> | null) {
    return (
      <details className={styles.rawBlock}>
        <summary>{title}</summary>
        <pre className={styles.rawJson}>{JSON.stringify(payload ?? {}, null, 2)}</pre>
      </details>
    );
  }

  function renderSelfEvolutionCandidateDetail(item: EvolutionLibraryEntry) {
    const evidenceRefs = item.evidenceRefs ?? [];
    const allowedUses = item.allowedDownstreamUses ?? [];
    const blockedUses = item.blockedDownstreamUses ?? [];
    return (
      <>
        <div className={styles.detailHeader}>
          <div>
            <p className={styles.eyebrow}>{t("pendingReview")}</p>
            <h2 className={styles.detailTitle}>{item.title}</h2>
          </div>
          <span className={styles.statusPill}>{item.outcomeSemantics.proposalStatusLabel}</span>
        </div>
        <div className={styles.detailSection}>
          <h3>{t("reviewHeadline")}</h3>
          <p className={styles.reviewLead}>{item.headline || item.summary}</p>
          <VTooltip content={item.reason || item.outcomeSemantics.runtimeExplanation} width="wide">
            <p tabIndex={0}>
              {displaySupervisedTechnicalText(item.reason || item.outcomeSemantics.runtimeExplanation, item.decision, lang, decisionLabel)}
            </p>
          </VTooltip>
        </div>
        <div className={styles.detailSection}>
          <h3>{t("resultLayersTitle")}</h3>
          <div className={styles.relatedList}>
            <article className={styles.relatedRow}>
              <strong>{t("sourceRun")}</strong>
              <span>{proposalDisplaySourceRun(item) || "--"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>candidate_id</strong>
              <span>{item.id}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("proposalUpdatedAt")}</strong>
              <span>{compactTimestamp(item.updatedAt)}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("proposalLayer")}</strong>
              <span>{item.outcomeSemantics.proposalStatusLabel}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("runtimeLayer")}</strong>
              <span>{item.outcomeSemantics.runtimeEffectLabel}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("targetLabelTitle")}</strong>
              <span>{item.targetLabel || item.candidateType || item.targetKey || "--"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("availableActions")}</strong>
              <span>{formatAvailableActions(item.availableActions)}</span>
            </article>
          </div>
          <VTooltip content={item.outcomeSemantics.runtimeExplanation} width="wide">
            <p className={styles.noticeText} tabIndex={0}>
              {displaySupervisedTechnicalText(item.outcomeSemantics.runtimeExplanation, item.decision, lang, decisionLabel)}
            </p>
          </VTooltip>
        </div>
        <div className={styles.detailSection}>
          <h3>{t("currentStateTitle")}</h3>
          <div className={styles.relatedList}>
            <article className={styles.relatedRow}>
              <strong>review_state</strong>
              <span>{item.reviewState || "--"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>{t("riskLevel")}</strong>
              <span>{item.riskLevel ? riskLabel(item.riskLevel) : "--"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>supervised_required</strong>
              <span>{item.supervisedRequired ? "true" : "false"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>candidate_only</strong>
              <span>{item.candidateOnly ? "true" : "false"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>auto_apply</strong>
              <span>{item.autoApply ? "true" : "false"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>allowed_downstream_uses</strong>
              <span>{allowedUses.length > 0 ? allowedUses.join(", ") : "--"}</span>
            </article>
            <article className={styles.relatedRow}>
              <strong>blocked_downstream_uses</strong>
              <span>{blockedUses.length > 0 ? blockedUses.join(", ") : "--"}</span>
            </article>
          </div>
        </div>
        <div className={styles.detailSection}>
          <h3>{t("deleteAndCleanup")}</h3>
          <div className={styles.relatedList}>
            <article className={styles.relatedRow}>
              <strong>{item.canDelete ? t("deletionAllowed") : t("deletionBlocked")}</strong>
              <span>{item.canDelete ? t("deleteProposal") : item.deleteBlockReason || "--"}</span>
            </article>
          </div>
        </div>
        <div className={styles.detailSection}>
          <h3>{t("evidencePaths")}</h3>
          <div className={styles.relatedList}>
            {evidenceRefs.length > 0 ? (
              evidenceRefs.map((path) => (
                <article key={path} className={styles.relatedRow}>
                  <strong>evidence</strong>
                  <span className={styles.pathText}>{path}</span>
                </article>
              ))
            ) : (
              <article className={styles.relatedRow}>
                <strong>evidence</strong>
                <span>--</span>
              </article>
            )}
            {item.sourceExperienceId ? (
              <article className={styles.relatedRow}>
                <strong>source_experience_id</strong>
                <span>{item.sourceExperienceId}</span>
              </article>
            ) : null}
            {item.sourceReflectionId ? (
              <article className={styles.relatedRow}>
                <strong>source_reflection_id</strong>
                <span>{item.sourceReflectionId}</span>
              </article>
            ) : null}
            {item.txnId ? (
              <article className={styles.relatedRow}>
                <strong>txn_id</strong>
                <span>{item.txnId}</span>
              </article>
            ) : null}
          </div>
        </div>
        <div className={styles.detailSection}>
          <div className={styles.rawBlockStack}>
            {renderRawJson("candidate_payload", item.payload ?? null)}
            {renderRawJson("provenance", item.provenance ?? null)}
          </div>
        </div>
      </>
    );
  }

  return (
<div className={`${styles.viewStack} ${styles.libraryViewStack}`} data-vui-region="evolution-supervised-library">
          <div className={styles.librarySummaryBar}>
            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("recentLibraryAdditions")}</p>
                  <h2 className={styles.sectionTitle}>{t("library")}</h2>
                </div>
                <div className={styles.filterSegmented}>
                  {(["items", "pending"] as const).map((view) => (
                    <VButton
                      key={view}
                      type="button"
                      className={
                        libraryView === view
                          ? `${styles.filterButton} ${styles.filterButtonActive}`
                          : styles.filterButton
                      }
                      onClick={() => onLibraryViewChange(view)}
                    >
                      {view === "items" ? t("libraryItems") : t("pendingReview")}
                    </VButton>
                  ))}
                </div>
              </div>
              <div className={styles.summaryMetricStrip}>
                <article className={styles.stripItem}>
                  <span>{t("libraryItems")}</span>
                  <strong>{libraryItems.length}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("pendingReview")}</span>
                  <strong>{pendingItems.length}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("intakeMode")}</span>
                  <strong>{intakeModeLabel(currentIntakeMode)}</strong>
                </article>
                <article className={styles.stripItem}>
                  <span>{t("selectedCount")}</span>
                  <strong>{selectedProposalRunIds.length}</strong>
                </article>
              </div>
              <p className={styles.noticeText}>{t("batchDeleteHint")}</p>
            </section>

            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("selectedCount")}</p>
                  <h2 className={styles.sectionTitle}>
                    {libraryView === "items" ? t("libraryItems") : t("pendingReview")}
                  </h2>
                </div>
                <span className={styles.secondaryPill}>{selectedProposalRunIds.length}</span>
              </div>
              <p className={styles.statusLead}>{libraryHeaderMessage}</p>
              <div className={styles.statusMetricGrid}>
                <article className={styles.metricTile}>
                  <span>{t("filterResults")}</span>
                  <strong>{`${visibleLibraryEntries.length} / ${currentLibraryEntries.length}`}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("selectedCount")}</span>
                  <strong>{selectedProposalRunIds.length}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("deletionAllowed")}</span>
                  <strong>{libraryDeletableCount}</strong>
                </article>
                <article className={styles.metricTile}>
                  <span>{t("deletionBlocked")}</span>
                  <strong>{libraryBlockedCount}</strong>
                </article>
              </div>
              {hasLibraryFilters ? (
                <div className={styles.actionRow}>
                  <VButton
                    type="button"
                    className={styles.inlineAction}
                    onClick={onClearLibraryFilters}
                  >
                    {t("clearFilters")}
                  </VButton>
                </div>
              ) : null}
            </section>

            <section className={`${styles.surface} ${styles.summarySurface}`}>
              <div className={styles.surfaceHeaderCompact}>
                <div>
                  <p className={styles.eyebrow}>{t("proposalStatus")}</p>
                  <h2 className={styles.sectionTitle}>
                    {selectedProposalSummary?.title
                      || (libraryView === "items" ? t("libraryItems") : t("pendingReview"))}
                  </h2>
                </div>
                <span className={selectedProposalSummary ? styles.statusPill : styles.secondaryPill}>
                  {selectedProposalSummary
                    ? selectedProposalSummary.outcomeSemantics.proposalStatusLabel
                    : intakeModeLabel(currentIntakeMode)}
                </span>
              </div>
              <p className={styles.statusLead}>
                {selectedProposalSummary
                  ? (selectedProposalSummary.summary || selectedProposalSummary.reason || selectedProposalSummary.headline)
                  : libraryHeaderMessage}
              </p>
              <div className={styles.relatedList}>
                <article className={styles.relatedRow}>
                  <strong>{t("latestRun")}</strong>
                  <span>{selectedProposalDisplaySourceRun || latestRunId || "--"}</span>
                </article>
                <article className={styles.relatedRow}>
                  <strong>{t("intakeMode")}</strong>
                  <span>{intakeModeLabel(currentIntakeMode)}</span>
                </article>
              </div>
              {selectedProposalSummary && selectedProposalCanOpenSourceRun ? (
                <div className={styles.actionRow}>
                  <VButton
                    type="button"
                    className={styles.inlineAction}
                    onClick={() => onOpenRun(selectedProposalSummary.sourceRun)}
                  >
                    <ArrowUpRight size={15} />
                    {t("openSourceRun")}
                  </VButton>
                </div>
              ) : null}
            </section>
          </div>

          <div className={styles.masterDetail} style={libraryWorkspaceStyle}>
            <VSurface
              as="section"
              className={
                libraryListCollapsed
                  ? `${styles.surface} ${styles.listPanel} ${styles.paneCollapsed}`
                  : `${styles.surface} ${styles.listPanel}`
              }
              aria-hidden={libraryListCollapsed}
              elevation="panel"
              padding="none"
              tone="rail"
            >
              <>
                <div className={styles.bulkToolbar}>
                  <div className={styles.bulkToolbarText}>
                    <strong>{t("selectedCount")}</strong>
                    <span>{selectedProposalRunIds.length}</span>
                  </div>
                  <div className={styles.actionRow}>
                    <VButton
                      type="button"
                      className={styles.inlineAction}
                      isDisabled={selectedProposalRunIds.length === 0}
                      onClick={() => onClearProposalSelection()}
                    >
                      {t("clearSelection")}
                    </VButton>
                    <VButton
                      type="button"
                      variant="danger"
                      className={styles.inlineAction}
                      isDisabled={selectedProposalRunIds.length === 0 || bulkDeletePending}
                      onClick={onBulkDelete}
                    >
                      <Trash2 size={15} />
                      {t("deleteSelected")}
                    </VButton>
                  </div>
                </div>
                <div className={styles.libraryFilters}>
                  <div className={styles.filterRow}>
                    <label className={styles.filterField}>
                      <span>{t("proposalTarget")}</span>
                      <VInput
                        type="text"
                        className={styles.textInput}
                        value={librarySearchInput}
                        placeholder={t("proposalSearchPlaceholder")}
                        onChange={(event) => onLibrarySearchInputChange(event.target.value)}
                      />
                    </label>
                    <div className={styles.filterField}>
                      <span>{t("filterByStatus")}</span>
                      <VStringSelect
                        ariaLabel={t("filterByStatus")}
                        className={styles.selectInput}
                        value={libraryStatusFilter}
                        options={LIBRARY_STATUS_FILTERS.map((status) => ({
                          value: status,
                          label: status === "all" ? t("filterAll") : statusLabel(status),
                        }))}
                        onValueChange={(value) => onLibraryStatusFilterChange(value as EvolutionLibraryStatusFilter)}
                      />
                    </div>
                    <div className={styles.filterField}>
                      <span>{t("filterByDeleteState")}</span>
                      <VStringSelect
                        ariaLabel={t("filterByDeleteState")}
                        className={styles.selectInput}
                        value={libraryDeleteFilter}
                        options={[
                          { value: "all", label: t("filterAll") },
                          { value: "deletable", label: t("filterDeletableOnly") },
                          { value: "blocked", label: t("filterBlockedOnly") },
                        ]}
                        onValueChange={(value) => onLibraryDeleteFilterChange(value as EvolutionLibraryDeleteFilter)}
                      />
                    </div>
                  </div>
                  <div className={styles.filterMeta}>
                    <div className={styles.selectionSummary}>
                      <span>{t("filterResults")}</span>
                      <strong>{visibleLibraryEntries.length} / {currentLibraryEntries.length}</strong>
                    </div>
                    {hasLibraryFilters ? (
                      <VButton
                        type="button"
                        className={styles.inlineAction}
                        onClick={onClearLibraryFilters}
                      >
                        {t("clearFilters")}
                      </VButton>
                    ) : null}
                  </div>
                </div>
                {libraryFeedback ? <p className={styles.feedbackText}>{libraryFeedback}</p> : null}
                {bulkDeleteError ? <p className={styles.errorText}>{bulkDeleteError}</p> : null}
                {libraryView === "items"
                ? libraryItems.length === 0
                  ? <VStateSurface className={styles.emptyState} title={t("emptyLibraryItems")} tone="empty" />
                  : filteredLibraryItems.length === 0
                    ? <VStateSurface className={styles.emptyState} title={t("noProposalMatches")} tone="empty" />
                    : filteredLibraryItems.map((item) => (
                      <article
                        key={item.id}
                        className={
                          selectedLibraryItem?.id === item.id
                            ? `${styles.proposalCard} ${styles.runItemActive}`
                            : styles.proposalCard
                        }
                      >
                        <div className={styles.selectionBar}>
                          <VCheckbox
                            className={styles.batchToggle}
                            isDisabled={!item.canDelete}
                            isSelected={proposalSelected(item.sourceRun)}
                            onChange={() => onToggleProposalSelection(item)}
                          >
                            {t("selectForBatchDelete")}
                          </VCheckbox>
                          <span className={item.canDelete ? styles.secondaryPill : styles.statusPill}>
                            {item.canDelete ? t("deletionAllowed") : t("deletionBlocked")}
                          </span>
                        </div>
                        <VButton
                          type="button"
                          contentLayout="plain"
                          className={styles.proposalCardButton}
                          onClick={() => onSelectLibraryItem(item.id)}
                        >
                          <div className={styles.listRowTop}>
                            <strong>{item.title}</strong>
                            <span className={styles.secondaryPill}>{item.outcomeSemantics.proposalStatusLabel}</span>
                          </div>
                          <div className={styles.metaRow}>
                            <span>{displayDecisionLabel(item.decision)}</span>
                            <span>{proposalDisplaySourceRun(item)}</span>
                          </div>
                          <p className={styles.cardHeadline}>{item.changeSummary || item.headline}</p>
                          <p>{item.summary}</p>
                          <div className={styles.cardFooter}>
                            <span>{item.targetLabel || item.targetKey || "--"}</span>
                            <span>{compactTimestamp(item.updatedAt)}</span>
                          </div>
                        </VButton>
                      </article>
                    ))
                : pendingItems.length === 0
                  ? <VStateSurface className={styles.emptyState} title={t("emptyPendingItems")} tone="empty" />
                  : filteredPendingItems.length === 0
                    ? <VStateSurface className={styles.emptyState} title={t("noProposalMatches")} tone="empty" />
                    : filteredPendingItems.map((item) => (
                      <article
                        key={item.id}
                        className={
                          selectedPendingItem?.id === item.id
                            ? `${styles.proposalCard} ${styles.runItemActive}`
                            : styles.proposalCard
                        }
                      >
                        <div className={styles.selectionBar}>
                          <VCheckbox
                            className={styles.batchToggle}
                            isDisabled={!item.canDelete}
                            isSelected={proposalSelected(item.sourceRun)}
                            onChange={() => onToggleProposalSelection(item)}
                          >
                            {t("selectForBatchDelete")}
                          </VCheckbox>
                          <span className={item.canDelete ? styles.secondaryPill : styles.statusPill}>
                            {item.canDelete ? t("deletionAllowed") : t("deletionBlocked")}
                          </span>
                        </div>
                        <VButton
                          type="button"
                          contentLayout="plain"
                          className={styles.proposalCardButton}
                          onClick={() => onSelectPendingItem(item.id)}
                        >
                          <div className={styles.listRowTop}>
                            <strong>{item.title}</strong>
                            <span className={styles.secondaryPill}>{item.outcomeSemantics.proposalStatusLabel}</span>
                          </div>
                          <div className={styles.metaRow}>
                            <span>{displayDecisionLabel(item.decision)}</span>
                            <span>{proposalDisplaySourceRun(item)}</span>
                          </div>
                          <p className={styles.cardHeadline}>{item.changeSummary || item.headline}</p>
                          <p>{item.reason || item.summary}</p>
                          <div className={styles.cardFooter}>
                            <span>{item.targetLabel || item.targetKey || "--"}</span>
                            <span>{compactTimestamp(item.updatedAt)}</span>
                          </div>
                        </VButton>
                      </article>
                    ))}
              </>
            </VSurface>

            <PaneCollapseHandle
              side="left"
              collapsed={libraryListCollapsed}
              separatorLabel={resizeLibraryListLabel}
              collapseLabel={lang === "zh" ? "收起提案列表" : "Collapse proposal list"}
              expandLabel={lang === "zh" ? "展开提案列表" : "Expand proposal list"}
              className={styles.resizeHandle}
              active={libraryDragging}
              valueNow={libraryListWidth}
              valueMin={libraryListMinWidth}
              valueMax={libraryListMaxWidth}
              onToggle={() => onToggleLibraryListCollapsed()}
              onPointerDown={onLibraryResizePointerDown}
              onKeyDown={onLibraryResizeKeyDown}
            />

            <VSurface
              as="section"
              className={`${styles.surface} ${styles.detailPanel}`}
              elevation="panel"
              padding="none"
              tone="panel"
            >
              {selectedProposalSummary ? (
                selectedProposalIsSelfCandidate ? (
                  renderSelfEvolutionCandidateDetail(selectedProposalSummary)
                ) : proposalDetail ? (
                  <>
                    <div className={styles.detailHeader}>
                      <div>
                        <p className={styles.eyebrow}>
                          {libraryView === "items" ? t("libraryItems") : t("pendingReview")}
                        </p>
                        <h2 className={styles.detailTitle}>{proposalDetail.title}</h2>
                      </div>
                      <span className={styles.statusPill}>
                        {proposalDetail.outcomeSemantics.proposalStatusLabel}
                      </span>
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("reviewHeadline")}</h3>
                      <p className={styles.reviewLead}>{proposalDetail.review.headline}</p>
                      <p>{proposalDetail.review.changeSummary}</p>
                    </div>

                    <div className={styles.detailSection}>
                      <div className={styles.sectionHeadingRow}>
                        <h3>{t("editProposalTitle")}</h3>
                        {proposalEditOpen ? (
                          <div className={styles.actionRow}>
                            <VButton
                              type="button"
                              className={styles.inlineAction}
                              isDisabled={updateProposalPending}
                              onClick={() => onCancelProposalEdit(proposalDetail)}
                            >
                              <X size={15} />
                              {t("cancelEdit")}
                            </VButton>
                            <VButton
                              type="button"
                              variant="primary"
                              className={styles.inlineAction}
                              isDisabled={!proposalDetail.canEdit || updateProposalPending}
                              onClick={() => onTriggerProposalUpdate(proposalDetail.sourceRun)}
                            >
                              <Save size={15} />
                              {updateProposalPending ? t("saving") : t("saveProposalEdit")}
                            </VButton>
                          </div>
                        ) : (
                          <VButton
                            type="button"
                            className={styles.inlineAction}
                            isDisabled={!proposalDetail.canEdit}
                            onClick={() => onBeginProposalEdit(proposalDetail)}
                          >
                            <Pencil size={15} />
                            {t("editProposal")}
                          </VButton>
                        )}
                      </div>
                      {!proposalDetail.canEdit ? (
                        <p className={styles.noticeText}>{proposalDetail.editBlockReason || t("proposalEditLocked")}</p>
                      ) : null}
                      {proposalDetail.proposal.editedAt ? (
                        <p className={styles.noticeText}>
                          {t("proposalEditedAt")}: {compactTimestamp(proposalDetail.proposal.editedAt)}
                        </p>
                      ) : null}
                      {proposalEditOpen ? (
                        <div className={styles.proposalEditGrid}>
                          <label className={styles.formField}>
                            <span>{t("proposalImprovementType")}</span>
                            <VInput
                              className={styles.textInput}
                              value={proposalEditDraft.improvementType}
                              onChange={(event) => onUpdateProposalEditDraft("improvementType", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalExpectedEffect")}</span>
                            <VTextarea
                              className={styles.textArea}
                              rows={3}
                              value={proposalEditDraft.expectedEffect}
                              onChange={(event) => onUpdateProposalEditDraft("expectedEffect", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalDraftSummary")}</span>
                            <VTextarea
                              className={styles.textArea}
                              rows={3}
                              value={proposalEditDraft.summary}
                              onChange={(event) => onUpdateProposalEditDraft("summary", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalCandidatePrompt")}</span>
                            <VTextarea
                              className={styles.textArea}
                              rows={6}
                              value={proposalEditDraft.candidatePrompt}
                              onChange={(event) => onUpdateProposalEditDraft("candidatePrompt", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalBaselinePrompt")}</span>
                            <VTextarea
                              className={styles.textArea}
                              rows={5}
                              value={proposalEditDraft.baselinePrompt}
                              onChange={(event) => onUpdateProposalEditDraft("baselinePrompt", event.target.value)}
                            />
                          </label>
                          <label className={styles.formField}>
                            <span>{t("proposalEditNote")}</span>
                            <VInput
                              className={styles.textInput}
                              value={proposalEditDraft.editNote}
                              onChange={(event) => onUpdateProposalEditDraft("editNote", event.target.value)}
                            />
                          </label>
                        </div>
                      ) : (
                        <div className={styles.relatedList}>
                          <article className={styles.relatedRow}>
                            <strong>{t("proposalImprovementType")}</strong>
                            <span>{proposalDetail.proposal.improvementType || "--"}</span>
                          </article>
                          <article className={styles.relatedRow}>
                            <strong>{t("proposalExpectedEffect")}</strong>
                            <span>{proposalDetail.proposal.expectedEffect || "--"}</span>
                          </article>
                          <article className={styles.relatedRow}>
                            <strong>{t("proposalDraftSummary")}</strong>
                            <span>{proposalDetail.proposal.summary || proposalDetail.review.changeSummary || "--"}</span>
                          </article>
                        </div>
                      )}
                      {proposalEditFeedback ? <p className={styles.feedbackText}>{proposalEditFeedback}</p> : null}
                      {updateProposalError ? <p className={styles.errorText}>{updateProposalError}</p> : null}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("whatChangedTitle")}</h3>
                      {renderReviewList(proposalDetail.review.whatChanged)}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("whyCreatedTitle")}</h3>
                      {renderReviewList(proposalDetail.review.whyCreated)}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("currentStateTitle")}</h3>
                      {renderReviewList([
                        ...proposalDetail.review.currentState,
                        proposalDetail.review.nextAction,
                      ])}
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("resultLayersTitle")}</h3>
                      <div className={styles.relatedList}>
                        <article className={styles.relatedRow}>
                          <strong>{t("sourceRun")}</strong>
                          <span>{proposalDetail.sourceRun}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("proposalUpdatedAt")}</strong>
                          <span>{compactTimestamp(proposalDetail.updatedAt)}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("runLayer")}</strong>
                          <span>{proposalDetail.runSemantics.runStatusLabel}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("decision")}</strong>
                          <span>
                            {displayDecisionLabel(
                              proposalDetail.outcomeSemantics.decision || proposalDetail.decision,
                            )}
                          </span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("proposalLayer")}</strong>
                          <span>{proposalDetail.outcomeSemantics.proposalStatusLabel}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("runtimeLayer")}</strong>
                          <span>{proposalDetail.outcomeSemantics.runtimeEffectLabel}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("targetLabelTitle")}</strong>
                          <span>
                            {proposalDetail.targetLabel
                              || proposalDetail.targetKey
                              || "--"}
                          </span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("baselineScore")}</strong>
                          <span>{proposalDetail.supervised.baselineScore}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("candidateScore")}</strong>
                          <span>{proposalDetail.supervised.candidateScore}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("scoreDelta")}</strong>
                          <span>{proposalDetail.supervised.deltaScore}</span>
                        </article>
                        <article className={styles.relatedRow}>
                          <strong>{t("riskLevel")}</strong>
                          <span>{riskLabel(proposalDetail.supervised.riskLevel)}</span>
                        </article>
                      </div>
                      <VTooltip content={proposalDetail.outcomeSemantics.runtimeExplanation} width="wide">
                        <p className={styles.noticeText} tabIndex={0}>
                          {displaySupervisedTechnicalText(
                            proposalDetail.outcomeSemantics.runtimeExplanation,
                            proposalDetail.decision,
                            lang,
                            decisionLabel,
                          )}
                        </p>
                      </VTooltip>
                      <VTooltip content={proposalDetail.supervised.decisionReason} width="wide">
                        <p tabIndex={0}>
                          {displaySupervisedTechnicalText(
                            proposalDetail.supervised.decisionReason,
                            proposalDetail.decision,
                            lang,
                            decisionLabel,
                          )}
                        </p>
                      </VTooltip>
                      {proposalDetail.supervised.riskReasons.length > 0 ? (
                        <VTooltip content={proposalDetail.supervised.riskReasons.join(" / ")} width="wide">
                          <p tabIndex={0}>
                            {displaySupervisedTechnicalText(
                              proposalDetail.supervised.riskReasons.join(" / "),
                              proposalDetail.decision,
                              lang,
                              decisionLabel,
                            )}
                          </p>
                        </VTooltip>
                      ) : null}
                      {proposalDetail.supervised.caseDiagnostics.length > 0 ? (
                        <div className={styles.relatedList}>
                          {proposalDetail.supervised.caseDiagnostics.slice(0, 3).map((item) => (
                            <article key={item.caseId || item.summary} className={styles.relatedRow}>
                              <strong>{item.caseId || "--"}</strong>
                              <span>{item.summary}</span>
                              {item.caseType && item.caseType !== "static" ? <span>{item.caseType}</span> : null}
                              {compactCaseObject(item.expectedFinalState) ? (
                                <span>expected final: {compactCaseObject(item.expectedFinalState)}</span>
                              ) : null}
                              {compactCaseObject(item.expectedInfeasibleOutcome) ? (
                                <span>expected infeasible: {compactCaseObject(item.expectedInfeasibleOutcome)}</span>
                              ) : null}
                            </article>
                          ))}
                        </div>
                      ) : null}
                    </div>

                    <Suspense fallback={<p className={styles.noticeText}>{t("loading")}</p>}>
                      <EvolutionProposalActionBandsPanel
                        proposal={proposalDetail}
                        labels={{ t, proposalActionLabel }}
                        runLocked={runLocked}
                        actionFeedback={actionFeedback}
                        actionError={actionError}
                        actionPending={actionPending}
                        deleteProposalError={deleteProposalError}
                        deleteProposalPending={deleteProposalPending}
                        onRunAction={onRunAction}
                        onDeleteProposal={onDeleteProposal}
                      />
                    </Suspense>

                    <div className={styles.detailSection}>
                      <h3>{t("evidencePaths")}</h3>
                      <div className={styles.relatedList}>
                        {Object.entries(proposalDetail.paths)
                          .filter(([, value]) => Boolean(value))
                          .map(([key, value]) => (
                            <article key={key} className={styles.relatedRow}>
                              <strong>{key}</strong>
                              <span className={styles.pathText}>{value}</span>
                            </article>
                          ))}
                      </div>
                    </div>

                    <div className={styles.detailSection}>
                      <h3>{t("navEvolution")}</h3>
                      <VButton
                        type="button"
                        className={styles.inlineAction}
                        onClick={() => onOpenRun(proposalDetail.sourceRun)}
                      >
                        <ArrowUpRight size={15} />
                        {t("openSourceRun")}
                      </VButton>
                    </div>

                    <div className={styles.detailSection}>
                      <div className={styles.rawBlockStack}>
                        {renderRawJson(t("rawProposalJson"), proposalDetail.rawProposal)}
                        {renderRawJson(t("rawGymDecisionJson"), proposalDetail.rawGymDecision)}
                        {renderRawJson(t("rawSupervisedDecisionJson"), proposalDetail.rawSupervisedDecision)}
                      </div>
                    </div>
                  </>
                ) : proposalDetailError ? (
                  <VStateSurface fill className={styles.emptyState} title={proposalDetailError} tone="error" />
                ) : (
                  <VStateSurface fill className={styles.emptyState} title={t("loadingRunDetails")} tone="loading" />
                )
              ) : (
                <VStateSurface fill className={styles.emptyState} title={t("chooseProposalDetail")} tone="empty" />
              )}
            </VSurface>
          </div>
        </div>
  );
}
