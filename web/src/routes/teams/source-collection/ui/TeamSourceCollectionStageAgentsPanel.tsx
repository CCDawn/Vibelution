import { useNavigate } from "react-router-dom";

import {
  VDenseTable,
  VEmptyState,
  VRouteLinkButton,
  VStatusChip,
  type VDenseTableColumn,
  type VStatusTone,
} from "../../../../components/vui";

import styles from "./TeamSourceCollectionStageAgentsPanel.styles";

type TeamSourceCollectionStageAgentsLang = "zh" | "en";
export type TeamSourceCollectionStageAgentTone = "ready" | "warning" | "blocked" | "missing";

export type TeamSourceCollectionStageAgentCard = {
  id: string;
  tone: TeamSourceCollectionStageAgentTone;
  roleLabel: string;
  agentName: string;
  modelLabel: string;
  statusLabel: string;
  memoryRoute: string;
  configRoute: string;
  configLabel: string;
};

function statusTone(tone: TeamSourceCollectionStageAgentTone): VStatusTone {
  if (tone === "blocked") return "danger";
  if (tone === "warning" || tone === "missing") return "warning";
  return "neutral";
}

type TeamSourceCollectionStageAgentsPanelProps = {
  lang: TeamSourceCollectionStageAgentsLang;
  agents: TeamSourceCollectionStageAgentCard[];
  layout?: "inline" | "stacked";
};

export function TeamSourceCollectionStageAgentsPanel({
  lang,
  agents,
  layout = "inline",
}: TeamSourceCollectionStageAgentsPanelProps) {
  const navigate = useNavigate();
  const isZh = lang === "zh";
  if (!agents.length) {
    return (
      <section
        className={styles.sourceCollectionStageAgentPanel}
        aria-label={isZh ? "当前步骤 Agent 配置" : "Current step Agent configuration"}
        data-layout={layout}
      >
        <div className={styles.sourceCollectionStageAgentHeader}>
          <strong>{isZh ? "Agent 配置" : "Agent configuration"}</strong>
        </div>
        <VEmptyState
          align="start"
          title={isZh ? "尚未绑定 Agent" : "No agents bound"}
          actions={(
            <VRouteLinkButton chrome="shell-nav" to="/agents">
              {isZh ? "前往 Agent 中心绑定" : "Bind an Agent in Agent Center"}
            </VRouteLinkButton>
          )}
        >
          {isZh
            ? "当前步骤没有可用的 Agent，绑定后才能运行。"
            : "No agent is available for this step yet; bind one before running."}
        </VEmptyState>
      </section>
    );
  }
  const columns: Array<VDenseTableColumn<TeamSourceCollectionStageAgentCard>> = [
    {
      id: "role",
      header: isZh ? "职责" : "Role",
      className: styles.sourceCollectionStageAgentRole,
      render: (agent) => <span title={agent.roleLabel}>{agent.roleLabel}</span>,
    },
    {
      id: "model",
      header: isZh ? "模型" : "Model",
      className: styles.sourceCollectionStageAgentModel,
      render: (agent) => (
        <div className={styles.sourceCollectionStageAgentModelContent}>
          <span
            className={styles.sourceCollectionStageAgentModelValue}
            title={agent.modelLabel || undefined}
          >
            {agent.modelLabel || "—"}
          </span>
          <VRouteLinkButton
            aria-label={`${agent.configLabel}：${agent.roleLabel}`}
            chrome="shell-nav"
            className={styles.sourceCollectionStageAgentConfigLink}
            to={agent.configRoute}
            onClick={(event) => event.stopPropagation()}
          >
            {agent.configLabel}
          </VRouteLinkButton>
        </div>
      ),
    },
    {
      id: "status",
      header: isZh ? "状态" : "Status",
      className: styles.sourceCollectionStageAgentStatus,
      truncate: false,
      render: (agent) => (
        <VStatusChip tone={statusTone(agent.tone)}>{agent.statusLabel}</VStatusChip>
      ),
    },
  ];

  return (
    <section
      className={styles.sourceCollectionStageAgentPanel}
      aria-label={isZh ? "当前步骤 Agent 配置" : "Current step Agent configuration"}
      data-layout={layout}
    >
      <div className={styles.sourceCollectionStageAgentHeader}>
        <strong>{isZh ? "Agent 配置" : "Agent configuration"}</strong>
      </div>
      <VDenseTable
        ariaLabel={isZh ? "Agent 职责、模型与状态" : "Agent role, model and status"}
        className={styles.sourceCollectionStageAgentTable}
        columns={columns}
        getRowKey={(agent) => agent.id}
        getRowState={(agent) => ({
          tone: agent.tone === "ready" ? "neutral" : "warning",
        })}
        onRowClick={(agent) => navigate(agent.configRoute)}
        rows={agents}
      />
    </section>
  );
}
