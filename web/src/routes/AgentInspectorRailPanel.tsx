import { X } from "lucide-react";
import { type ComponentProps, type ReactNode } from "react";

import { AgentWorkspacePanel } from "../components/vui/product/agent-management";
import { VIconButton, VStateSurface } from "../components/vui";
import { AgentManagementBriefPanel } from "./AgentManagementBriefPanel";
import { AgentOverviewResourcesPanel } from "./AgentOverviewResourcesPanel";
import styles from "./AgentInspectorRailPanel.styles";

export type AgentInspectorRailPanelProps = {
  ariaLabel: string;
  title: string;
  subtitle?: string;
  emptyTitle: string;
  emptyHint: string;
  closeLabel?: string;
  brief: ComponentProps<typeof AgentManagementBriefPanel> | null;
  resources: ComponentProps<typeof AgentOverviewResourcesPanel> | null;
  /** Extra blocks for config/activity panes (optional). */
  extra?: ReactNode;
  onClose?: () => void;
};

export function AgentInspectorRailPanel({
  ariaLabel,
  title,
  subtitle,
  emptyTitle,
  emptyHint,
  closeLabel,
  brief,
  resources,
  extra,
  onClose,
}: AgentInspectorRailPanelProps) {
  const hasContent = Boolean(brief || resources || extra);

  return (
    <AgentWorkspacePanel
      as="aside"
      ariaLabel={ariaLabel}
      className={styles.rail}
    >
      <header className={styles.railHeader}>
        <div>
          <p>{title}</p>
          {subtitle ? <strong>{subtitle}</strong> : null}
        </div>
        {onClose ? (
          <VIconButton
            type="button"
            className={styles.closeButton}
            label={closeLabel || title}
            icon={<X size={15} />}
            onPress={onClose}
          />
        ) : null}
      </header>
      <div className={styles.railBody}>
        {hasContent ? (
          <>
            {brief ? <AgentManagementBriefPanel {...brief} /> : null}
            {resources ? <AgentOverviewResourcesPanel {...resources} /> : null}
            {extra}
          </>
        ) : (
          <VStateSurface
            fill
            className={styles.emptyRail}
            tone="empty"
            title={emptyTitle}
            aria-label={emptyTitle}
          >
            {emptyHint}
          </VStateSurface>
        )}
      </div>
    </AgentWorkspacePanel>
  );
}
