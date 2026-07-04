import { CheckCircle2, Square, TriangleAlert, XCircle } from "lucide-react";
import type { ReactNode } from "react";

import type { AgentProjectMemoryUpdateProposal } from "../api/types";
import { VButton, VNativeInput } from "../components/vui";
import styles from "./MemoryProjectMemoryQueuePanel.styles";

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
  return (
    <section className={styles.projectMemoryQueuePanel}>
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
      <div className={styles.projectMemoryQueueStats} title={copy.projectMemoryQueueHint}>
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
  );
}
