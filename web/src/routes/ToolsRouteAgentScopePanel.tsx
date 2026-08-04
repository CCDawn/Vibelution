import type { AgentInstance } from "../api/types";
import { VStringSelect } from "../components/vui";
import styles from "./ToolsRouteAgentScopePanel.styles";

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
    <section className={styles.agentScopeBar}>
        <div className={styles.scopeCopy}>
          <p className={styles.panelEyebrow}>{copy.configureAgent}</p>
          <strong>{agentDisplayName(activeAgent)}</strong>
          <span>{dirty ? copy.unsaved : copy.synced}</span>
        </div>
        <label className={styles.scopeSelect}>
          <span>{copy.configure}</span>
          <VStringSelect
            ariaLabel={copy.configureAgent}
            value={activeAgent?.agentId ?? ""}
            isDisabled={!activeAgents.length}
            onValueChange={onAgentChange}
            options={
              !activeAgents.length
                ? [{ value: "", label: agentsLoading ? copy.loading : "-" }]
                : activeAgents.map((agent) => ({
                    value: agent.agentId,
                    label: `${agent.agentCode ? `${agent.agentCode} · ` : ""}${agent.displayName || agent.agentId}`,
                  }))
            }
          />
        </label>
        <label className={styles.scopeSelect}>
          <span>{copy.scope}</span>
          <VStringSelect
            ariaLabel={copy.scope}
            value={activeAgentScopeId}
            onValueChange={onScopeChange}
            options={scopeOptions.map((scope) => ({
              value: scope.id,
              label: scope.label,
            }))}
          />
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
  );
}
