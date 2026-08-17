import { Brain, Database, FileText, Search } from "lucide-react";
import type { ReactNode } from "react";

import { WORKBENCH_LAYOUT_IDS } from "../components/layout/workbenchLayoutIds";
import { VButton, VLoadingValue, VMetricStrip, VNativeInput, VSplitWorkspace, VStateSurface, VStatusChip } from "../components/vui";
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
  agentMemorySelectPrompt: string;
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

/** Pane ids under WORKBENCH_LAYOUT_IDS.memory — separate from sources left/right. */
const AGENT_MEMORY_SPLIT_RESIZE = {
  layoutId: WORKBENCH_LAYOUT_IDS.memory,
  sidebar: {
    id: "agent-list",
    defaultWidth: 235,
    minWidth: 210,
    maxWidth: 300,
  },
  aside: {
    id: "agent-detail",
    defaultWidth: 320,
    minWidth: 260,
    maxWidth: 420,
  },
} as const;

function metricValue(pending: boolean, loadingLabel: string, value: ReactNode): ReactNode {
  return pending ? <VLoadingValue label={loadingLabel} /> : value;
}

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
  const filesLoading = inventoryPending || (Boolean(selectedAgent) && detailPending && !items.length);
  const emptyAsideHint = inventoryPending
    ? copy.loading
    : agents.length
      ? copy.agentMemorySelectPrompt
      : copy.agentMemoryNoAgents;

  return (
    <>
      <div className={styles.summaryGrid}>
        <VMetricStrip
          ariaLabel={copy.agentMemoryAgents}
          metrics={[
            { id: "agents", label: copy.agentMemoryAgents, value: metricValue(inventoryPending, copy.loading, summary.agentCount) },
            { id: "files", label: copy.agentMemoryPrivateFiles, value: metricValue(inventoryPending, copy.loading, summary.privateFileCount), detail: summary.privateByteText },
            { id: "knowledge", label: copy.agentMemoryFormalKnowledge, value: metricValue(inventoryPending, copy.loading, summary.formalKnowledgeItemCount), detail: `${copy.agentMemoryFormalBases}: ${summary.formalKnowledgeBaseCount}` },
            { id: "warnings", label: copy.warnings, value: metricValue(inventoryPending, copy.loading, summary.warningCount) },
          ]}
        />
      </div>

      <VSplitWorkspace
        className={`${styles.workspace} ${styles.agentMemoryWorkspace}`}
        data-vui-region="memory-agent-workspace"
        data-vui-layout-id={WORKBENCH_LAYOUT_IDS.memory}
        resize={AGENT_MEMORY_SPLIT_RESIZE}
        sidebar={(
          <div className={styles.sourcePanel} data-vui-region="memory-agent-list">
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{copy.agentMemoryAgents}</p>
                <h2>{copy.agentMemorySelectedAgent}</h2>
              </div>
              <span className={styles.countPill}>{inventoryPending ? "…" : agents.length}</span>
            </div>
            <label className={styles.searchBox}>
              <Search size={15} />
              <VNativeInput value={searchText} placeholder={copy.searchPlaceholder} onChange={(event) => onSearchTextChange(event.target.value)} aria-label={copy.searchPlaceholder} />
            </label>
            <div className={styles.itemList}>
              {inventoryPending ? <VStateSurface tone="loading" title={copy.loading} skeletonLines={2} /> : null}
              {inventoryErrorText ? (
                <VStateSurface tone="error" title={copy.loadFailed}>
                  {inventoryErrorText}
                </VStateSurface>
              ) : null}
              {!inventoryPending && !agents.length ? <VStateSurface tone="empty" title={copy.agentMemoryNoAgents} /> : null}
              {agents.map((agent) => (
                <VButton
                  key={agent.id}
                  type="button"
                  contentLayout="plain"
                  className={agent.active ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
                  onClick={() => onSelectAgent(agent.id)}
                >
                  <span className={styles.itemHeader}>
                    <strong>{agent.name}</strong>
                    <span>{agent.status}</span>
                  </span>
                  <span className={styles.itemOrigin}>{agent.origin}</span>
                  <span className={styles.itemPath} title={agent.path}>{agent.path}</span>
                  <span className={styles.itemBadges}>
                    <VStatusChip tone={agent.hasPrivateMemory ? "success" : "neutral"}>
                      {copy.agentMemoryPrivateFiles}: {agent.privateFileCount}
                    </VStatusChip>
                    <VStatusChip tone="neutral">
                      {copy.agentMemoryFormalBases}: {agent.formalKnowledgeBaseCount}
                    </VStatusChip>
                  </span>
                </VButton>
              ))}
            </div>
          </div>
        )}
        main={(
          <div className={styles.itemPanel} data-vui-region="memory-agent-files">
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
              <span title={selectedAgent?.privateRoot || ""}>{copy.agentMemoryPrivateRoot}: {selectedAgent?.privateRoot || "-"}</span>
              <span title={selectedAgent?.workspacePath || ""}>{copy.sourcePath}: {selectedAgent?.workspacePath || "-"}</span>
              <span>{copy.agentMemoryFormalKnowledge}: {selectedAgent?.formalKnowledgeItemCount ?? 0}</span>
            </section>
            <div className={styles.itemList}>
              {filesLoading ? <VStateSurface tone="loading" title={copy.loading} skeletonLines={2} /> : null}
              {detailErrorText ? (
                <VStateSurface tone="error" title={copy.loadFailed}>
                  {detailErrorText}
                </VStateSurface>
              ) : null}
              {!filesLoading && !items.length ? (
                <VStateSurface tone="empty" title={selectedAgent ? copy.agentMemoryNoPrivateMemory : copy.agentMemorySelectPrompt} />
              ) : null}
              {items.map((item) => (
                <VButton
                  key={item.id}
                  type="button"
                  contentLayout="plain"
                  className={item.active ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
                  onClick={() => onSelectItem(item.id)}
                >
                  <span className={styles.itemHeader}>
                    <strong>{item.title}</strong>
                    <span>{item.updatedAtText}</span>
                  </span>
                  <span className={styles.itemPath} title={item.path}>{item.path}</span>
                  <span className={styles.itemSummary}>{item.summary}</span>
                  <span className={styles.itemBadges}>
                    <VStatusChip tone="neutral">{item.sizeText}</VStatusChip>
                    <VStatusChip tone="neutral">{item.contentType}</VStatusChip>
                    {item.truncated ? <VStatusChip tone="neutral">{copy.truncated}</VStatusChip> : null}
                  </span>
                </VButton>
              ))}
            </div>
          </div>
        )}
        aside={(
          <div className={styles.detailPanel} data-vui-region="memory-agent-detail">
            {selectedAgent ? (
              <>
                <div className={styles.detailHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.agentMemorySelectedFile}</p>
                    <h2 title={selectedItem?.title}>{selectedItem?.title ?? copy.agentMemoryNoFileSelected}</h2>
                    <p title={selectedItem?.path || selectedAgent.privateRoot || ""}>{selectedItem?.path || selectedAgent.privateRoot || "-"}</p>
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
                <p>{emptyAsideHint}</p>
              </section>
            )}
          </div>
        )}
      />
    </>
  );
}
