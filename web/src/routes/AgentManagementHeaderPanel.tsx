import { RefreshCw } from "lucide-react";

import {
  AgentPageHeader,
  AgentSummaryStrip,
  type AgentSummaryMetric,
} from "../components/vui/product/agent-management";
import { AgentManagementNav } from "./AgentManagementNav";
import styles from "./AgentManagementHeaderPanel.styles";

type AgentManagementHeaderPanelCopy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  refresh: string;
  workspaceSummary: string;
  workspaceHealthStatus: string;
};

type AgentManagementHeaderPanelProps = {
  copy: AgentManagementHeaderPanelCopy;
  healthStatus: string;
  healthStatusLabel: string;
  healthStatusDescription: string;
  metrics: AgentSummaryMetric[];
  onRefresh: () => void;
};

function healthTone(status: string): "danger" | "warning" | "success" {
  if (status === "blocked") {
    return "danger";
  }
  if (status === "warning") {
    return "warning";
  }
  return "success";
}

export function AgentManagementHeaderPanel({
  copy,
  healthStatus,
  healthStatusLabel,
  healthStatusDescription,
  metrics,
  onRefresh,
}: AgentManagementHeaderPanelProps) {
  return (
    <>
      <AgentPageHeader
        eyebrow={copy.eyebrow}
        title={copy.title}
        tooltip={copy.subtitle}
        tooltipLabel={`${copy.title} · ${copy.subtitle}`}
        actions={[
          {
            id: "refresh",
            label: copy.refresh,
            tooltip: copy.refresh,
            icon: <RefreshCw size={14} />,
            onPress: onRefresh,
          },
        ]}
      />

      <div className={styles.controlStrip}>
        <AgentManagementNav active="agents" className={styles.managementNav} />

        <AgentSummaryStrip
          ariaLabel={copy.workspaceSummary}
          status={{
            label: healthStatusLabel,
            title: healthStatusDescription,
            ariaLabel: `${copy.workspaceHealthStatus}: ${healthStatusLabel}. ${healthStatusDescription}`,
            tone: healthTone(healthStatus),
          }}
          metrics={metrics}
        />
      </div>
    </>
  );
}
