import { Search } from "lucide-react";

import type {
  KnowledgeRagContext,
  KnowledgeRagHealthPayload,
  KnowledgeRagProviderHealth,
  KnowledgeRagRetrievalPayload,
  KnowledgeSearchPayload,
} from "../api/types";
import { VNativeInput, VNativeSelect } from "../components/vui";
import { MemoryKnowledgeRagPanel, type MemoryKnowledgeRagPanelCopy } from "./MemoryKnowledgeRagPanel";
import styles from "./MemoryRoute.styles";

export type MemoryKnowledgeSearchDraft = {
  query: string;
  tags: string;
  searchMode: "exact" | "semantic" | "hybrid";
  ragTopK: number;
  ragMaxContextChars: number;
};

export type MemoryKnowledgeSearchPanelCopy = MemoryKnowledgeRagPanelCopy & {
  knowledgeSearch: string;
  governance: string;
  searchQuery: string;
  tags: string;
  searchMode: string;
  exactSearch: string;
  semanticSearch: string;
  hybridSearch: string;
  ragTopK: string;
  ragContextBudget: string;
  sourceArtifacts: string;
  semanticScore: string;
  noMatches: string;
};

type MemoryKnowledgeSearchPanelProps = {
  copy: MemoryKnowledgeSearchPanelCopy;
  draft: MemoryKnowledgeSearchDraft;
  resultCount: number;
  results: KnowledgeSearchPayload["results"];
  searchPending: boolean;
  contexts: KnowledgeRagContext[];
  ragHealth: KnowledgeRagHealthPayload | undefined;
  ragProviderHealth: KnowledgeRagProviderHealth | undefined;
  retrievalPolicy: KnowledgeRagHealthPayload["retrievalPolicy"] | KnowledgeRagRetrievalPayload["retrievalPolicy"] | undefined;
  ragContextCount: number;
  ragCitationCount: number;
  ragPending: boolean;
  onDraftChange: (draft: MemoryKnowledgeSearchDraft) => void;
};

export function MemoryKnowledgeSearchPanel({
  copy,
  draft,
  resultCount,
  results,
  searchPending,
  contexts,
  ragHealth,
  ragProviderHealth,
  retrievalPolicy,
  ragContextCount,
  ragCitationCount,
  ragPending,
  onDraftChange,
}: MemoryKnowledgeSearchPanelProps) {
  return (
    <section className={styles.managementPanel}>
      <div className={styles.managementHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.knowledgeSearch}</p>
          <h2>{copy.governance}</h2>
        </div>
        <span className={styles.countPill}>{resultCount}</span>
      </div>
      <div className={styles.knowledgeFormGrid}>
        <label>
          <span>{copy.searchQuery}</span>
          <VNativeInput value={draft.query} onChange={(event) => onDraftChange({ ...draft, query: event.target.value })} />
        </label>
        <label>
          <span>{copy.tags}</span>
          <VNativeInput value={draft.tags} onChange={(event) => onDraftChange({ ...draft, tags: event.target.value })} />
        </label>
        <label>
          <span>{copy.searchMode}</span>
          <VNativeSelect
            value={draft.searchMode}
            onChange={(event) =>
              onDraftChange({
                ...draft,
                searchMode: event.target.value as MemoryKnowledgeSearchDraft["searchMode"],
              })
            }
          >
            <option value="exact">{copy.exactSearch}</option>
            <option value="semantic">{copy.semanticSearch}</option>
            <option value="hybrid">{copy.hybridSearch}</option>
          </VNativeSelect>
        </label>
        <label>
          <span>{copy.ragTopK}</span>
          <VNativeInput
            type="number"
            min={1}
            max={20}
            value={draft.ragTopK}
            onChange={(event) =>
              onDraftChange({
                ...draft,
                ragTopK: Math.min(20, Math.max(1, Number(event.target.value) || 5)),
              })
            }
          />
        </label>
        <label>
          <span>{copy.ragContextBudget}</span>
          <VNativeInput
            type="number"
            min={120}
            max={4000}
            value={draft.ragMaxContextChars}
            onChange={(event) =>
              onDraftChange({
                ...draft,
                ragMaxContextChars: Math.min(4000, Math.max(120, Number(event.target.value) || 1200)),
              })
            }
          />
        </label>
      </div>
      <div className={styles.knowledgeProposalList}>
        {results.map((item) => (
          <section key={`search:${item.knowledgeItemId}`} className={styles.knowledgeRow}>
            <strong>{item.title}</strong>
            <span>{item.summary || item.content}</span>
            <span className={styles.statusPill}>{item.importanceLevel}</span>
            <small>{item.teamName} · {item.knowledgeBaseName} · {item.sourceTypes.join(", ") || copy.sourceArtifacts}</small>
            <small>{copy.semanticScore}: {Math.round(Number(item.semanticScore || 0) * 100)}% · {item.matchReason}</small>
          </section>
        ))}
        {!searchPending && !results.length ? (
          <section className={styles.emptyDetail}>
            <Search size={20} />
            <strong>{copy.noMatches}</strong>
          </section>
        ) : null}
      </div>
      <MemoryKnowledgeRagPanel
        copy={copy}
        contexts={contexts}
        health={ragHealth}
        providerHealth={ragProviderHealth}
        retrievalPolicy={retrievalPolicy}
        contextCount={ragContextCount}
        citationCount={ragCitationCount}
        isPending={ragPending}
      />
    </section>
  );
}
