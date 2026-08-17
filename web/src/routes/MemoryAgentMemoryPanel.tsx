import { MemoryContentBrowsePanel } from "./MemoryContentBrowsePanel";
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
  content?: string;
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
  browseBack: string;
  memoryCount: string;
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
  searchText,
  onSearchTextChange,
  agents,
  selectedAgent,
  selectedItem,
  items,
  inventoryPending,
  inventoryErrorText,
  detailPending,
  detailErrorText,
  onSelectAgent,
  onSelectItem,
}: MemoryAgentMemoryPanelProps) {
  const selectedCardId = agents.find((agent) => agent.active)?.id ?? "";
  return (
    <div className={`${styles.workspace} ${styles.agentMemoryWorkspace}`} data-vui-region="memory-agent-workspace">
      <MemoryContentBrowsePanel
        copy={{
          loading: copy.loading,
          loadFailed: copy.loadFailed,
          browseBack: copy.browseBack,
          browseSelectCard: copy.agentMemorySelectPrompt,
          browseEmptyCards: copy.agentMemoryNoAgents,
          browseEmptyEntries: copy.agentMemoryNoPrivateMemory,
          noContent: copy.noContent,
          searchPlaceholder: copy.searchPlaceholder,
        }}
        searchText={searchText}
        onSearchTextChange={onSearchTextChange}
        cards={agents.map((agent) => ({
          id: agent.id,
          title: agent.name,
          meta: `${agent.privateFileCount} ${copy.memoryCount}`,
        }))}
        selectedCardId={selectedCardId}
        onSelectCard={onSelectAgent}
        onClearCard={() => onSelectAgent("")}
        entries={items.map((item) => ({
          id: item.id,
          title: item.title,
          body: item.content || (selectedItem && items.find((row) => row.active)?.id === item.id ? selectedItem.content : "") || item.summary,
        }))}
        selectedEntryId={items.find((item) => item.active)?.id ?? ""}
        onSelectEntry={onSelectItem}
        loading={inventoryPending}
        errorText={inventoryErrorText}
        entriesLoading={Boolean(selectedCardId) && detailPending && !items.length}
      />
      {detailErrorText ? <p className={styles.emptyState}>{copy.loadFailed}: {detailErrorText}</p> : null}
    </div>
  );
}
