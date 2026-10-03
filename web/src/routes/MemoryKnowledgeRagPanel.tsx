import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Link2 } from "lucide-react";

import { buildKnowledgeSemanticIndex, fetchKnowledgeSemanticIndexHealth } from "../api/knowledgeLifecycle";
import type {
  KnowledgeRagContext,
  KnowledgeRagHealthPayload,
  KnowledgeRagProviderHealth,
  KnowledgeRagRetrievalPayload,
  KnowledgeSemanticIndexBuildResponse,
  KnowledgeSemanticIndexHealthPayload,
} from "../api/types";
import { VButton, VStatusChip, VTooltip } from "../components/vui";
import styles from "./MemoryKnowledgeRagPanel.styles";

export type MemoryKnowledgeRagPanelCopy = {
  ragRetrieval: string;
  ragContextCandidates: string;
  ragRetrievalHint: string;
  ragHealth: string;
  ragProvider: string;
  ragVector: string;
  ragIndexed: string;
  ragStale: string;
  ragNoPromptInjection: string;
  ragCitations: string;
  ragNoContexts: string;
  noDirectApply: string;
  loading: string;
  yes: string;
  no: string;
  semanticIndex: string;
  semanticIndexStatus: string;
  semanticIndexModel: string;
  semanticIndexReady: string;
  semanticIndexDegraded: string;
  semanticIndexUnknown: string;
  semanticIndexPrepared: string;
  semanticIndexNotPrepared: string;
  semanticIndexLoaded: string;
  semanticIndexNotLoaded: string;
  semanticIndexIndexed: string;
  semanticIndexMissing: string;
  semanticIndexTotal: string;
  semanticIndexOfflineNote: string;
  prepareAndBuildSemanticIndex: string;
  rebuildSemanticIndex: string;
  semanticIndexBuilding: string;
  semanticIndexBuildCompleted: string;
  semanticIndexBuildFailed: string;
  semanticIndexReviewRequired: string;
  semanticIndexUnavailable: string;
};

type MemoryKnowledgeRagPanelProps = {
  copy: MemoryKnowledgeRagPanelCopy;
  contexts: KnowledgeRagContext[];
  health: KnowledgeRagHealthPayload | undefined;
  providerHealth: KnowledgeRagProviderHealth | undefined;
  retrievalPolicy: KnowledgeRagHealthPayload["retrievalPolicy"] | KnowledgeRagRetrievalPayload["retrievalPolicy"] | undefined;
  contextCount: number;
  citationCount: number;
  isPending: boolean;
  knowledgeBaseId: string;
  agentId: string;
  canReviewKnowledge: boolean;
  onIndexBuilt: () => void;
};

export function MemoryKnowledgeRagPanel({
  copy,
  contexts,
  health,
  providerHealth,
  retrievalPolicy,
  contextCount,
  citationCount,
  isPending,
  knowledgeBaseId,
  agentId,
  canReviewKnowledge,
  onIndexBuilt,
}: MemoryKnowledgeRagPanelProps) {
  const mountedRef = useRef(false);
  const buildKnowledgeBaseIdRef = useRef(knowledgeBaseId);
  const [semanticIndexHealth, setSemanticIndexHealth] = useState<KnowledgeSemanticIndexHealthPayload | null>(null);
  const [semanticIndexHealthPending, setSemanticIndexHealthPending] = useState(false);
  const [semanticIndexError, setSemanticIndexError] = useState("");
  const [semanticIndexBuildError, setSemanticIndexBuildError] = useState("");
  const [semanticIndexBuildResult, setSemanticIndexBuildResult] = useState<KnowledgeSemanticIndexBuildResponse | null>(null);
  const [semanticIndexBuildPending, setSemanticIndexBuildPending] = useState(false);

  useLayoutEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useLayoutEffect(() => {
    if (buildKnowledgeBaseIdRef.current === knowledgeBaseId) {
      return;
    }
    buildKnowledgeBaseIdRef.current = knowledgeBaseId;
    setSemanticIndexBuildError("");
    setSemanticIndexBuildResult(null);
    setSemanticIndexBuildPending(false);
  }, [knowledgeBaseId]);

  useEffect(() => {
    const controller = new AbortController();
    setSemanticIndexHealth(null);
    setSemanticIndexError("");
    setSemanticIndexBuildError("");
    setSemanticIndexBuildResult(null);
    if (!agentId) {
      setSemanticIndexHealthPending(false);
      return () => controller.abort();
    }
    setSemanticIndexHealthPending(true);
    setSemanticIndexError("");
    void fetchKnowledgeSemanticIndexHealth({ agentId, signal: controller.signal })
      .then((payload) => {
        if (!controller.signal.aborted && mountedRef.current) {
          setSemanticIndexHealth(payload);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted && mountedRef.current) {
          setSemanticIndexError(error instanceof Error ? error.message : String(error));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && mountedRef.current) {
          setSemanticIndexHealthPending(false);
        }
      });
    return () => controller.abort();
  }, [agentId]);

  const refreshSemanticIndexHealth = async () => {
    if (!agentId || !mountedRef.current) {
      return;
    }
    setSemanticIndexHealthPending(true);
    setSemanticIndexError("");
    try {
      const payload = await fetchKnowledgeSemanticIndexHealth({ agentId });
      if (mountedRef.current) {
        setSemanticIndexHealth(payload);
      }
    } catch (error) {
      if (mountedRef.current) {
        setSemanticIndexError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (mountedRef.current) {
        setSemanticIndexHealthPending(false);
      }
    }
  };

  const submitSemanticIndexBuild = async () => {
    if (!knowledgeBaseId || !agentId || !canReviewKnowledge || semanticIndexBuildPending) {
      return;
    }
    const requestedKnowledgeBaseId = knowledgeBaseId;
    const isCurrentBuildScope = () =>
      mountedRef.current && buildKnowledgeBaseIdRef.current === requestedKnowledgeBaseId;
    const prepareModel = !semanticIndexHealth?.modelPrepared;
    setSemanticIndexBuildPending(true);
    setSemanticIndexBuildError("");
    setSemanticIndexBuildResult(null);
    try {
      const result = await buildKnowledgeSemanticIndex(requestedKnowledgeBaseId, { actorAgentId: agentId, prepareModel });
      if (!isCurrentBuildScope()) {
        return;
      }
      setSemanticIndexBuildResult(result);
      if (result.status !== "ready") {
        const resultStatus = result.status === "degraded"
          ? copy.semanticIndexDegraded
          : result.status === "unavailable"
            ? copy.semanticIndexUnavailable
            : copy.semanticIndexUnknown;
        setSemanticIndexBuildError(`${copy.semanticIndexBuildFailed}: ${resultStatus}`);
      }
      await refreshSemanticIndexHealth();
      if (isCurrentBuildScope()) {
        onIndexBuilt();
      }
    } catch (error) {
      if (!isCurrentBuildScope()) {
        return;
      }
      setSemanticIndexBuildError(error instanceof Error ? error.message : String(error));
      await refreshSemanticIndexHealth();
    } finally {
      if (isCurrentBuildScope()) {
        setSemanticIndexBuildPending(false);
      }
    }
  };

  const semanticIndexTone = semanticIndexHealth?.status === "ready"
    ? "success"
    : semanticIndexHealth?.status === "unavailable"
      ? "danger"
      : "warning";
  const semanticIndexStatusLabel = semanticIndexHealth?.status === "ready"
    ? copy.semanticIndexReady
    : semanticIndexHealth?.status === "degraded"
      ? copy.semanticIndexDegraded
      : semanticIndexHealth?.status === "unavailable"
        ? copy.semanticIndexUnavailable
        : copy.semanticIndexUnknown;

  return (
    <VTooltip content={copy.ragRetrievalHint} width="wide">
      <section
        className={styles.ragPreviewPanel}
        aria-label={`${copy.ragRetrieval} · ${copy.ragRetrievalHint}`}
        tabIndex={0}
      >
        <div className={styles.ragPreviewHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.ragRetrieval}</p>
            <h3>{copy.ragContextCandidates}</h3>
          </div>
          <span className={styles.countPill}>{contextCount}</span>
        </div>
        <div className={styles.ragHealthStrip} aria-label={copy.ragHealth}>
          <span>{copy.ragProvider}: {providerHealth?.provider ?? health?.provider ?? "local"} · {providerHealth?.status ?? health?.status ?? copy.loading}</span>
          <span>{copy.ragVector}: {providerHealth?.vectorEnabled ? copy.yes : copy.no}</span>
          <span>{copy.ragIndexed}: {providerHealth?.indexedItemCount ?? 0}</span>
          <span data-stale={Number(providerHealth?.staleItemCount ?? 0) > 0 ? "true" : "false"}>
            {copy.ragStale}: {providerHealth?.staleItemCount ?? 0}
          </span>
        </div>
        <div className={styles.ragPolicyStrip}>
          <span>{copy.ragNoPromptInjection}: {retrievalPolicy?.injectsPromptByDefault ? copy.no : copy.yes}</span>
          <span>ACL: {retrievalPolicy?.honorsKnowledgeAcl ? copy.yes : copy.no}</span>
          <span>{copy.noDirectApply}: {retrievalPolicy?.mutatesFormalKnowledge ? copy.no : copy.yes}</span>
          <span>{copy.ragCitations}: {citationCount}</span>
        </div>
        <section className={styles.semanticIndexPanel} aria-label={copy.semanticIndex}>
          <div className={styles.semanticIndexHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.semanticIndex}</p>
              <div className={styles.semanticIndexStatus} aria-label={copy.semanticIndexStatus}>
                <VStatusChip tone={semanticIndexHealth ? semanticIndexTone : "neutral"}>
                  {semanticIndexHealth ? semanticIndexStatusLabel : semanticIndexHealthPending ? copy.loading : copy.semanticIndexUnavailable}
                </VStatusChip>
                <span>{copy.semanticIndexModel}: {semanticIndexHealth?.embeddingModel || "BGE"}</span>
              </div>
            </div>
            <VButton
              type="button"
              variant={semanticIndexHealth?.modelPrepared ? "secondary" : "primary"}
              isDisabled={!canReviewKnowledge || !knowledgeBaseId || !agentId || semanticIndexBuildPending || semanticIndexHealthPending}
              isPending={semanticIndexBuildPending}
              tooltip={!canReviewKnowledge ? copy.semanticIndexReviewRequired : undefined}
              onPress={() => void submitSemanticIndexBuild()}
            >
              {semanticIndexBuildPending
                ? copy.semanticIndexBuilding
                : semanticIndexHealth?.modelPrepared
                  ? copy.rebuildSemanticIndex
                  : copy.prepareAndBuildSemanticIndex}
            </VButton>
          </div>
          <div className={styles.semanticIndexMeta}>
            <span>{semanticIndexHealth?.modelPrepared ? copy.semanticIndexPrepared : copy.semanticIndexNotPrepared}</span>
            <span>{semanticIndexHealth?.modelLoaded ? copy.semanticIndexLoaded : copy.semanticIndexNotLoaded}</span>
            <span>{copy.semanticIndexIndexed}: {semanticIndexHealth?.indexedItemCount ?? 0}</span>
            <span>{copy.semanticIndexMissing}: {semanticIndexHealth?.missingItemCount ?? 0}</span>
            <span>{copy.semanticIndexTotal}: {semanticIndexHealth?.indexableItemCount ?? 0}</span>
          </div>
          <p className={styles.semanticIndexNote}>{copy.semanticIndexOfflineNote}</p>
          {semanticIndexError ? <p className={styles.semanticIndexError} role="alert">{semanticIndexError}</p> : null}
          {semanticIndexBuildError ? <p className={styles.semanticIndexError} role="alert">{semanticIndexBuildError}</p> : null}
          {semanticIndexBuildResult ? (
            <p className={styles.semanticIndexNote} role="status">
              {copy.semanticIndexBuildCompleted}: {semanticIndexBuildResult.indexedItemCount}
              {semanticIndexBuildResult.candidateItemCount === undefined ? "" : ` / ${semanticIndexBuildResult.candidateItemCount}`}
            </p>
          ) : null}
        </section>
        <div className={styles.ragContextList}>
          {contexts.map((context) => (
            <article key={context.contextId} className={styles.ragContextCard}>
              <div className={styles.ragContextMeta}>
                <strong>{context.rank}. {context.title || context.contextId}</strong>
                <span>{Math.round(Number(context.score || 0) * 100)}% · {context.matchReason || context.retrievalMode}</span>
              </div>
              <p>{context.text}</p>
              <small>
                {copy.ragCitations}: {context.source.teamName || context.source.teamId} · {context.source.knowledgeBaseName || context.source.knowledgeBaseId} · {context.source.knowledgeItemId}
              </small>
            </article>
          ))}
          {!isPending && !contexts.length ? (
            <section className={styles.emptyDetail}>
              <Link2 size={20} />
              <strong>{copy.ragNoContexts}</strong>
            </section>
          ) : null}
        </div>
      </section>
    </VTooltip>
  );
}
