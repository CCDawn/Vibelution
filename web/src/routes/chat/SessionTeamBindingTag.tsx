import type { MouseEvent } from "react";

import type { SessionSummary, Team, TeamMember } from "../../api/types";
import { VRouteLinkButton, VTooltip } from "../../components/vui";
import {
  buildConversationTeamLookup,
  conversationTeamFor,
  sessionToConversationSummary,
  type ConversationIndexTeam,
} from "../conversationIndexModel";
import { teamWorkspaceRoute } from "../teams/researchWorkspaceModel";
import styles from "./SessionTeamBindingTag.styles";

export type SessionTeamBinding = {
  teamId: string;
  teamName: string;
  purpose?: string;
};

export function sessionTeamBindingAriaLabel(binding: SessionTeamBinding, lang: "zh" | "en"): string {
  const teamTitle = binding.teamName || binding.teamId;
  if (!binding.teamId) {
    return lang === "zh" ? `已绑定团队：${teamTitle}` : `Bound team: ${teamTitle}`;
  }
  return lang === "zh" ? `打开团队：${teamTitle}` : `Open team: ${teamTitle}`;
}

function isActiveTeamStatus(status: string | undefined) {
  const normalized = String(status || "active").trim().toLowerCase();
  return !normalized || normalized === "active";
}

function teamsForBindingLookup(teams: ConversationIndexTeam[] | Team[]): ConversationIndexTeam[] {
  return (teams as ConversationIndexTeam[])
    .filter((team) => isActiveTeamStatus(team.status))
    .map((team) => ({
      ...team,
      members: (team.members ?? []).filter((member: TeamMember) => isActiveTeamStatus(member.agentStatus)),
    }));
}

export function resolveSessionTeamBinding(
  session: SessionSummary,
  teams: ConversationIndexTeam[] | Team[] = [],
): SessionTeamBinding | undefined {
  const sessionKind = String(session.conversationIndexKind || "").trim();
  if (sessionKind === "user_chat" && !session.agentId) {
    return undefined;
  }
  if (teams.length) {
    const lookup = buildConversationTeamLookup(teamsForBindingLookup(teams));
    const team = conversationTeamFor(sessionToConversationSummary(session), lookup);
    if (team) {
      return {
        teamId: String(team.teamId || "").trim(),
        teamName: String(team.name || "").trim() || String(team.teamId || "").trim(),
        purpose: String(team.purpose || "").trim() || undefined,
      };
    }
  }
  const teamId = String(session.teamId || "").trim();
  const teamName = String(session.teamName || "").trim();
  if (teamId || teamName) {
    return { teamId, teamName: teamName || teamId };
  }
  const experimentTeamId = String(session.experimentBinding?.teamId || "").trim();
  if (experimentTeamId) {
    return {
      teamId: experimentTeamId,
      teamName: String(session.experimentBinding?.experimentName || experimentTeamId).trim(),
    };
  }
  return undefined;
}

export function SessionTeamBindingTag({
  session,
  lang,
  teams,
}: {
  session: SessionSummary;
  lang: "zh" | "en";
  teams?: ConversationIndexTeam[] | Team[];
}) {
  const binding = resolveSessionTeamBinding(session, teams ?? []);
  if (!binding) {
    return null;
  }
  const label = lang === "zh" ? "团队" : "Team";
  const teamTitle = binding.teamName || binding.teamId;
  const tooltip = [teamTitle, binding.purpose].filter(Boolean).join("\n");
  const ariaLabel = sessionTeamBindingAriaLabel(binding, lang);
  const handleActivate = (event: MouseEvent) => {
    event.stopPropagation();
  };

  if (!binding.teamId) {
    return (
      <VTooltip content={tooltip}>
        <span className={styles.tag} tabIndex={0} aria-label={ariaLabel} data-session-team-binding="static">
          {label}
        </span>
      </VTooltip>
    );
  }

  return (
    <VTooltip content={tooltip}>
      <VRouteLinkButton
        to={teamWorkspaceRoute(binding.teamId)}
        chrome="shell-nav"
        className={styles.tag}
        aria-label={ariaLabel}
        data-session-team-binding="link"
        onClick={handleActivate}
      >
        {label}
      </VRouteLinkButton>
    </VTooltip>
  );
}
