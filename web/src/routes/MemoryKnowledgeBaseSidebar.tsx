import { Database } from "lucide-react";

import { VButton } from "../components/vui";
import styles from "./MemoryRoute.styles";

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

  return (
    <aside className={styles.sourcePanel}>
      <div className={styles.panelHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.teamKnowledge}</p>
          <h2>{copy.knowledgeBases}</h2>
        </div>
        <span className={styles.countPill}>{bases.length}</span>
      </div>
      <section className={styles.governanceMiniPanel} aria-label={copy.toolVisibility} title={copy.knowledgeHint}>
        <strong>{copy.toolVisibility}</strong>
        <span className={styles.statusPill} title={visibleTools.map((tool) => tool.toolName).join("\n")}>
          {copy.yes}: {visibleTools.length}
        </span>
        <span
          className={hiddenTools.length ? styles.statusPillMuted : styles.statusPill}
          title={hiddenTools.map((tool) => `${tool.toolName}: ${tool.reason}`).join("\n")}
        >
          {copy.missing}: {hiddenTools.length}
        </span>
      </section>
      {isLoading ? <div className={styles.emptyState}>{copy.loading}</div> : null}
      {!isLoading && !bases.length ? (
        <section className={styles.emptyDetail}>
          <Database size={22} />
          <strong>{copy.noKnowledgeBases}</strong>
        </section>
      ) : null}
      <nav className={styles.sourceList} aria-label={copy.knowledgeBases}>
        {bases.map((base) => (
          <VButton
            key={base.requestId}
            type="button"
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
