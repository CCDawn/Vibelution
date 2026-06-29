import { CircleDot, Clock3, MessageCircleHeart, UsersRound } from "lucide-react";

import type { ConversationSummary, Team } from "../api/types";
import { VButton } from "../components/vui";
import type { ConversationIndexTeam } from "./conversationIndexModel";
import { conversationIndexTeamMemberCount } from "./conversationIndexModel";
import styles from "./ChatCodingRoute.module.css";

export function teamStatusLabel(status: string | undefined, lang: "zh" | "en", fallback: (status: string) => string) {
  const normalized = String(status ?? "").trim().toLowerCase();
  if (normalized === "active") {
    return lang === "zh" ? "启用中" : "Active";
  }
  if (normalized === "archived") {
    return lang === "zh" ? "已归档" : "Archived";
  }
  return fallback(normalized || String(status ?? ""));
}

export function teamMemberPreview(team: Pick<Team, "members" | "memberCount">, lang: "zh" | "en") {
  const memberCount = conversationIndexTeamMemberCount(team);
  if (!memberCount) {
    return lang === "zh" ? "0人" : "0";
  }
  return lang === "zh" ? `${memberCount}人` : String(memberCount);
}

export function teamMemberStatusTitle(team: Pick<Team, "members" | "memberCount">, lang: "zh" | "en") {
  const memberCount = conversationIndexTeamMemberCount(team);
  if (!memberCount) {
    return lang === "zh" ? "成员：0人 / 未配置成员" : "Members: 0 / not configured";
  }
  return lang === "zh" ? `成员：${teamMemberPreview(team, lang)}` : `Members: ${teamMemberPreview(team, lang)}`;
}

export function teamCategoryLabel(team: Pick<Team, "teamCategory" | "teamKind">, lang: "zh" | "en") {
  return team.teamCategory || team.teamKind || (lang === "zh" ? "自定义团队" : "Custom team");
}

type GroupConversationIndexItemProps = {
  active: boolean;
  conversation: ConversationSummary;
  kindLabel: string;
  fallbackSummary: string;
  lang: "zh" | "en";
  roomId: string;
  statusLabel: (status: string) => string;
  formatTime: (value: string) => string;
  onOpen: (roomId: string) => void;
};

export function GroupConversationIndexItem({
  active,
  conversation,
  kindLabel,
  fallbackSummary,
  lang,
  roomId,
  statusLabel,
  formatTime,
  onOpen,
}: GroupConversationIndexItemProps) {
  void fallbackSummary;
  const itemClassName = active
    ? `${styles.sessionItem} ${styles.groupSessionItem} ${styles.sessionItemActive}`
    : `${styles.sessionItem} ${styles.groupSessionItem}`;
  const groupStatus = statusLabel(conversation.status);
  const memberLabel = lang === "zh" ? `成员：${conversation.participantCount ?? 0}` : `Members: ${conversation.participantCount ?? 0}`;

  return (
    <div
      aria-current={active ? "true" : undefined}
      className={itemClassName}
    >
      <VButton
        type="button"
        className={styles.sessionItemMain}
        onPress={() => onOpen(roomId)}
      >
        <span className={`${styles.conversationAvatar} ${styles.conversationAvatarGroup}`} aria-hidden="true">
          <UsersRound size={18} />
        </span>
        <span className={styles.conversationCopy}>
          <span className={styles.conversationTitleRow}>
            <span className={styles.sessionItemTitle}>{conversation.title}</span>
            <span className={styles.sessionState} title={groupStatus} aria-label={groupStatus}>
              <CircleDot size={10} aria-hidden="true" />
            </span>
          </span>
          <span className={styles.conversationMetaRow}>
            <span className={`${styles.conversationKindBadge} ${styles.conversationKindBadgeGroup}`} title={kindLabel} aria-label={kindLabel}>
              <MessageCircleHeart size={10} aria-hidden="true" />
            </span>
            <span title={memberLabel} aria-label={memberLabel}>
              <UsersRound size={10} aria-hidden="true" />
              {conversation.participantCount ?? 0}
            </span>
            <Clock3 size={10} aria-hidden="true" />
            <time>{formatTime(conversation.updatedAt)}</time>
          </span>
        </span>
      </VButton>
    </div>
  );
}

type TeamConversationIndexItemProps = {
  active: boolean;
  lang: "zh" | "en";
  roomId: string;
  team: ConversationIndexTeam;
  teamRoute: string;
  statusLabel: (status: string) => string;
  onOpen: (roomId: string) => void;
};

export function TeamConversationIndexItem({
  active,
  lang,
  roomId,
  team,
  teamRoute,
  statusLabel,
  onOpen,
}: TeamConversationIndexItemProps) {
  void teamRoute;
  const itemClassName = active
    ? `${styles.sessionItem} ${styles.teamTreeItem} ${styles.sessionItemActive}`
    : `${styles.sessionItem} ${styles.teamTreeItem}`;
  const teamStatus = teamStatusLabel(team.status, lang, statusLabel);
  const roomTitle = roomId ? (lang === "zh" ? "团队群聊已同步" : "Team room linked") : (lang === "zh" ? "团队群聊待同步" : "Team room pending");
  const memberTitle = teamMemberStatusTitle(team, lang);
  const duplicateCount = Number(team.conversationIndexDuplicateCount) || 0;
  const duplicateTitle = lang === "zh"
    ? `已合并 ${duplicateCount} 个同名团队记录`
    : `${duplicateCount} same-name Team records merged`;

  return (
    <div
      aria-current={active ? "true" : undefined}
      className={itemClassName}
    >
      <VButton
        type="button"
        className={styles.sessionItemMain}
        isDisabled={!roomId}
        onPress={() => onOpen(roomId)}
      >
        <span className={`${styles.conversationAvatar} ${styles.conversationAvatarGroup}`} aria-hidden="true">
          <UsersRound size={18} />
        </span>
        <span className={styles.conversationCopy}>
          <span className={styles.conversationTitleRow}>
            <span className={styles.sessionItemTitle}>{team.name}</span>
            <span className={styles.sessionState} title={teamStatus} aria-label={teamStatus}>
              <CircleDot size={10} aria-hidden="true" />
            </span>
          </span>
          <span className={styles.conversationMetaRow}>
            <span className={`${styles.conversationKindBadge} ${styles.conversationKindBadgeGroup}`} title={lang === "zh" ? "团队" : "Team"} aria-label={lang === "zh" ? "团队" : "Team"}>
              <UsersRound size={10} aria-hidden="true" />
            </span>
            <span title={memberTitle} aria-label={memberTitle}>
              <UsersRound size={10} aria-hidden="true" />
              {teamMemberPreview(team, lang)}
            </span>
            <span title={roomTitle} aria-label={roomTitle}>
              <MessageCircleHeart size={10} aria-hidden="true" />
            </span>
            {duplicateCount > 1 ? (
              <span title={duplicateTitle} aria-label={duplicateTitle}>
                {lang === "zh" ? `合并${duplicateCount}` : `merged ${duplicateCount}`}
              </span>
            ) : null}
          </span>
        </span>
      </VButton>
    </div>
  );
}
