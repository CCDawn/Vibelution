import type { AgentInstance } from "../api/types";
import { VNativeSelect } from "../components/vui";
import { AgentManagementNav } from "./AgentManagementNav";
import styles from "./ToolsRouteAgentScopePanel.styles";

export type ToolsRouteSummaryMetric = {
  id: string;
  label: string;
  value: number;
};

export type ToolsRouteScopeOption = {
  id: string;
  label: string;
};

type ToolsRouteAgentScopeCopy = {
  blocked: string;
  callable: string;
  configure: string;
  configureAgent: string;
  loading: string;
  scope: string;
  synced: string;
  unsaved: string;
  visible: string;
};

type ToolsRouteAgentScopePanelProps = {
  copy: ToolsRouteAgentScopeCopy;
  summaryMetrics: ToolsRouteSummaryMetric[];
  activeAgents: AgentInstance[];
  activeAgent?: AgentInstance | null;
  agentsLoading: boolean;
  activeAgentScopeId: string;
  scopeOptions: ToolsRouteScopeOption[];
  scopeCounts: {
    visible: number;
    callable: number;
    blocked: number;
  };
  dirty: boolean;
  deepLinkNotice: string;
  onAgentChange: (agentId: string) => void;
  onScopeChange: (scopeId: string) => void;
};

function agentDisplayName(agent: AgentInstance | null | undefined) {
  if (!agent) {
    return "-";
  }
  return `${agent.agentCode || ""} ${agent.displayName || agent.agentId}`.trim();
}

export function ToolsRouteAgentScopePanel({
  copy,
  summaryMetrics,
  activeAgents,
  activeAgent,
  agentsLoading,
  activeAgentScopeId,
  scopeOptions,
  scopeCounts,
  dirty,
  deepLinkNotice,
  onAgentChange,
  onScopeChange,
}: ToolsRouteAgentScopePanelProps) {
  return (
    <>
      <div className={styles.controlStrip}>
        <AgentManagementNav active="tools" className={styles.managementNav} />

        <div className={styles.summaryGrid}>
          {summaryMetrics.map((metric) => (
            <section key={metric.id} className={styles.summaryCard}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
            </section>
          ))}
        </div>
      </div>

      <section className={styles.agentScopeBar}>
        <div className={styles.scopeCopy}>
          <p className={styles.panelEyebrow}>{copy.configureAgent}</p>
          <strong>{agentDisplayName(activeAgent)}</strong>
          <span>{dirty ? copy.unsaved : copy.synced}</span>
        </div>
        <label className={styles.scopeSelect}>
          <span>{copy.configure}</span>
          <VNativeSelect
            value={activeAgent?.agentId ?? ""}
            disabled={!activeAgents.length}
            aria-label={copy.configureAgent}
            onChange={(event) => onAgentChange(event.target.value)}
          >
            {!activeAgents.length ? (
              <option value="">{agentsLoading ? copy.loading : "-"}</option>
            ) : null}
            {activeAgents.map((agent) => (
              <option key={agent.agentId} value={agent.agentId}>
                {agent.agentCode ? `${agent.agentCode} · ` : ""}{agent.displayName || agent.agentId}
              </option>
            ))}
          </VNativeSelect>
        </label>
        <label className={styles.scopeSelect}>
          <span>{copy.scope}</span>
          <VNativeSelect
            value={activeAgentScopeId}
            aria-label={copy.scope}
            onChange={(event) => onScopeChange(event.target.value)}
          >
            {scopeOptions.map((scope) => (
              <option key={scope.id} value={scope.id}>
                {scope.label}
              </option>
            ))}
          </VNativeSelect>
        </label>
        <div className={styles.scopeStats}>
          <span>
            {copy.visible}: <strong>{scopeCounts.visible}</strong>
          </span>
          <span>
            {copy.callable}: <strong>{scopeCounts.callable}</strong>
          </span>
          <span>
            {copy.blocked}: <strong>{scopeCounts.blocked}</strong>
          </span>
        </div>
        {deepLinkNotice ? <p className={styles.deepLinkNotice}>{deepLinkNotice}</p> : null}
      </section>
    </>
  );
}
