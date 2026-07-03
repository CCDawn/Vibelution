import { VButton } from "../components/vui";
import styles from "./MemoryRoute.styles";

export type MemoryKnowledgeWorkspaceMode = "sources" | "search" | "review" | "governance" | "permissions";

export type MemoryKnowledgeModeTabsCopy = {
  governance: string;
  ownerSourceInbox: string;
  centralSources: string;
  knowledgeSearch: string;
  ragRetrieval: string;
  pendingProposals: string;
  ratingSuggestions: string;
  operationsHealth: string;
  governanceTasks: string;
  permissionAudit: string;
  ingestionAdapters: string;
};

type MemoryKnowledgeModeTabsProps = {
  copy: MemoryKnowledgeModeTabsCopy;
  lang: "zh" | "en";
  activeMode: MemoryKnowledgeWorkspaceMode;
  sourceCount: number;
  centralSourceCount: number;
  searchResultCount: number;
  ragContextCount: number;
  pendingProposalCount: number;
  ratingSuggestionCount: number;
  operationsFindingCount: number;
  openGovernanceTaskCount: number;
  permissionKnowledgeBaseCount: number;
  ingestionAdapterCount: number;
  onModeChange: (mode: MemoryKnowledgeWorkspaceMode) => void;
};

export function MemoryKnowledgeModeTabs({
  copy,
  lang,
  activeMode,
  sourceCount,
  centralSourceCount,
  searchResultCount,
  ragContextCount,
  pendingProposalCount,
  ratingSuggestionCount,
  operationsFindingCount,
  openGovernanceTaskCount,
  permissionKnowledgeBaseCount,
  ingestionAdapterCount,
  onModeChange,
}: MemoryKnowledgeModeTabsProps) {
  const modes = [
    {
      key: "sources",
      label: lang === "zh" ? "来源" : "Sources",
      hint: `${copy.ownerSourceInbox} / ${copy.centralSources}`,
      count: sourceCount + centralSourceCount,
    },
    {
      key: "search",
      label: lang === "zh" ? "检索" : "Search",
      hint: `${copy.knowledgeSearch} / ${copy.ragRetrieval}`,
      count: searchResultCount + ragContextCount,
    },
    {
      key: "review",
      label: lang === "zh" ? "审核" : "Review",
      hint: `${copy.pendingProposals} / ${copy.ratingSuggestions}`,
      count: pendingProposalCount + ratingSuggestionCount,
    },
    {
      key: "governance",
      label: lang === "zh" ? "治理" : "Governance",
      hint: `${copy.operationsHealth} / ${copy.governanceTasks}`,
      count: operationsFindingCount + openGovernanceTaskCount,
    },
    {
      key: "permissions",
      label: lang === "zh" ? "权限" : "Permissions",
      hint: `${copy.permissionAudit} / ${copy.ingestionAdapters}`,
      count: permissionKnowledgeBaseCount + ingestionAdapterCount,
    },
  ] satisfies Array<{ key: MemoryKnowledgeWorkspaceMode; label: string; hint: string; count: number }>;

  return (
    <div className={styles.knowledgeModeTabs} role="tablist" aria-label={copy.governance}>
      {modes.map((mode) => (
        <VButton
          key={mode.key}
          type="button"
          role="tab"
          aria-selected={activeMode === mode.key}
          className={activeMode === mode.key ? styles.knowledgeModeTabActive : styles.knowledgeModeTab}
          title={mode.hint}
          onClick={() => onModeChange(mode.key)}
        >
          <span>{mode.label}</span>
          <strong>{mode.count}</strong>
        </VButton>
      ))}
    </div>
  );
}
