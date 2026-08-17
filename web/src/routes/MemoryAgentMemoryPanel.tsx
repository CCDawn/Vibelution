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
  primaryMode: string;
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
  searchAgents: string;
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
  groupHasMemory: string;
  groupNoMemory: string;
  groupChat: string;
  groupResearch: string;
  groupSelfEvolution: string;
  groupSupervised: string;
  groupGeneral: string;
  groupOther: string;
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

function agentModeLabel(mode: string, copy: MemoryAgentMemoryPanelCopy): string {
  if (mode === "chat") {
    return copy.groupChat;
  }
  if (mode === "research") {
    return copy.groupResearch;
  }
  if (mode === "self_evolution") {
    return copy.groupSelfEvolution;
  }
  if (mode === "supervised_evolution") {
    return copy.groupSupervised;
  }
  if (mode === "general") {
    return copy.groupGeneral;
  }
  return mode.trim() ? copy.groupOther : copy.groupGeneral;
}

function memoryFolderGroup(path: string, title: string): string {
  const parts = (path || title || "").replace(/\\/g, "/").split("/").filter(Boolean);
  if (parts.length < 2) {
    return "";
  }
  const folder = parts[parts.length - 2];
  return folder.includes(":") ? "" : folder;
}

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
          searchPlaceholder: copy.searchAgents,
          ungrouped: copy.groupOther,
        }}
        searchText={searchText}
        onSearchTextChange={onSearchTextChange}
        cards={[...agents]
          .sort((left, right) => Number(right.hasPrivateMemory) - Number(left.hasPrivateMemory))
          .map((agent) => ({
            id: agent.id,
            title: agent.name,
            group: agent.hasPrivateMemory ? copy.groupHasMemory : copy.groupNoMemory,
            meta: `${agentModeLabel(agent.primaryMode, copy)} · ${agent.privateFileCount} ${copy.memoryCount}`,
          }))}
        selectedCardId={selectedCardId}
        onSelectCard={onSelectAgent}
        onClearCard={() => onSelectAgent("")}
        entries={items.map((item) => ({
          id: item.id,
          title: item.title,
          group: memoryFolderGroup(item.path, item.title),
          body: item.content || (selectedItem && items.find((row) => row.active)?.id === item.id ? selectedItem.content : "") || item.summary,
        }))}
        selectedEntryId={items.find((item) => item.active)?.id ?? ""}
        onSelectEntry={onSelectItem}
        loading={inventoryPending && !agents.length}
        errorText={inventoryErrorText}
        entriesLoading={Boolean(selectedCardId) && detailPending && !items.length}
      />
      {detailErrorText ? <p className={styles.emptyState}>{copy.loadFailed}: {detailErrorText}</p> : null}
    </div>
  );
}
