import type { ReactNode } from "react";
import type { AgentInstance, ChatRoomDetail, Team, TeamMember } from "../../api/types";
import { VButton } from "../../components/vui";
import { agentDisplayInfo } from "../agentDisplay";
import styles from "./TeamConversationRail.styles";

export function teamMemberDisplay(member: TeamMember, agentsById: ReadonlyMap<string, Partial<AgentInstance>> | undefined, lang: "zh" | "en") {
  const info = agentDisplayInfo(agentsById?.get(member.agentId), lang, { name: member.agentName || undefined, templateId: member.role });
  return { name: info.name === member.agentId ? info.functionLabel : info.name, role: member.role.includes("_") ? info.functionLabel : member.role };
}

export function teamMemberSessionId(member: TeamMember, room: ChatRoomDetail | null) {
  return String(room?.participants?.find((participant) => participant.kind !== "user" && participant.agentId === member.agentId)?.sessionId || "").trim();
}

export function TeamConversationRail({ team, room, lang, selectedMemberId, groupSelected, onOpenGroup, onOpenMember, navigation, agentsById }: {
  team: Team; room: ChatRoomDetail | null; lang: "zh" | "en"; selectedMemberId: string; groupSelected: boolean;
  onOpenGroup: () => void; onOpenMember: (member: TeamMember, sessionId: string) => void; navigation?: ReactNode;
  agentsById?: ReadonlyMap<string, Partial<AgentInstance>>;
}) {
  const entries = [{ id: "group", title: team.name, subtitle: lang === "zh" ? `团队讨论 · ${team.members.length} 位成员` : `Team discussion · ${team.members.length} members`, avatar: lang === "zh" ? "团" : "T", selected: groupSelected, disabled: false, onClick: onOpenGroup },
    ...team.members.map((member) => { const sessionId = teamMemberSessionId(member, room); const display = teamMemberDisplay(member, agentsById, lang); return {
      id: member.memberId, title: display.name, subtitle: display.role,
      avatar: display.name.slice(0, 1), selected: selectedMemberId === member.memberId,
      disabled: !sessionId || member.agentStatus === "stale", onClick: () => onOpenMember(member, sessionId),
    }; })];
  return <nav aria-label={lang === "zh" ? "团队与成员对话" : "Team and member conversations"} className={styles.root}>
    <div className={styles.entries}><p className={styles.heading}>{lang === "zh" ? "团队与成员" : "Team and members"}</p>
      {entries.map((entry) => <VButton key={entry.id} variant="ghost" aria-label={entry.title + (lang === "zh" ? entry.id === "group" ? " · 团队讨论" : " · 成员对话" : entry.id === "group" ? " · Team discussion" : " · Member conversation")} aria-pressed={entry.selected}
        isDisabled={entry.disabled} disabledReason={entry.disabled ? lang === "zh" ? "成员会话尚不可用，请先同步群聊或检查成员配置" : "Sync the room or check the member configuration first" : undefined}
        className={styles.entry} onClick={entry.onClick}>
        <span className={styles.identity}><span className={styles.avatar}>{entry.avatar}</span><span className={styles.copy}><span className={styles.name}>{entry.title}</span><span className={styles.role}>{entry.subtitle}</span></span></span>
      </VButton>)}
    </div>
    {navigation ? <div className={styles.navigation}>{navigation}</div> : null}
  </nav>;
}
