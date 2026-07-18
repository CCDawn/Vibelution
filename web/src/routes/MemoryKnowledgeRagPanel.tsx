import { Link2 } from "lucide-react";

import type { KnowledgeRagContext, KnowledgeRagHealthPayload, KnowledgeRagProviderHealth, KnowledgeRagRetrievalPayload } from "../api/types";
import { VTooltip } from "../components/vui";
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
}: MemoryKnowledgeRagPanelProps) {
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
