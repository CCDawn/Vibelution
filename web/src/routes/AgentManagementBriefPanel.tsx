import { AlertTriangle, CheckCircle2 } from "lucide-react";

import { VNativeButton } from "../components/vui";
import styles from "./AgentsRoute.styles";

export type AgentManagementBriefPanelPane = "overview" | "config" | "activity";

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
  return (
    <section className={styles.managementBriefPanel} title={copy.managementBriefHint}>
      <div className={styles.managementBriefHeader}>
        <div>
          <p className={styles.panelEyebrow}>{copy.managementBriefTitle}</p>
          <h3>{brief.statusLabel}</h3>
          <span>{brief.statusDetail}</span>
        </div>
        <strong>{brief.score}</strong>
      </div>
      <div className={styles.managementChecklist}>
        {brief.items.map((item) => (
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
            <VNativeButton
              key={action.id}
              type="button"
              className="w-full"
              title={action.detail}
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
          ))
        ) : (
          <p>{copy.nextAllReady}</p>
        )}
      </div>
    </section>
  );
}
