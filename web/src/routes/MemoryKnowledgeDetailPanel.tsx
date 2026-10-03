import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { AlertCircle, FileText, RotateCcw } from "lucide-react";

import {
  createKnowledgeRevisionProposal,
  fetchKnowledgeItemBody,
  readKnowledgeItemBodyAllPages,
} from "../api/knowledgeLifecycle";
import type {
  KnowledgeItem,
  KnowledgeItemBodyPage,
  KnowledgeItemHistoryPage,
  KnowledgeTracePayload,
  TeamKnowledgeBase,
} from "../api/types";
import { VButton, VDialog, VNativeInput, VStateSurface, VStatusChip, VStringSelect, VTextarea } from "../components/vui";
import styles from "./MemoryKnowledgeDetailPanel.styles";
import {
  MemoryKnowledgeItemRatingCard,
  type MemoryKnowledgeItemRatingCardCopy,
  type MemoryKnowledgeLifecycleMode,
  type MemoryKnowledgeRatingDraft,
} from "./MemoryKnowledgeItemRatingCard";

export type MemoryKnowledgeDetailPanelCopy = MemoryKnowledgeItemRatingCardCopy & {
  formalKnowledge: string;
  selectedKnowledgeDetail: string;
  sourceChain: string;
  traceability: string;
  sourceArtifacts: string;
  pendingProposals: string;
  ratingSuggestions: string;
  loading: string;
  confidence: string;
  stability: string;
  reviewPriority: string;
  markingReason: string;
  submitRatingSuggestion: string;
  noMatches: string;
  knowledgeRevisionDialog: string;
  knowledgeBodyDialog: string;
  knowledgeSourceDialog: string;
  knowledgeHistoryDialog: string;
  knowledgeBodyLoading: string;
  knowledgeBodyEmpty: string;
  sourceBodyUnavailable: string;
  knowledgeBodyTrustNotice: string;
  knowledgeSourceSelector: string;
  knowledgeHistoryEmpty: string;
  knowledgeHistoryMore: string;
  knowledgeVersion: string;
  revisionTitle: string;
  revisionSummary: string;
  revisionContent: string;
  revisionReason: string;
  revisionReasonPlaceholder: string;
  submitRevision: string;
  cancel: string;
  revisionSubmitted: string;
  revisionSubmitPending: string;
  reloadLatestKnowledge: string;
};

type MemoryKnowledgeDetailPanelProps = {
  copy: MemoryKnowledgeDetailPanelCopy;
  activeKnowledgeBase: TeamKnowledgeBase | null | undefined;
  traceTargetId: string;
  trace: KnowledgeTracePayload | undefined;
  knowledgeItems: KnowledgeItem[];
  knowledgeItemsPending: boolean;
  knowledgeItemsErrorText?: string;
  ratingDraft: MemoryKnowledgeRatingDraft;
  knowledgeBusy: boolean;
  agentId: string;
  onLifecycleChanged: () => void;
  onTraceTargetChange: (value: string) => void;
  onRatingDraftChange: (draft: MemoryKnowledgeRatingDraft) => void;
  onUpdateKnowledgeRating: (item: KnowledgeItem) => void;
};

export function MemoryKnowledgeDetailPanel({
  copy,
  activeKnowledgeBase,
  traceTargetId,
  trace,
  knowledgeItems,
  knowledgeItemsPending,
  knowledgeItemsErrorText,
  ratingDraft,
  knowledgeBusy,
  agentId,
  onLifecycleChanged,
  onTraceTargetChange,
  onRatingDraftChange,
  onUpdateKnowledgeRating,
}: MemoryKnowledgeDetailPanelProps) {
  const activeKnowledgeBaseId = activeKnowledgeBase?.scopedKnowledgeBaseId || activeKnowledgeBase?.knowledgeBaseId || "";
  const activeKnowledgeContextKey = JSON.stringify([activeKnowledgeBaseId, agentId]);
  const [dialogMode, setDialogMode] = useState<MemoryKnowledgeLifecycleMode | null>(null);
  const [dialogItem, setDialogItem] = useState<KnowledgeItem | null>(null);
  const [dialogContextKey, setDialogContextKey] = useState("");
  const [dialogSourceId, setDialogSourceId] = useState("");
  const [bodyPage, setBodyPage] = useState<KnowledgeItemBodyPage | null>(null);
  const [historyPage, setHistoryPage] = useState<KnowledgeItemHistoryPage | null>(null);
  const [historyVersions, setHistoryVersions] = useState<KnowledgeItemHistoryPage["versions"]>([]);
  const [dialogPending, setDialogPending] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const [revisionDraft, setRevisionDraft] = useState<{ title: string; summary: string; content: string; reason: string; expectedHash: string } | null>(null);
  const [revisionSubmitted, setRevisionSubmitted] = useState(false);
  const [revisionSubmitting, setRevisionSubmitting] = useState(false);
  const lifecycleActionVersionRef = useRef(0);
  const dialogMatchesActiveContext = Boolean(dialogMode && dialogItem && dialogContextKey === activeKnowledgeContextKey);

  useLayoutEffect(() => {
    lifecycleActionVersionRef.current += 1;
  }, [activeKnowledgeContextKey]);

  useEffect(() => {
    if (!dialogItem || !dialogMode || !agentId || dialogContextKey !== activeKnowledgeContextKey) {
      return;
    }
    const controller = new AbortController();
    let current = true;
    setDialogPending(true);
    setDialogError("");
    setBodyPage(null);
    setHistoryPage(null);
    setHistoryVersions([]);
    setRevisionSubmitted(false);
    setRevisionSubmitting(false);

    const knowledgeBaseId = activeKnowledgeBaseId;
    if (!knowledgeBaseId) {
      setDialogError(copy.selectedKnowledgeDetail);
      setDialogPending(false);
      return () => controller.abort();
    }

    const load = async () => {
      try {
        if (dialogMode === "history") {
          const page = await fetchKnowledgeItemBody({
            knowledgeBaseId,
            knowledgeItemId: dialogItem.knowledgeItemId,
            agentId,
            readMode: "history",
            offset: 0,
            maxChars: 25,
            signal: controller.signal,
          });
          if (current) {
            setHistoryPage(page);
            setHistoryVersions(page.versions);
            if (page.offsetUnit !== "versions") {
              setDialogError(copy.knowledgeBodyEmpty);
            }
          }
          return;
        }

        const page = await readKnowledgeItemBodyAllPages(dialogMode === "source"
          ? {
            knowledgeBaseId,
            knowledgeItemId: dialogItem.knowledgeItemId,
            agentId,
            readMode: "source",
            sourceArtifactId: dialogSourceId,
            signal: controller.signal,
          }
          : {
            knowledgeBaseId,
            knowledgeItemId: dialogItem.knowledgeItemId,
            agentId,
            readMode: "item",
            signal: controller.signal,
          });
        if (!current) {
          return;
        }
        if (dialogMode === "source" && page.sourceBodyStatus !== "source_body_available") {
          setDialogError(copy.sourceBodyUnavailable);
          return;
        }
        setBodyPage(page);
        if (dialogMode === "revision") {
          setRevisionDraft({
            title: dialogItem.title,
            summary: dialogItem.summary,
            content: page.content,
            reason: "",
            expectedHash: page.contentSha256 || "",
          });
        }
      } catch (error) {
        if (current && !controller.signal.aborted) {
          setDialogError(error instanceof Error ? error.message : String(error));
        }
      } finally {
        if (current) {
          setDialogPending(false);
        }
      }
    };

    void load();
    return () => {
      current = false;
      controller.abort();
    };
  }, [activeKnowledgeBaseId, activeKnowledgeContextKey, agentId, copy.knowledgeBodyEmpty, copy.selectedKnowledgeDetail, copy.sourceBodyUnavailable, dialogContextKey, dialogItem, dialogMode, dialogSourceId]);

  useEffect(() => {
    if (!dialogMode || dialogContextKey === activeKnowledgeContextKey) {
      return;
    }
    setDialogMode(null);
    setDialogItem(null);
    setDialogContextKey("");
    setDialogSourceId("");
    setBodyPage(null);
    setHistoryPage(null);
    setHistoryVersions([]);
    setDialogPending(false);
    setDialogError("");
    setRevisionDraft(null);
    setRevisionSubmitted(false);
    setRevisionSubmitting(false);
  }, [activeKnowledgeContextKey, dialogContextKey, dialogMode]);

  useLayoutEffect(() => () => {
    lifecycleActionVersionRef.current += 1;
  }, []);

  const openLifecycleDialog = (item: KnowledgeItem, mode: MemoryKnowledgeLifecycleMode) => {
    lifecycleActionVersionRef.current += 1;
    setDialogItem(item);
    setDialogMode(mode);
    setDialogContextKey(activeKnowledgeContextKey);
    setDialogSourceId(mode === "source" ? item.sourceArtifactIds?.[0] || "" : "");
    setBodyPage(null);
    setHistoryPage(null);
    setHistoryVersions([]);
    setDialogPending(false);
    setRevisionDraft(null);
    setRevisionSubmitted(false);
    setDialogError("");
    setRevisionSubmitting(false);
    onTraceTargetChange(item.knowledgeItemId);
  };

  const closeLifecycleDialog = () => {
    if (dialogPending) {
      return;
    }
    lifecycleActionVersionRef.current += 1;
    setDialogMode(null);
    setDialogItem(null);
    setDialogContextKey("");
    setDialogSourceId("");
    setBodyPage(null);
    setHistoryPage(null);
    setHistoryVersions([]);
    setRevisionDraft(null);
    setRevisionSubmitted(false);
    setDialogError("");
    setRevisionSubmitting(false);
  };

  const loadMoreHistory = async () => {
    if (!dialogMatchesActiveContext || !dialogItem || !historyPage?.hasMore || historyPage.nextOffset === null || !activeKnowledgeBase || !agentId) {
      return;
    }
    const actionVersion = ++lifecycleActionVersionRef.current;
    setDialogPending(true);
    setDialogError("");
    try {
      const page = await fetchKnowledgeItemBody({
        knowledgeBaseId: activeKnowledgeBase.scopedKnowledgeBaseId || activeKnowledgeBase.knowledgeBaseId,
        knowledgeItemId: dialogItem.knowledgeItemId,
        agentId,
        readMode: "history",
        offset: historyPage.nextOffset,
        maxChars: 25,
      });
      if (actionVersion !== lifecycleActionVersionRef.current) {
        return;
      }
      if (page.offsetUnit !== "versions" || page.offset !== historyPage.nextOffset) {
        throw new Error(copy.knowledgeBodyEmpty);
      }
      setHistoryVersions((previous) => [...previous, ...page.versions]);
      setHistoryPage(page);
    } catch (error) {
      if (actionVersion === lifecycleActionVersionRef.current) {
        setDialogError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (actionVersion === lifecycleActionVersionRef.current) {
        setDialogPending(false);
      }
    }
  };

  const submitRevision = async () => {
    if (!dialogMatchesActiveContext || dialogMode !== "revision" || !dialogItem || !revisionDraft || !activeKnowledgeBase || !agentId || !activeKnowledgeBase.permissions.canPropose) {
      return;
    }
    if (!revisionDraft.expectedHash || !revisionDraft.reason.trim() || !revisionDraft.content.trim()) {
      setDialogError(copy.revisionReasonPlaceholder);
      return;
    }
    const actionVersion = ++lifecycleActionVersionRef.current;
    setDialogPending(true);
    setRevisionSubmitting(true);
    setDialogError("");
    try {
      await createKnowledgeRevisionProposal(
        activeKnowledgeBase.scopedKnowledgeBaseId || activeKnowledgeBase.knowledgeBaseId,
        {
          sourceArtifactIds: dialogItem.sourceArtifactIds || [],
          title: revisionDraft.title.trim(),
          summary: revisionDraft.summary.trim(),
          content: revisionDraft.content,
          proposedByAgentId: agentId,
          supersedesKnowledgeItemId: dialogItem.knowledgeItemId,
          expectedContentSha256: revisionDraft.expectedHash,
          revisionReason: revisionDraft.reason.trim(),
          tags: dialogItem.tags || [],
        },
      );
      if (actionVersion !== lifecycleActionVersionRef.current) {
        return;
      }
      setRevisionSubmitted(true);
      onLifecycleChanged();
    } catch (error) {
      if (actionVersion === lifecycleActionVersionRef.current) {
        setDialogError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (actionVersion === lifecycleActionVersionRef.current) {
        setDialogPending(false);
        setRevisionSubmitting(false);
      }
    }
  };

  const dialogTitle = dialogMode === "source"
    ? copy.knowledgeSourceDialog
    : dialogMode === "history"
      ? copy.knowledgeHistoryDialog
      : dialogMode === "revision"
        ? copy.knowledgeRevisionDialog
        : copy.knowledgeBodyDialog;

  return (
    <aside className={styles.detailPanel}>
      <div className={styles.detailHeader}>
        <p className={styles.panelEyebrow}>{copy.formalKnowledge}</p>
        <h2>{activeKnowledgeBase?.name ?? copy.selectedKnowledgeDetail}</h2>
      </div>
      <section className={styles.managementPanel}>
        <div className={styles.managementHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.sourceChain}</p>
            <h2>{copy.traceability}</h2>
          </div>
        </div>
        <label>
          <span>{copy.traceability}</span>
          <VNativeInput value={traceTargetId} onChange={(event) => onTraceTargetChange(event.target.value)} placeholder="source / proposal / item / rating id" />
        </label>
        {trace ? (
          <div className={styles.metaGrid}>
            <span>{copy.sourceArtifacts}: {trace.summary.sourceArtifacts ?? 0}</span>
            <span>{copy.pendingProposals}: {trace.summary.proposals ?? 0}</span>
            <span>{copy.formalKnowledge}: {trace.summary.items ?? 0}</span>
            <span>{copy.ratingSuggestions}: {trace.summary.ratingSuggestions ?? 0}</span>
          </div>
        ) : null}
      </section>
      {knowledgeItemsPending ? <VStateSurface tone="loading" title={copy.loading} skeletonLines={2} /> : null}
      <div className={styles.knowledgeItems}>
        {knowledgeItems.map((item) => (
          <MemoryKnowledgeItemRatingCard
            key={item.knowledgeItemId}
            copy={copy}
            item={item}
            ratingDraft={ratingDraft}
            canRate={Boolean(activeKnowledgeBase?.permissions.canRate)}
            canRead={Boolean(activeKnowledgeBase?.permissions.canRead && agentId)}
            canPropose={Boolean(activeKnowledgeBase?.permissions.canPropose && agentId)}
            knowledgeBusy={knowledgeBusy}
            onRatingDraftChange={onRatingDraftChange}
            onUpdateKnowledgeRating={onUpdateKnowledgeRating}
            onOpenLifecycleView={openLifecycleDialog}
          />
        ))}
        {knowledgeItemsErrorText ? (
          <section className={styles.emptyDetail} role="alert">
            <FileText size={22} />
            <strong>{knowledgeItemsErrorText}</strong>
          </section>
        ) : null}
        {!knowledgeItemsPending && !knowledgeItemsErrorText && !knowledgeItems.length ? (
          <section className={styles.emptyDetail}>
            <FileText size={22} />
            <strong>{copy.noMatches}</strong>
          </section>
        ) : null}
      </div>
      <VDialog
        open={dialogMatchesActiveContext}
        onOpenChange={(open) => {
          if (!open) closeLifecycleDialog();
        }}
        title={dialogTitle}
        description={dialogItem?.title}
        size="lg"
        className={styles.lifecycleDialog}
        contentClassName={styles.lifecycleDialogContent}
        footer={dialogMode === "revision" ? (
          <>
            <VButton type="button" variant="secondary" onPress={closeLifecycleDialog} isDisabled={dialogPending}>
              {copy.cancel}
            </VButton>
            <VButton
              type="button"
              variant="primary"
              onPress={() => void submitRevision()}
              isDisabled={dialogPending || revisionSubmitted || !activeKnowledgeBase?.permissions.canPropose || !revisionDraft?.reason.trim() || !revisionDraft?.content.trim() || !revisionDraft?.expectedHash}
              isPending={revisionSubmitting}
            >
              {revisionSubmitting ? copy.revisionSubmitPending : copy.submitRevision}
            </VButton>
          </>
        ) : (
          <VButton type="button" variant="secondary" onPress={closeLifecycleDialog} isDisabled={dialogPending}>
            {copy.cancel}
          </VButton>
        )}
      >
        {dialogMatchesActiveContext && dialogPending && !revisionSubmitted ? <VStateSurface tone="loading" title={copy.knowledgeBodyLoading} skeletonLines={3} /> : null}
        {dialogError ? (
          <section className={styles.lifecycleError} role="alert">
            <AlertCircle size={16} aria-hidden="true" />
            <span>{dialogError}</span>
            {dialogMode === "revision" ? (
              <VButton type="button" density="compact" onPress={() => dialogItem && openLifecycleDialog(dialogItem, "revision")} icon={<RotateCcw size={13} />}>
                {copy.reloadLatestKnowledge}
              </VButton>
            ) : null}
          </section>
        ) : null}
        {dialogMode === "revision" ? (
          revisionSubmitted ? (
            <VStateSurface tone="info" title={copy.revisionSubmitted}>
              <p>{copy.revisionReason}</p>
            </VStateSurface>
          ) : revisionDraft ? (
            <div className={styles.revisionForm}>
              <label>
                <span>{copy.revisionTitle}</span>
                <VNativeInput value={revisionDraft.title} onChange={(event) => setRevisionDraft({ ...revisionDraft, title: event.target.value })} />
              </label>
              <label>
                <span>{copy.revisionSummary}</span>
                <VNativeInput value={revisionDraft.summary} onChange={(event) => setRevisionDraft({ ...revisionDraft, summary: event.target.value })} />
              </label>
              <label>
                <span>{copy.revisionContent}</span>
                <VTextarea rows={14} value={revisionDraft.content} onChange={(event) => setRevisionDraft({ ...revisionDraft, content: event.target.value })} />
              </label>
              <label>
                <span>{copy.revisionReason}</span>
                <VTextarea rows={3} value={revisionDraft.reason} placeholder={copy.revisionReasonPlaceholder} onChange={(event) => setRevisionDraft({ ...revisionDraft, reason: event.target.value })} />
              </label>
            </div>
          ) : null
        ) : null}
        {dialogMode === "item" || dialogMode === "source" ? (
          <div className={styles.bodyReader}>
            {dialogMode === "source" && (dialogItem?.sourceArtifactIds.length ?? 0) > 1 ? (
              <label>
                <span>{copy.knowledgeSourceSelector}</span>
                <VStringSelect
                  ariaLabel={copy.knowledgeSourceSelector}
                  value={dialogSourceId}
                  onValueChange={(sourceArtifactId) => {
                    lifecycleActionVersionRef.current += 1;
                    setDialogSourceId(sourceArtifactId);
                    setBodyPage(null);
                    setDialogError("");
                    setDialogPending(false);
                  }}
                  options={(dialogItem?.sourceArtifactIds || []).map((sourceArtifactId) => ({ value: sourceArtifactId, label: sourceArtifactId }))}
                />
              </label>
            ) : null}
            {bodyPage ? <pre className={styles.knowledgeBody}>{bodyPage.content || copy.knowledgeBodyEmpty}</pre> : null}
            {bodyPage ? <p className={styles.trustNotice}>{copy.knowledgeBodyTrustNotice}</p> : null}
          </div>
        ) : null}
        {dialogMode === "history" ? (
          <div className={styles.historyList}>
            {!dialogPending && !dialogError && !historyVersions.length ? (
              <section className={styles.emptyDetail}><strong>{copy.knowledgeHistoryEmpty}</strong></section>
            ) : null}
            {historyVersions.map((version) => (
              <article key={version.knowledgeItemId} className={styles.historyVersion}>
                <div className={styles.historyVersionHeader}>
                  <strong>{copy.knowledgeVersion} {version.revision}</strong>
                  <VStatusChip tone={version.state === "active" ? "success" : "warning"}>{version.state}</VStatusChip>
                </div>
                <p>{version.title}</p>
                <span>{version.knowledgeItemId} · {version.contentLength} chars</span>
                {version.reviewedAt ? <span>{version.reviewedAt}</span> : null}
                {version.revisionReason ? <p>{version.revisionReason}</p> : null}
              </article>
            ))}
            {historyPage?.hasMore ? (
              <VButton type="button" onPress={() => void loadMoreHistory()} isDisabled={dialogPending} isPending={dialogPending}>
                {copy.knowledgeHistoryMore}
              </VButton>
            ) : null}
          </div>
        ) : null}
      </VDialog>
    </aside>
  );
}
