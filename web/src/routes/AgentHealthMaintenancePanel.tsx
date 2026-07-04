import { AlertTriangle, CheckCircle2, MessageSquare } from "lucide-react";

import { VButton } from "../components/vui";
import styles from "./AgentHealthMaintenancePanel.styles";

export type AgentHealthMaintenanceIssueView = {
  key: string;
  severity: string;
  title: string;
  detail: string;
  showInboxAction: boolean;
};

export type AgentHealthMaintenancePanelCopy = {
  handleInboxNow: string;
  maintenanceHint: string;
  maintenanceTitle: string;
  noIssues: string;
};

type AgentHealthMaintenancePanelProps = {
  copy: AgentHealthMaintenancePanelCopy;
  health: {
    title: string;
    label: string;
    headline: string;
    hasIssues: boolean;
    issues: AgentHealthMaintenanceIssueView[];
  };
  onOpenActivity: () => void;
};

function issueItemToneClass(severity: string) {
  const toneKey = `issueItem_${severity}` as keyof typeof styles;
  return styles[toneKey] || "";
}

export function AgentHealthMaintenancePanel({
  copy,
  health,
  onOpenActivity,
}: AgentHealthMaintenancePanelProps) {
  return (
    <>
      <section className={styles.detailSection} title={health.title}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{health.label}</p>
            <h3>{health.headline}</h3>
          </div>
          {health.hasIssues ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
        </div>
        {health.hasIssues ? (
          <div className={styles.issueList}>
            {health.issues.map((issue) => (
              <article key={issue.key} className={`${styles.issueItem} ${issueItemToneClass(issue.severity)}`}>
                <strong>{issue.title}</strong>
                <p>{issue.detail}</p>
                {issue.showInboxAction ? (
                  <VButton
                    type="button"
                    variant="secondary"
                    icon={<MessageSquare size={15} />}
                    onPress={onOpenActivity}
                  >
                    {copy.handleInboxNow}
                  </VButton>
                ) : null}
              </article>
            ))}
          </div>
        ) : (
          <p className={styles.emptyText}>{copy.noIssues}</p>
        )}
      </section>

      <section className={styles.maintenanceIntro} title={copy.maintenanceHint}>
        <div>
          <p className={styles.panelEyebrow}>{copy.maintenanceTitle}</p>
          <h3>{copy.maintenanceTitle}</h3>
        </div>
      </section>
    </>
  );
}
