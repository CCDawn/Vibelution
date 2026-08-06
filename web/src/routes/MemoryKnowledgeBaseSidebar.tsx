import { Database } from "lucide-react";

import { VButton, VStateSurface, VStatusChip, VTooltip } from "../components/vui";
import styles from "./MemoryKnowledgeBaseSidebar.styles";

export type MemoryKnowledgeBaseSidebarCopy = {
  teamKnowledge: string;
  knowledgeBases: string;
  toolVisibility: string;
  knowledgeHint: string;
  yes: string;
  missing: string;
  loading: string;
  noKnowledgeBases: string;
};

export type MemoryKnowledgeBaseSidebarItem = {
  requestId: string;
  name: string;
  teamLabel: string;
  itemCount: number;
  pendingProposalCount: number;
};

export type MemoryKnowledgePermissionTool = {
  toolName: string;
  visible: boolean;
  reason: string;
};

type MemoryKnowledgeBaseSidebarProps = {
  copy: MemoryKnowledgeBaseSidebarCopy;
  bases: MemoryKnowledgeBaseSidebarItem[];
  permissionTools: MemoryKnowledgePermissionTool[];
  activeBaseRequestId: string;
  isLoading: boolean;
  onSelectBase: (requestId: string) => void;
};

export function MemoryKnowledgeBaseSidebar({
  copy,
  bases,
  permissionTools,
  activeBaseRequestId,
  isLoading,
  onSelectBase,
}: MemoryKnowledgeBaseSidebarProps) {
  const visibleTools = permissionTools.filter((tool) => tool.visible);
  const hiddenTools = permissionTools.filter((tool) => !tool.visible);
  const toolVisibilityTooltip = [
    copy.knowledgeHint,
    `${copy.yes}: ${visibleTools.map((tool) => tool.toolName).join(", ") || "-"}`,
    `${copy.missing}: ${hiddenTools.map((tool) => `${tool.toolName}: ${tool.reason}`).join("\n") || "-"}`,
  ].join("\n");

  return (
    <aside className={styles.sourcePanel}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.teamKnowledge}</p>
          <h2>{copy.knowledgeBases}</h2>
        </div>
        <span className={styles.countPill}>{bases.length}</span>
      </div>
      <VTooltip content={toolVisibilityTooltip} width="wide">
        <section className={styles.governanceMiniPanel} tabIndex={0} aria-label={`${copy.toolVisibility}说明`}>
          <strong>{copy.toolVisibility}</strong>
          <VStatusChip tone="success">
            {copy.yes}: {visibleTools.length}
          </VStatusChip>
          <VStatusChip tone={hiddenTools.length ? "warning" : "success"}>
            {copy.missing}: {hiddenTools.length}
          </VStatusChip>
        </section>
      </VTooltip>
      {isLoading ? <VStateSurface tone="loading" title={copy.loading} skeletonLines={2} /> : null}
      {!isLoading && !bases.length ? (
        <VStateSurface tone="empty" title={copy.noKnowledgeBases} icon={<Database size={18} />} />
      ) : null}
      <nav className={styles.sourceList} aria-label={copy.knowledgeBases}>
        {bases.map((base) => (
          <VButton
            key={base.requestId}
            type="button"
                contentLayout="plain"
            className={base.requestId === activeBaseRequestId ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
            onClick={() => onSelectBase(base.requestId)}
          >
            <span className={styles.sourceIcon}>
              <Database size={15} />
            </span>
            <span className={styles.sourceCopy}>
              <strong>{base.name}</strong>
              <span>{base.teamLabel}</span>
            </span>
            <span className={styles.sourceStats}>{base.itemCount}/{base.pendingProposalCount}</span>
          </VButton>
        ))}
      </nav>
    </aside>
  );
}
