import { Brain, Database, FileText, Search } from "lucide-react";

import { VButton, VNativeInput } from "../components/vui";
import styles from "./MemoryAgentMemoryPanel.styles";

export type MemoryAgentMemorySummaryView = {
  agentCount: number;
  privateFileCount: number;
  privateByteText: string;
  formalKnowledgeItemCount: number;
  formalKnowledgeBaseCount: number;
  warningCount: number;
};

export type MemoryAgentMemoryAgentView = {
  id: string;
  name: string;
  status: string;
  origin: string;
  path: string;
  privateFileCount: number;
  formalKnowledgeBaseCount: number;
  hasPrivateMemory: boolean;
  active: boolean;
};

export type MemoryAgentMemoryItemView = {
  id: string;
  title: string;
  updatedAtText: string;
  path: string;
  summary: string;
  sizeText: string;
  contentType: string;
  truncated: boolean;
  active: boolean;
};

export type MemoryAgentMemoryKnowledgeBaseView = {
  id: string;
  label: string;
  title: string;
};

export type MemoryAgentMemorySelectedAgentView = {
  name: string;
  privateRoot: string;
  workspacePath: string;
  fileCount: number;
  formalKnowledgeItemCount: number;
  formalKnowledgeBaseCount: number;
  knowledgeError?: string;
  knowledgeBases: MemoryAgentMemoryKnowledgeBaseView[];
};

export type MemoryAgentMemorySelectedItemView = {
  title: string;
  path: string;
  sizeText: string;
  contentType: string;
  contentLanguage: string;
  content: string;
};

export type MemoryAgentMemoryPanelCopy = {
  agentMemoryAgents: string;
  agentMemoryPrivateFiles: string;
  agentMemoryFormalKnowledge: string;
  agentMemoryFormalBases: string;
  warnings: string;
  agentMemorySelectedAgent: string;
  searchPlaceholder: string;
  loading: string;
  loadFailed: string;
  agentMemoryNoAgents: string;
  agentMemoryPrivateRoot: string;
  sourcePath: string;
  agentMemoryNoPrivateMemory: string;
  truncated: string;
  agentMemorySelectedFile: string;
  agentMemoryNoFileSelected: string;
  noMatches: string;
  rawContent: string;
  noContent: string;
  generatedAt: string;
};

type MemoryAgentMemoryPanelProps = {
  copy: MemoryAgentMemoryPanelCopy;
  summary: MemoryAgentMemorySummaryView;
  searchText: string;
  onSearchTextChange: (value: string) => void;
  agents: MemoryAgentMemoryAgentView[];
  selectedAgent: MemoryAgentMemorySelectedAgentView | null;
  selectedItem: MemoryAgentMemorySelectedItemView | null;
  items: MemoryAgentMemoryItemView[];
  inventoryPending: boolean;
  inventoryErrorText: string;
  detailPending: boolean;
  detailFetching: boolean;
  detailErrorText: string;
  generatedAtText: string;
  onSelectAgent: (agentId: string) => void;
  onSelectItem: (itemId: string) => void;
};

export function MemoryAgentMemoryPanel({
  copy,
  summary,
  searchText,
  onSearchTextChange,
  agents,
  selectedAgent,
  selectedItem,
  items,
  inventoryPending,
  inventoryErrorText,
  detailPending,
  detailFetching,
  detailErrorText,
  generatedAtText,
  onSelectAgent,
  onSelectItem,
}: MemoryAgentMemoryPanelProps) {
  return (
    <>
      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.agentMemoryAgents}</span>
          <strong>{summary.agentCount}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.agentMemoryPrivateFiles}</span>
          <strong>{summary.privateFileCount}</strong>
          <small>{summary.privateByteText}</small>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.agentMemoryFormalKnowledge}</span>
          <strong>{summary.formalKnowledgeItemCount}</strong>
          <small>{copy.agentMemoryFormalBases}: {summary.formalKnowledgeBaseCount}</small>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.warnings}</span>
          <strong>{summary.warningCount}</strong>
        </section>
      </div>

      <div className={`${styles.workspace} ${styles.agentMemoryWorkspace}`}>
        <aside className={styles.sourcePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.agentMemoryAgents}</p>
              <h2>{copy.agentMemorySelectedAgent}</h2>
            </div>
            <span className={styles.countPill}>{agents.length}</span>
          </div>
          <label className={styles.searchBox}>
            <Search size={15} />
            <VNativeInput value={searchText} placeholder={copy.searchPlaceholder} onChange={(event) => onSearchTextChange(event.target.value)} />
          </label>
          <div className={styles.itemList}>
            {inventoryPending ? <div className={styles.emptyState}>{copy.loading}</div> : null}
            {inventoryErrorText ? <div className={styles.emptyState}>{copy.loadFailed}: {inventoryErrorText}</div> : null}
            {!inventoryPending && !agents.length ? <div className={styles.emptyState}>{copy.agentMemoryNoAgents}</div> : null}
            {agents.map((agent) => (
              <VButton
                key={agent.id}
                type="button"
                className={agent.active ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
                onClick={() => onSelectAgent(agent.id)}
              >
                <span className={styles.itemHeader}>
                  <strong>{agent.name}</strong>
                  <span>{agent.status}</span>
                </span>
                <span className={styles.itemOrigin}>{agent.origin}</span>
                <span className={styles.itemPath}>{agent.path}</span>
                <span className={styles.itemBadges}>
                  <span className={agent.hasPrivateMemory ? styles.statusPillVisible : styles.statusPill}>
                    {copy.agentMemoryPrivateFiles}: {agent.privateFileCount}
                  </span>
                  <span className={styles.statusPill}>
                    {copy.agentMemoryFormalBases}: {agent.formalKnowledgeBaseCount}
                  </span>
                </span>
              </VButton>
            ))}
          </div>
        </aside>

        <main className={styles.itemPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.agentMemoryPrivateRoot}</p>
              <h2 title={selectedAgent?.privateRoot || selectedAgent?.workspacePath || ""}>
                {selectedAgent?.name ?? copy.agentMemorySelectedAgent}
              </h2>
            </div>
            <span className={styles.countPill}>{selectedAgent?.fileCount ?? 0}</span>
          </div>
          <section className={styles.detailMeta}>
            <span>{copy.agentMemoryPrivateRoot}: {selectedAgent?.privateRoot || "-"}</span>
            <span>{copy.sourcePath}: {selectedAgent?.workspacePath || "-"}</span>
            <span>{copy.agentMemoryFormalKnowledge}: {selectedAgent?.formalKnowledgeItemCount ?? 0}</span>
          </section>
          <div className={styles.itemList}>
            {detailPending && selectedAgent ? <div className={styles.emptyState}>{copy.loading}</div> : null}
            {detailErrorText ? <div className={styles.emptyState}>{copy.loadFailed}: {detailErrorText}</div> : null}
            {!items.length && !detailPending ? <div className={styles.emptyState}>{copy.agentMemoryNoPrivateMemory}</div> : null}
            {items.map((item) => (
              <VButton
                key={item.id}
                type="button"
                className={item.active ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
                onClick={() => onSelectItem(item.id)}
              >
                <span className={styles.itemHeader}>
                  <strong>{item.title}</strong>
                  <span>{item.updatedAtText}</span>
                </span>
                <span className={styles.itemPath}>{item.path}</span>
                <span className={styles.itemSummary}>{item.summary}</span>
                <span className={styles.itemBadges}>
                  <span className={styles.statusPill}>{item.sizeText}</span>
                  <span className={styles.statusPill}>{item.contentType}</span>
                  {item.truncated ? <span className={styles.statusPill}>{copy.truncated}</span> : null}
                </span>
              </VButton>
            ))}
          </div>
        </main>

        <aside className={styles.detailPanel}>
          {selectedAgent ? (
            <>
              <div className={styles.detailHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{copy.agentMemorySelectedFile}</p>
                  <h2>{selectedItem?.title ?? copy.agentMemoryNoFileSelected}</h2>
                  <p>{selectedItem?.path || selectedAgent.privateRoot || "-"}</p>
                </div>
                {selectedItem ? <span className={styles.countPill}>{selectedItem.sizeText}</span> : null}
              </div>
              <section className={styles.sectionPanel}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.agentMemoryFormalKnowledge}</p>
                    <h3>{copy.agentMemoryFormalBases}</h3>
                  </div>
                  <span className={styles.countPill}>{selectedAgent.formalKnowledgeBaseCount}</span>
                </div>
                {selectedAgent.knowledgeError ? <p>{selectedAgent.knowledgeError}</p> : null}
                {selectedAgent.knowledgeBases.length ? (
                  <div className={styles.usageList}>
                    {selectedAgent.knowledgeBases.map((base) => (
                      <span key={base.id} title={base.title}>
                        <Database size={13} />
                        {base.label}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p>{copy.noMatches}</p>
                )}
              </section>
              <details className={styles.rawPanel} open>
                <summary>
                  <FileText size={15} />
                  <span>{copy.rawContent}</span>
                  <code>{selectedItem?.contentType ?? "-"}</code>
                </summary>
                {detailFetching ? <p>{copy.loading}</p> : null}
                {selectedItem?.content ? (
                  <pre data-language={selectedItem.contentLanguage}>{selectedItem.content}</pre>
                ) : !detailFetching ? (
                  <p>{selectedItem ? copy.noContent : copy.agentMemoryNoFileSelected}</p>
                ) : null}
              </details>
              <p className={styles.generatedAt}>{copy.generatedAt}: {generatedAtText}</p>
            </>
          ) : (
            <section className={styles.emptyDetail}>
              <Brain size={24} />
              <strong>{copy.agentMemorySelectedAgent}</strong>
              <p>{inventoryPending ? copy.loading : copy.agentMemoryNoAgents}</p>
            </section>
          )}
        </aside>
      </div>
    </>
  );
}
