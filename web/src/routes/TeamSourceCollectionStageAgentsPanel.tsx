import { Link2 } from "lucide-react";
import { Link } from "react-router-dom";

import styles from "./TeamsRoute.styles";

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

type TeamSourceCollectionStageAgentsPanelProps = {
  lang: TeamSourceCollectionStageAgentsLang;
  agents: TeamSourceCollectionStageAgentCard[];
};

export function TeamSourceCollectionStageAgentsPanel({
  lang,
  agents,
}: TeamSourceCollectionStageAgentsPanelProps) {
  if (!agents.length) {
    return null;
  }
  const isZh = lang === "zh";

  return (
    <section className={styles.sourceCollectionStageAgentPanel} aria-label={isZh ? "当前步骤 Agent 配置" : "Current step Agent configuration"}>
      <div className={styles.sourceCollectionStageAgentHeader}>
        <div>
          <strong>{isZh ? "当前步骤 Agent 配置" : "Step Agent configuration"}</strong>
          <span>
            {agents.length} {isZh ? "个功能 Agent" : "functional Agents"}
          </span>
        </div>
        <Link to="/agents">
          <Link2 size={12} />
          {isZh ? "Agent 管理" : "Agent management"}
        </Link>
      </div>
      <div className={styles.sourceCollectionStageAgentList}>
        {agents.map((agent) => (
          <article
            key={agent.id}
            className={[
              styles.sourceCollectionStageAgentCard,
              styles[`researchStageAgentCard_${agent.tone}` as keyof typeof styles],
            ].filter(Boolean).join(" ")}
          >
            <div className={styles.sourceCollectionStageAgentCardBody}>
              <span>
                <small>{isZh ? "职责" : "Role"}</small>
                <strong>{agent.roleLabel}</strong>
              </span>
              <span>
                <small>Agent</small>
                <strong>{agent.agentName}</strong>
              </span>
              <span>
                <small>{isZh ? "模型" : "Model"}</small>
                <strong>{agent.modelLabel}</strong>
              </span>
            </div>
            <div className={styles.sourceCollectionStageAgentCardActions}>
              <span>{agent.statusLabel}</span>
              {agent.memoryRoute ? (
                <Link to={agent.memoryRoute}>
                  <Link2 size={12} />
                  {isZh ? "Agent 记忆" : "Memory"}
                </Link>
              ) : null}
              <Link to={agent.configRoute}>
                <Link2 size={12} />
                {agent.configLabel}
              </Link>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
