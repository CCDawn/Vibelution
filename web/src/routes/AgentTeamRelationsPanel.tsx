import { ExternalLink, Users } from "lucide-react";

import { VButton, VEmptyState, VPanel } from "../components/vui";
import styles from "./AgentTeamRelationsPanel.styles";

export type AgentTeamRelationView = {
  teamId: string;
  name: string;
  purpose: string;
  members: Array<{
    agentId: string;
    label: string;
    functionLabel: string;
    current: boolean;
  }>;
};

type AgentTeamRelationsPanelProps = {
  relations: AgentTeamRelationView[];
  onOpenTeam: (teamId: string) => void;
};

export function AgentTeamRelationsPanel({ relations, onOpenTeam }: AgentTeamRelationsPanelProps) {
  return (
    <VPanel ariaLabel="团队关系" className={styles.relationsPanel}>
      <header className={styles.panelHeader}>
        <div>
          <h3>团队关系</h3>
          <p>确认当前 Agent 所属团队和同组成员；成员资格由团队工作区维护。</p>
        </div>
      </header>
      <p className={styles.evidenceNote}>成员关系来自团队画布。委派、审批和运行依赖请在对应团队或运行视图中核验。</p>
      {relations.length ? (
        <div className={styles.relationList}>
          {relations.map((relation) => (
            <section key={relation.teamId} className={styles.relationItem} aria-label={relation.name}>
              <div className={styles.relationCopy}>
                <h4>{relation.name}</h4>
                <p>{relation.purpose || "未填写团队目标"}</p>
                <ul className={styles.memberList} aria-label={`${relation.name} 成员`}>
                  {relation.members.map((member) => (
                    <li
                      key={member.agentId}
                      className={`${styles.member} ${member.current ? styles.memberCurrent : ""}`}
                    >
                      <strong>{member.label}</strong>
                      <small>{member.functionLabel}</small>
                    </li>
                  ))}
                </ul>
              </div>
              <VButton
                type="button"
                variant="secondary"
                className={styles.openTeam}
                icon={<ExternalLink size={14} />}
                onPress={() => onOpenTeam(relation.teamId)}
              >
                打开团队
              </VButton>
            </section>
          ))}
        </div>
      ) : (
        <VEmptyState title="该 Agent 未加入可见团队" icon={<Users size={16} />}>
          可在 Teams 页面查看或维护成员关系。
        </VEmptyState>
      )}
    </VPanel>
  );
}
