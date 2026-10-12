import { VStatusChip, VTabs, VTooltip } from "../components/vui";
import styles from "./MemoryKnowledgeModeTabs.styles";

export type MemoryKnowledgeWorkspaceMode = "sources" | "search" | "review" | "governance" | "permissions";

/** Agent-scoped semantic-index health snapshot powering the search tab badge. */
export type MemoryKnowledgeSemanticIndexHealth = {
  status: string;
  indexedItemCount?: number;
  indexableItemCount?: number;
};

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
  semanticIndex: string;
  semanticIndexReady: string;
  semanticIndexDegraded: string;
  semanticIndexUnknown: string;
  semanticIndexUnavailable: string;
  semanticIndexIndexed: string;
  semanticIndexTotal: string;
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
  /** Undefined (query pending/disabled) renders no badge — never a fake "unavailable". */
  semanticIndexHealth?: MemoryKnowledgeSemanticIndexHealth;
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
  semanticIndexHealth,
  onModeChange,
}: MemoryKnowledgeModeTabsProps) {
  const modes = [
    {
      key: "sources" as const,
      label: lang === "zh" ? "来源" : "Sources",
      hint: `${copy.ownerSourceInbox} / ${copy.centralSources}`,
      count: sourceCount + centralSourceCount,
    },
    {
      key: "search" as const,
      label: lang === "zh" ? "检索" : "Search",
      hint: `${copy.knowledgeSearch} / ${copy.ragRetrieval}`,
      count: searchResultCount + ragContextCount,
    },
    {
      key: "review" as const,
      label: lang === "zh" ? "审核" : "Review",
      hint: `${copy.pendingProposals} / ${copy.ratingSuggestions}`,
      count: pendingProposalCount + ratingSuggestionCount,
    },
    {
      key: "governance" as const,
      label: lang === "zh" ? "治理" : "Governance",
      hint: `${copy.operationsHealth} / ${copy.governanceTasks}`,
      count: operationsFindingCount + openGovernanceTaskCount,
    },
    {
      key: "permissions" as const,
      label: lang === "zh" ? "权限" : "Permissions",
      hint: `${copy.permissionAudit} / ${copy.ingestionAdapters}`,
      count: permissionKnowledgeBaseCount + ingestionAdapterCount,
    },
  ];

  // Same mapping as MemoryKnowledgeRagPanel: ready=success, unavailable=danger, else warning.
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
  const semanticIndexTooltip = semanticIndexHealth
    ? [
      `${copy.semanticIndex}: ${semanticIndexStatusLabel}`,
      `${copy.semanticIndexIndexed}: ${semanticIndexHealth.indexedItemCount ?? 0} / ${copy.semanticIndexTotal}: ${semanticIndexHealth.indexableItemCount ?? 0}`,
    ].join("\n")
    : "";
  const semanticIndexBadge = semanticIndexHealth ? (
    <VTooltip content={semanticIndexTooltip} width="wide">
      <VStatusChip tone={semanticIndexTone}>{semanticIndexStatusLabel}</VStatusChip>
    </VTooltip>
  ) : null;

  return (
    <VTabs
      aria-label={copy.governance}
      value={activeMode}
      onValueChange={(value) => {
        if (
          value === "sources"
          || value === "search"
          || value === "review"
          || value === "governance"
          || value === "permissions"
        ) {
          onModeChange(value);
        }
      }}
      className="min-w-0 max-w-full"
      listClassName={styles.knowledgeModeTabs}
      triggerClassName={styles.knowledgeModeTab}
      items={modes.map((mode) => ({
        id: mode.key,
        title: mode.hint,
        label: (
          <>
            <span>{mode.label}</span>
            <strong>{mode.count}</strong>
            {mode.key === "search" ? semanticIndexBadge : null}
          </>
        ),
      }))}
    />
  );
}
