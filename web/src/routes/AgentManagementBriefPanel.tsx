import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { VContextualHint, VNativeButton, VTooltip } from "../components/vui";
import styles from "./AgentManagementBriefPanel.styles";

export type AgentManagementBriefPanelPane = "overview" | "effective" | "relations" | "config" | "changes" | "activity";

export type AgentManagementBriefPanelData = {
  score: number;
  statusLabel: string;
  statusDetail: string;
  items: Array<{
    id: string;
    label: string;
    complete: boolean;
    pane: AgentManagementBriefPanelPane;
  }>;
  actions: Array<{
    id: string;
    label: string;
    detail: string;
    pane: AgentManagementBriefPanelPane;
    route?: string;
  }>;
};

export type AgentManagementBriefPanelCopy = {
  managementBriefHint: string;
  managementBriefTitle: string;
  nextActionsTitle: string;
  nextAllReady: string;
};

export type AgentManagementBriefPanelProps = {
  brief: AgentManagementBriefPanelData;
  copy: AgentManagementBriefPanelCopy;
  onOpenRoute: (route: string) => void;
  onSelectPane: (pane: AgentManagementBriefPanelPane) => void;
};

export function AgentManagementBriefPanel({ brief, copy, onOpenRoute, onSelectPane }: AgentManagementBriefPanelProps) {
  const incomplete = brief.items.filter((item) => !item.complete);
  const allReady = incomplete.length === 0 && brief.actions.length === 0;
  const checklistItems = allReady ? brief.items : incomplete.length ? incomplete : brief.items;

  if (allReady) {
    return (
      <section className={styles.managementBriefPanelCompact} aria-label={copy.managementBriefTitle}>
        <div className={styles.managementBriefHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.managementBriefTitle}</p>
            <h3 className={styles.contextualHintRow}>
              {brief.statusLabel}
              <VContextualHint content={copy.managementBriefHint} label={`${copy.managementBriefTitle}说明`} />
            </h3>
            <span>{copy.nextAllReady}</span>
          </div>
          <strong>{brief.score}</strong>
        </div>
      </section>
    );
  }

  return (
    <section className={styles.managementBriefPanel}>
      <div className={styles.managementBriefHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.managementBriefTitle}</p>
          <h3 className={styles.contextualHintRow}>
            {brief.statusLabel}
            <VContextualHint content={copy.managementBriefHint} label={`${copy.managementBriefTitle}说明`} />
          </h3>
          <span>{brief.statusDetail}</span>
        </div>
        <strong>{brief.score}</strong>
      </div>
      <div className={styles.managementChecklist}>
        {checklistItems.map((item) => (
          <VNativeButton
            key={item.id}
            type="button"
            className={item.complete ? styles.managementChecklistDone : styles.managementChecklistMissing}
            onClick={() => onSelectPane(item.pane)}
          >
            {item.complete ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            <span>{item.label}</span>
          </VNativeButton>
        ))}
      </div>
      <div className={styles.nextActionList}>
        <span>{copy.nextActionsTitle}</span>
        {brief.actions.length ? (
          brief.actions.map((action) => (
            <VTooltip key={action.id} content={action.detail} width="wide">
              <VNativeButton
                type="button"
                className={styles.nextActionButton}
                onClick={() => {
                  if (action.route) {
                    onOpenRoute(action.route);
                    return;
                  }
                  onSelectPane(action.pane);
                }}
              >
                <strong>{action.label}</strong>
              </VNativeButton>
            </VTooltip>
          ))
        ) : (
          <p>{copy.nextAllReady}</p>
        )}
      </div>
    </section>
  );
}
