import { AlertTriangle, CheckCircle2, MessageSquare } from "lucide-react";

import { VButton, VContextualHint } from "../components/vui";
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
      <section className={styles.detailSection}>
        <div className={styles.panelHeader}>
          <div>
            <p className={styles.panelEyebrow}>{health.label}</p>
            <h3 className="inline-flex items-center gap-1.5">
              {health.headline}
              <VContextualHint content={health.title} label={`${health.label}说明`} />
            </h3>
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

      <section className={styles.maintenanceIntro}>
        <div>
          <p className={styles.panelEyebrow}>{copy.maintenanceTitle}</p>
          <h3 className="inline-flex items-center gap-1.5">
            {copy.maintenanceTitle}
            <VContextualHint content={copy.maintenanceHint} label={`${copy.maintenanceTitle}说明`} />
          </h3>
        </div>
      </section>
    </>
  );
}
