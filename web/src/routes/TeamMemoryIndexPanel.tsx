import { Bot, Eye, Link2 } from "lucide-react";
import { Link } from "react-router-dom";

import styles from "./TeamMemoryIndexPanel.styles";

type TeamMemoryIndexLang = "zh" | "en";

export type TeamMemoryIndexMember = {
  id: string;
  agentName: string;
  agentCode: string;
  roleLabel: string;
  roleTitle: string;
  statusLabel: string;
  statusTitle: string;
  statusTone: string;
  memoryRoute: string;
  configRoute: string;
};

type TeamMemoryIndexPanelProps = {
  lang: TeamMemoryIndexLang;
  members: TeamMemoryIndexMember[];
  knowledgeRoute: string;
  graphRoute: string;
};

export function TeamMemoryIndexPanel({
  lang,
  members,
  knowledgeRoute,
  graphRoute,
}: TeamMemoryIndexPanelProps) {
  const isZh = lang === "zh";

  return (
    <section className={styles.teamMemoryIndex} aria-label={isZh ? "团队记忆索引" : "Team memory index"}>
      <div className={styles.teamMemoryIndexHeader}>
        <div>
          <strong>{isZh ? "团队记忆索引" : "Team memory index"}</strong>
          <span>
            {members.length} {isZh ? "个成员" : "members"}
          </span>
        </div>
        <div className={styles.teamMemoryActionRail}>
          <Link to={knowledgeRoute} title={isZh ? "打开当前团队知识库" : "Open this team's knowledge bases"}>
            <Link2 size={13} />
            <span>{isZh ? "知识库" : "Knowledge"}</span>
          </Link>
          <Link to={graphRoute} title={isZh ? "打开团队记忆图谱" : "Open team memory graph"}>
            <Eye size={13} />
            <span>{isZh ? "图谱" : "Graph"}</span>
          </Link>
        </div>
      </div>
      <div className={styles.teamMemoryMemberTable}>
        {members.length ? (
          <div className={styles.teamMemoryMemberHeading}>
            <span>Agent</span>
            <span>{isZh ? "职责" : "Role"}</span>
            <span>{isZh ? "状态" : "Status"}</span>
            <span>{isZh ? "入口" : "Open"}</span>
          </div>
        ) : null}
        {members.map((member) => (
          <section
            key={member.id}
            className={styles.teamMemoryMemberCard}
            aria-label={`${member.agentName} · ${member.roleLabel} · ${member.statusLabel}`}
          >
            <div className={styles.teamMemoryMemberMain}>
              <div className={styles.teamMemoryMemberIdentity}>
                <strong>{member.agentName}</strong>
                <span>{member.agentCode}</span>
              </div>
              <div className={styles.teamMemoryMemberMeta}>
                <span className={styles.teamMemoryRole} title={member.roleTitle || undefined}>
                  {member.roleLabel}
                </span>
                <span className={styles.teamMemoryStatusBadge} data-tone={member.statusTone} title={member.statusTitle}>
                  {member.statusLabel}
                </span>
              </div>
            </div>
            <div className={styles.teamMemoryMemberActions}>
              <Link to={member.memoryRoute} title={isZh ? "打开该 Agent 私有记忆" : "Open this Agent's private memory"}>
                <Bot size={13} />
                <span>{isZh ? "记忆" : "Memory"}</span>
              </Link>
              <Link to={member.configRoute} title={isZh ? "打开该 Agent 记忆配置" : "Open this Agent's memory configuration"}>
                <Link2 size={13} />
                <span>{isZh ? "配置" : "Config"}</span>
              </Link>
            </div>
          </section>
        ))}
        {!members.length ? (
          <div className={styles.empty}>{isZh ? "当前团队还没有绑定成员 Agent。" : "No member Agents are bound to this team yet."}</div>
        ) : null}
      </div>
    </section>
  );
}
