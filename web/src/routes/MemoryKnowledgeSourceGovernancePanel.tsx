import { CheckCircle2, Copy as CopyIcon, Database, Eye, FileText, Link2, Pencil, XCircle } from "lucide-react";

import type { KnowledgeCentralSource, KnowledgeOwnerSource } from "../api/types";
import { VButton, VNativeInput, VNativeSelect, VNativeTextarea } from "../components/vui";
import styles from "./MemoryKnowledgeSourceGovernancePanel.styles";

export type MemoryKnowledgeSourceOwnerType = "team" | "agent";
export type MemoryKnowledgeSourceInboxStatusFilter = "pending" | "accepted" | "rejected" | "duplicate" | "needs_more_context" | "all";

export type MemoryKnowledgeOwnerSourceDraft = {
  sourceType: string;
  sourceRef: string;
  sourceCreatedAt: string;
  capturedBy: string;
  evidenceRange: string;
  title: string;
  summary: string;
  originalContent: string;
  originalFilename: string;
  sourceHash: string;
};

export type MemoryKnowledgeSourceReviewDecision = "accepted" | "rejected" | "duplicate" | "needs_more_context";

export type MemoryKnowledgeSourceGovernancePanelCopy = {
  sourceGovernance: string;
  ownerSourceInbox: string;
  ownerScope: string;
  ownerTeam: string;
  ownerAgent: string;
  ownerId: string;
  status: string;
  useActiveKnowledgeOwner: string;
  collectOwnerSource: string;
  cancelEdit: string;
  submitSource: string;
  sourceType: string;
  titleField: string;
  originalFilename: string;
  sourceCreatedAt: string;
  capturedBy: string;
  sourceHash: string;
  sourceRef: string;
  evidenceRange: string;
  summaryField: string;
  originalContent: string;
  reviewSource: string;
  centralSourceRegistry: string;
  sourceReviewNote: string;
  centralSourceId: string;
  originalPath: string;
  curationStatus: string;
  dedupeStatus: string;
  acceptSource: string;
  needsMoreContext: string;
  markDuplicate: string;
  rejectProposal: string;
  noInboxSources: string;
  centralPath: string;
  reviewedBy: string;
  reviewedAt: string;
  attachCentralSource: string;
  noCentralSources: string;
  pendingSources: string;
  acceptedSources: string;
  rejectedSources: string;
  duplicateSources: string;
  needsMoreContextSources: string;
  allSourceStatuses: string;
};

type MemoryKnowledgeSourceGovernancePanelProps = {
  copy: MemoryKnowledgeSourceGovernancePanelCopy;
  sourceOwnerType: MemoryKnowledgeSourceOwnerType;
  sourceOwnerId: string;
  sourceInboxStatus: MemoryKnowledgeSourceInboxStatusFilter;
  sourceCount: number;
  centralSourceCount: number;
  showOwnerSourceForm: boolean;
  ownerSourceDraft: MemoryKnowledgeOwnerSourceDraft;
  sourceReviewNote: string;
  duplicateCentralSourceId: string;
  ownerInboxSources: KnowledgeOwnerSource[];
  centralSources: KnowledgeCentralSource[];
  isSourceInboxPending: boolean;
  isCentralSourcesPending: boolean;
  knowledgeBusy: boolean;
  canSubmitOwnerSource: boolean;
  canAttachCentralSource: boolean;
  onSourceOwnerTypeChange: (value: MemoryKnowledgeSourceOwnerType) => void;
  onSourceOwnerIdChange: (value: string) => void;
  onSourceInboxStatusChange: (value: MemoryKnowledgeSourceInboxStatusFilter) => void;
  onApplyActiveKnowledgeOwner: () => void;
  onShowOwnerSourceFormChange: (value: boolean) => void;
  onOwnerSourceDraftChange: (draft: MemoryKnowledgeOwnerSourceDraft) => void;
  onSourceReviewNoteChange: (value: string) => void;
  onDuplicateCentralSourceIdChange: (value: string) => void;
  onSubmitOwnerSource: () => void;
  onReviewOwnerSource: (source: KnowledgeOwnerSource, decision: MemoryKnowledgeSourceReviewDecision) => void;
  onAttachCentralSource: (centralSourceId: string) => void;
  formatTimestamp: (value: string) => string;
};

const SOURCE_INBOX_STATUSES: MemoryKnowledgeSourceInboxStatusFilter[] = [
  "pending",
  "accepted",
  "rejected",
  "duplicate",
  "needs_more_context",
  "all",
];

const SOURCE_TYPES = [
  "manual_user_entry",
  "team_chat_refinement",
  "external_search_refinement",
  "pdf_refinement",
  "agent_authored",
  "runtime_evidence_refinement",
];

function sourceInboxStatusLabel(copy: MemoryKnowledgeSourceGovernancePanelCopy, status: MemoryKnowledgeSourceInboxStatusFilter | string) {
  if (status === "pending") {
    return copy.pendingSources;
  }
  if (status === "accepted") {
    return copy.acceptedSources;
  }
  if (status === "rejected") {
    return copy.rejectedSources;
  }
  if (status === "duplicate") {
    return copy.duplicateSources;
  }
  if (status === "needs_more_context") {
    return copy.needsMoreContextSources;
  }
  return copy.allSourceStatuses;
}

function sourceIsReviewable(source: KnowledgeOwnerSource) {
  return source.status === "pending" || source.status === "needs_more_context";
}

export function MemoryKnowledgeSourceGovernancePanel({
  copy,
  sourceOwnerType,
  sourceOwnerId,
  sourceInboxStatus,
  sourceCount,
  centralSourceCount,
  showOwnerSourceForm,
  ownerSourceDraft,
  sourceReviewNote,
  duplicateCentralSourceId,
  ownerInboxSources,
  centralSources,
  isSourceInboxPending,
  isCentralSourcesPending,
  knowledgeBusy,
  canSubmitOwnerSource,
  canAttachCentralSource,
  onSourceOwnerTypeChange,
  onSourceOwnerIdChange,
  onSourceInboxStatusChange,
  onApplyActiveKnowledgeOwner,
  onShowOwnerSourceFormChange,
  onOwnerSourceDraftChange,
  onSourceReviewNoteChange,
  onDuplicateCentralSourceIdChange,
  onSubmitOwnerSource,
  onReviewOwnerSource,
  onAttachCentralSource,
  formatTimestamp,
}: MemoryKnowledgeSourceGovernancePanelProps) {
  return (
    <section className={styles.managementPanel}>
      <div className={styles.managementHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.sourceGovernance}</p>
          <h2>{copy.ownerSourceInbox}</h2>
        </div>
        <span className={styles.countPill}>{sourceCount}</span>
      </div>
      <div className={styles.sourceGovernanceControls}>
        <label>
          <span>{copy.ownerScope}</span>
          <VNativeSelect value={sourceOwnerType} onChange={(event) => onSourceOwnerTypeChange(event.target.value as MemoryKnowledgeSourceOwnerType)}>
            <option value="team">{copy.ownerTeam}</option>
            <option value="agent">{copy.ownerAgent}</option>
          </VNativeSelect>
        </label>
        <label>
          <span>{copy.ownerId}</span>
          <VNativeInput value={sourceOwnerId} onChange={(event) => onSourceOwnerIdChange(event.target.value)} />
        </label>
        <label>
          <span>{copy.status}</span>
          <VNativeSelect value={sourceInboxStatus} onChange={(event) => onSourceInboxStatusChange(event.target.value as MemoryKnowledgeSourceInboxStatusFilter)}>
            {SOURCE_INBOX_STATUSES.map((status) => (
              <option key={status} value={status}>{sourceInboxStatusLabel(copy, status)}</option>
            ))}
          </VNativeSelect>
        </label>
        <VButton type="button" className={styles.detailActionButton} onClick={onApplyActiveKnowledgeOwner}>
          <Database size={14} />
          <span>{copy.useActiveKnowledgeOwner}</span>
        </VButton>
      </div>
      <div className={styles.sourceGovernanceGrid}>
        <div className={styles.sourceGovernanceColumn}>
          <div className={styles.managementHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.collectOwnerSource}</p>
              <h3>{copy.ownerSourceInbox}</h3>
            </div>
            <VButton type="button" className={styles.primaryActionButton} onClick={() => onShowOwnerSourceFormChange(!showOwnerSourceForm)}>
              <Pencil size={15} />
              <span>{showOwnerSourceForm ? copy.cancelEdit : copy.submitSource}</span>
            </VButton>
          </div>
          {showOwnerSourceForm ? (
            <>
              <div className={styles.knowledgeFormGrid}>
                <label>
                  <span>{copy.sourceType}</span>
                  <VNativeSelect value={ownerSourceDraft.sourceType} onChange={(event) => onOwnerSourceDraftChange({ ...ownerSourceDraft, sourceType: event.target.value })}>
                    {SOURCE_TYPES.map((type) => (
                      <option key={type} value={type}>{type}</option>
                    ))}
                  </VNativeSelect>
                </label>
                <label>
                  <span>{copy.titleField}</span>
                  <VNativeInput value={ownerSourceDraft.title} onChange={(event) => onOwnerSourceDraftChange({ ...ownerSourceDraft, title: event.target.value })} />
                </label>
                <label>
                  <span>{copy.originalFilename}</span>
                  <VNativeInput value={ownerSourceDraft.originalFilename} onChange={(event) => onOwnerSourceDraftChange({ ...ownerSourceDraft, originalFilename: event.target.value })} />
                </label>
                <label>
                  <span>{copy.sourceCreatedAt}</span>
                  <VNativeInput value={ownerSourceDraft.sourceCreatedAt} onChange={(event) => onOwnerSourceDraftChange({ ...ownerSourceDraft, sourceCreatedAt: event.target.value })} />
                </label>
                <label>
                  <span>{copy.capturedBy}</span>
                  <VNativeInput value={ownerSourceDraft.capturedBy} onChange={(event) => onOwnerSourceDraftChange({ ...ownerSourceDraft, capturedBy: event.target.value })} />
                </label>
                <label>
                  <span>{copy.sourceHash}</span>
                  <VNativeInput value={ownerSourceDraft.sourceHash} onChange={(event) => onOwnerSourceDraftChange({ ...ownerSourceDraft, sourceHash: event.target.value })} />
                </label>
                <label className={styles.wideField}>
                  <span>{copy.sourceRef}</span>
                  <VNativeTextarea rows={2} value={ownerSourceDraft.sourceRef} onChange={(event) => onOwnerSourceDraftChange({ ...ownerSourceDraft, sourceRef: event.target.value })} />
                </label>
                <label className={styles.wideField}>
                  <span>{copy.evidenceRange}</span>
                  <VNativeTextarea rows={2} value={ownerSourceDraft.evidenceRange} onChange={(event) => onOwnerSourceDraftChange({ ...ownerSourceDraft, evidenceRange: event.target.value })} />
                </label>
                <label className={styles.wideField}>
                  <span>{copy.summaryField}</span>
                  <VNativeTextarea rows={2} value={ownerSourceDraft.summary} onChange={(event) => onOwnerSourceDraftChange({ ...ownerSourceDraft, summary: event.target.value })} />
                </label>
                <label className={styles.wideField}>
                  <span>{copy.originalContent}</span>
                  <VNativeTextarea rows={4} value={ownerSourceDraft.originalContent} onChange={(event) => onOwnerSourceDraftChange({ ...ownerSourceDraft, originalContent: event.target.value })} />
                </label>
              </div>
              <div className={styles.formActionRow}>
                <VButton type="button" className={styles.primaryActionButton} onClick={onSubmitOwnerSource} isDisabled={!canSubmitOwnerSource}>
                  <Link2 size={15} />
                  <span>{copy.collectOwnerSource}</span>
                </VButton>
              </div>
            </>
          ) : (
            <VButton type="button"
                contentLayout="plain" className={styles.collapsedFormButton} onClick={() => onShowOwnerSourceFormChange(true)}>
              <Pencil size={15} />
              <span>{copy.submitSource}</span>
              <small>{ownerSourceDraft.sourceType}</small>
            </VButton>
          )}
        </div>
        <div className={styles.sourceGovernanceColumn}>
          <div className={styles.managementHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.reviewSource}</p>
              <h3>{copy.centralSourceRegistry}</h3>
            </div>
            <span className={styles.countPill}>{centralSourceCount}</span>
          </div>
          <div className={styles.sourceGovernanceControls}>
            <label>
              <span>{copy.sourceReviewNote}</span>
              <VNativeInput value={sourceReviewNote} onChange={(event) => onSourceReviewNoteChange(event.target.value)} />
            </label>
            <label>
              <span>{copy.centralSourceId}</span>
              <VNativeInput value={duplicateCentralSourceId} onChange={(event) => onDuplicateCentralSourceIdChange(event.target.value)} />
            </label>
          </div>
          <div className={styles.sourceRecordList}>
            {ownerInboxSources.map((source) => {
              const reviewable = sourceIsReviewable(source);
              return (
                <article key={source.inboxSourceId} className={styles.sourceRecord}>
                  <div className={styles.sourceRecordHeader}>
                    <strong>{source.title || source.inboxSourceId}</strong>
                    <span className={reviewable ? styles.statusPill : styles.statusPillMuted}>{source.status}</span>
                  </div>
                  <p>{source.summary || source.sourceType}</p>
                  <div className={styles.sourceRecordMeta}>
                    <span>{copy.originalPath}: {source.originalPath || "-"}</span>
                    <span>{copy.sourceHash}: {source.sourceHash || "-"}</span>
                    <span>{copy.curationStatus}: {source.curationStatus || "-"}</span>
                    <span>{copy.dedupeStatus}: {source.dedupeStatus || "-"}</span>
                  </div>
                  <div className={styles.sourceRecordActions}>
                    <VButton type="button" className={styles.detailActionButton} isDisabled={knowledgeBusy || !reviewable} onClick={() => onReviewOwnerSource(source, "accepted")}>
                      <CheckCircle2 size={14} />
                      <span>{copy.acceptSource}</span>
                    </VButton>
                    <VButton type="button" className={styles.detailActionButton} isDisabled={knowledgeBusy || !reviewable} onClick={() => onReviewOwnerSource(source, "needs_more_context")}>
                      <Eye size={14} />
                      <span>{copy.needsMoreContext}</span>
                    </VButton>
                    <VButton
                      type="button"
                      className={styles.detailActionButton}
                      isDisabled={knowledgeBusy || !reviewable || !duplicateCentralSourceId.trim()}
                      onClick={() => onReviewOwnerSource(source, "duplicate")}
                    >
                      <CopyIcon size={14} />
                      <span>{copy.markDuplicate}</span>
                    </VButton>
                    <VButton type="button" className={styles.detailActionButton} isDisabled={knowledgeBusy || !reviewable} onClick={() => onReviewOwnerSource(source, "rejected")}>
                      <XCircle size={14} />
                      <span>{copy.rejectProposal}</span>
                    </VButton>
                  </div>
                </article>
              );
            })}
            {!isSourceInboxPending && !ownerInboxSources.length ? (
              <section className={styles.emptyDetail}>
                <FileText size={20} />
                <strong>{copy.noInboxSources}</strong>
              </section>
            ) : null}
          </div>
        </div>
      </div>
      <div className={styles.sourceRecordList}>
        {centralSources.map((source) => (
          <article key={source.centralSourceId} className={styles.sourceRecord}>
            <div className={styles.sourceRecordHeader}>
              <strong>{source.title || source.centralSourceId}</strong>
              <span className={styles.statusPill}>{source.status}</span>
            </div>
            <p>{source.summary || source.sourceType}</p>
            <div className={styles.sourceRecordMeta}>
              <span>{copy.centralSourceId}: {source.centralSourceId}</span>
              <span>{copy.centralPath}: {source.centralPath || "-"}</span>
              <span>{copy.originalPath}: {source.originOriginalPath || "-"}</span>
              <span>{copy.reviewedBy}: {source.acceptedByAgentId || "-"}</span>
              <span>{copy.reviewedAt}: {formatTimestamp(source.acceptedAt)}</span>
            </div>
            <div className={styles.sourceRecordActions}>
              <VButton type="button" className={styles.detailActionButton} isDisabled={!canAttachCentralSource} onClick={() => onAttachCentralSource(source.centralSourceId)}>
                <Link2 size={14} />
                <span>{copy.attachCentralSource}</span>
              </VButton>
            </div>
          </article>
        ))}
        {!isCentralSourcesPending && !centralSources.length ? (
          <section className={styles.emptyDetail}>
            <Database size={20} />
            <strong>{copy.noCentralSources}</strong>
          </section>
        ) : null}
      </div>
    </section>
  );
}
