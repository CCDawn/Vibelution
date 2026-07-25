import { CheckCircle2, Square, TriangleAlert, XCircle } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";

import type { AgentProjectMemoryUpdateProposal } from "../api/types";
import { PaneHeightResizeHandle } from "../components/layout/PaneHeightResizeHandle";
import type { PaneHeightSpec } from "../components/layout/paneHeightPersistence";
import { usePersistedPaneHeight } from "../components/layout/usePersistedPaneHeight";
import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VButton, VNativeInput, VTooltip } from "../components/vui";
import styles from "./MemoryProjectMemoryQueuePanel.styles";

const MEMORY_PROJECT_QUEUE_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.memory;
const MEMORY_PROJECT_QUEUE_HEIGHT_PANE: PaneHeightSpec = {
  id: "project-memory-queue",
  defaultHeight: 220,
  minHeight: 140,
  maxHeight: 480,
};
const MEMORY_PROJECT_QUEUE_HEIGHT_PANES: PaneHeightSpec[] = [MEMORY_PROJECT_QUEUE_HEIGHT_PANE];

export type MemoryProjectMemoryResolveStatus = "applied" | "rejected" | "conflict" | "superseded";

export type MemoryProjectMemoryQueueCopy = {
  governance: string;
  status: string;
  projectMemoryQueue: string;
  projectMemoryQueueHint: string;
  projectMemoryQueuePendingOnly: string;
  projectMemoryQueueAll: string;
  projectMemoryQueueAgent: string;
  projectMemoryQueueLane: string;
  projectMemoryQueueFiles: string;
  projectMemoryQueueCreated: string;
  projectMemoryQueueResolved: string;
  projectMemoryQueueResolutionNote: string;
  projectMemoryQueueApply: string;
  projectMemoryQueueReject: string;
  projectMemoryQueueConflict: string;
  projectMemoryQueueSupersede: string;
  pendingProposals: string;
  loading: string;
};

type MemoryProjectMemoryQueuePanelProps = {
  copy: MemoryProjectMemoryQueueCopy;
  isPendingOnly: boolean;
  pendingProposalCount: number;
  proposalCount: number;
  laneCount: number;
  proposals: AgentProjectMemoryUpdateProposal[];
  resolutionNotes: Record<string, string>;
  mutationFeedback: { tone: "idle" | "success" | "error"; text: string };
  errorText: string;
  emptyText: string;
  isLoading: boolean;
  isResolving: boolean;
  onFilterChange: (status: "pending" | "") => void;
  onResolutionNoteChange: (proposalId: string, note: string) => void;
  onResolve: (proposal: AgentProjectMemoryUpdateProposal, status: MemoryProjectMemoryResolveStatus) => void;
  renderStatus: (status: string) => ReactNode;
  formatTimestamp: (value: string | undefined) => string;
  proposalAgentLabel: (proposal: AgentProjectMemoryUpdateProposal) => string;
  proposalResolverLabel: (resolvedBy: string | undefined) => string;
};

export function MemoryProjectMemoryQueuePanel({
  copy,
  isPendingOnly,
  pendingProposalCount,
  proposalCount,
  laneCount,
  proposals,
  resolutionNotes,
  mutationFeedback,
  errorText,
  emptyText,
  isLoading,
  isResolving,
  onFilterChange,
  onResolutionNoteChange,
  onResolve,
  renderStatus,
  formatTimestamp,
  proposalAgentLabel,
  proposalResolverLabel,
}: MemoryProjectMemoryQueuePanelProps) {
  const {
    heights: queueHeights,
    draggingPaneId: queueHeightDraggingPaneId,
    startResize: startQueueHeightResize,
    onResizeKeyDown: onQueueHeightResizeKeyDown,
  } = usePersistedPaneHeight({
    layoutId: MEMORY_PROJECT_QUEUE_LAYOUT_ID,
    panes: MEMORY_PROJECT_QUEUE_HEIGHT_PANES,
  });
  const queueHeight = queueHeights["project-memory-queue"] ?? MEMORY_PROJECT_QUEUE_HEIGHT_PANE.defaultHeight;
  const queueStyle = {
    height: `${queueHeight}px`,
  } as CSSProperties;

  return (
    <>
    <section
      className={styles.projectMemoryQueuePanel}
      style={queueStyle}
      data-vui-region="memory-project-queue"
      data-vui-layout-id={MEMORY_PROJECT_QUEUE_LAYOUT_ID}
    >
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.governance}</p>
          <h2>{copy.projectMemoryQueue}</h2>
        </div>
        <div className={styles.projectMemoryQueueControls} aria-label={copy.status}>
          <VButton
            type="button"
            className={isPendingOnly ? styles.filterButtonActive : styles.filterButton}
            aria-pressed={isPendingOnly}
            onClick={() => onFilterChange("pending")}
          >
            {copy.projectMemoryQueuePendingOnly}
          </VButton>
          <VButton
            type="button"
            className={!isPendingOnly ? styles.filterButtonActive : styles.filterButton}
            aria-pressed={!isPendingOnly}
            onClick={() => onFilterChange("")}
          >
            {copy.projectMemoryQueueAll}
          </VButton>
        </div>
      </div>
      <VTooltip content={copy.projectMemoryQueueHint} width="wide">
        <div
          className={styles.projectMemoryQueueStats}
          tabIndex={0}
          aria-label={`${copy.projectMemoryQueue} · ${copy.projectMemoryQueueHint}`}
        >
          <span>
            <strong>{pendingProposalCount}</strong>
            {copy.pendingProposals}
          </span>
          <span>
            <strong>{proposalCount}</strong>
            {isPendingOnly ? copy.projectMemoryQueuePendingOnly : copy.projectMemoryQueueAll}
          </span>
          <span>
            <strong>{laneCount}</strong>
            {copy.projectMemoryQueueLane}
          </span>
        </div>
      </VTooltip>
      {mutationFeedback.tone !== "idle" ? (
        <p className={styles.copyNotice} data-tone={mutationFeedback.tone}>
          {mutationFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
          <span>{mutationFeedback.text}</span>
        </p>
      ) : null}
      {errorText ? (
        <p className={styles.panelError}>
          <TriangleAlert size={15} />
          <span>{errorText}</span>
        </p>
      ) : null}
      <div className={styles.projectMemoryProposalList}>
        {proposals.map((proposal) => {
          const isPendingProposal = proposal.status === "pending";
          const noteValue = resolutionNotes[proposal.proposalId] ?? "";
          const relatedFiles = (proposal.relatedFiles ?? []).filter(Boolean);
          return (
            <article key={proposal.proposalId} className={styles.projectMemoryProposalRow} data-status={proposal.status || "unknown"}>
              <div className={styles.projectMemoryProposalMain}>
                <div className={styles.projectMemoryProposalTitleLine}>
                  <strong>{proposal.focus || proposal.update || proposal.proposalId}</strong>
                  {renderStatus(proposal.status)}
                </div>
                <p>{proposal.update || proposal.details || "-"}</p>
                <small>{proposal.details || proposal.proposalId}</small>
              </div>
              <div className={styles.projectMemoryProposalMeta}>
                <span>{copy.projectMemoryQueueAgent}: {proposalAgentLabel(proposal)}</span>
                <span>{copy.projectMemoryQueueLane}: {proposal.laneId || "-"}</span>
                <span>{copy.projectMemoryQueueCreated}: {formatTimestamp(proposal.createdAt)}</span>
              </div>
              <div className={styles.projectMemoryProposalFiles} aria-label={copy.projectMemoryQueueFiles}>
                {relatedFiles.length ? relatedFiles.slice(0, 3).map((file) => <code key={file}>{file}</code>) : <span>-</span>}
                {relatedFiles.length > 3 ? <span>+{relatedFiles.length - 3}</span> : null}
              </div>
              <div className={styles.projectMemoryProposalNote}>
                {isPendingProposal ? (
                  <VNativeInput
                    value={noteValue}
                    placeholder={copy.projectMemoryQueueResolutionNote}
                    onChange={(event) => onResolutionNoteChange(proposal.proposalId, event.target.value)}
                  />
                ) : (
                  <span>
                    {proposal.resolutionNote || `${copy.projectMemoryQueueResolved}: ${proposalResolverLabel(proposal.resolvedBy)}`}
                  </span>
                )}
              </div>
              <div className={styles.projectMemoryProposalActions}>
                {isPendingProposal ? (
                  <>
                    <VButton
                      type="button"
                      className={styles.detailActionButton}
                      title={copy.projectMemoryQueueApply}
                      isDisabled={isResolving}
                      onClick={() => onResolve(proposal, "applied")}
                    >
                      <CheckCircle2 size={14} />
                      <span>{copy.projectMemoryQueueApply}</span>
                    </VButton>
                    <VButton
                      type="button"
                      className={styles.detailActionButton}
                      title={copy.projectMemoryQueueReject}
                      isDisabled={isResolving}
                      onClick={() => onResolve(proposal, "rejected")}
                    >
                      <XCircle size={14} />
                      <span>{copy.projectMemoryQueueReject}</span>
                    </VButton>
                    <VButton
                      type="button"
                      className={styles.detailActionButton}
                      title={copy.projectMemoryQueueConflict}
                      isDisabled={isResolving}
                      onClick={() => onResolve(proposal, "conflict")}
                    >
                      <TriangleAlert size={14} />
                      <span>{copy.projectMemoryQueueConflict}</span>
                    </VButton>
                    <VButton
                      type="button"
                      className={styles.detailActionButton}
                      title={copy.projectMemoryQueueSupersede}
                      isDisabled={isResolving}
                      onClick={() => onResolve(proposal, "superseded")}
                    >
                      <Square size={14} />
                      <span>{copy.projectMemoryQueueSupersede}</span>
                    </VButton>
                  </>
                ) : (
                  <span className={styles.projectMemoryProposalResolved}>
                    {copy.projectMemoryQueueResolved}: {formatTimestamp(proposal.resolvedAt)}
                  </span>
                )}
              </div>
            </article>
          );
        })}
        {isLoading && !proposals.length ? (
          <section className={styles.emptyState}>{copy.loading}</section>
        ) : null}
        {!isLoading && !proposals.length ? (
          <section className={styles.emptyState}>
            <CheckCircle2 size={20} />
            <span>{emptyText}</span>
          </section>
        ) : null}
      </div>
    </section>
    <PaneHeightResizeHandle
      label={copy.projectMemoryQueue}
      valueNow={queueHeight}
      valueMin={MEMORY_PROJECT_QUEUE_HEIGHT_PANE.minHeight}
      valueMax={MEMORY_PROJECT_QUEUE_HEIGHT_PANE.maxHeight}
      active={queueHeightDraggingPaneId === "project-memory-queue"}
      className={styles.projectMemoryQueueResizeHandle}
      onPointerDown={(event) => startQueueHeightResize("project-memory-queue", event, { direction: 1 })}
      onKeyDown={(event) => onQueueHeightResizeKeyDown("project-memory-queue", event, { direction: 1 })}
    />
    </>
  );
}
