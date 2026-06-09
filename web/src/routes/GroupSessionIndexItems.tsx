import { MessageCircleHeart, UsersRound } from "lucide-react";
import { Link } from "react-router-dom";

import type { ConversationSummary, Team } from "../api/types";
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
  return (team.members ?? [])
    .slice(0, 3)
    .map((member) => member.agentName || member.agentCode || member.agentId)
    .filter(Boolean)
    .join(", ") || (team.memberCount ? String(team.memberCount) : (lang === "zh" ? "待绑定" : "empty"));
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
  const itemClassName = active
    ? `${styles.sessionItem} ${styles.groupSessionItem} ${styles.sessionItemActive}`
    : `${styles.sessionItem} ${styles.groupSessionItem}`;

  return (
    <div
      aria-current={active ? "true" : undefined}
      className={itemClassName}
    >
      <button
        type="button"
        className={styles.sessionItemMain}
        onClick={() => onOpen(roomId)}
      >
        <span className={`${styles.conversationAvatar} ${styles.conversationAvatarGroup}`} aria-hidden="true">
          <UsersRound size={18} />
        </span>
        <span className={styles.conversationCopy}>
          <span className={styles.conversationTitleRow}>
            <span className={styles.sessionItemTitle}>{conversation.title}</span>
            <span className={styles.sessionState}>{statusLabel(conversation.status)}</span>
          </span>
          <span className={styles.sessionItemSummary} title={conversation.summary}>
            {conversation.summary || fallbackSummary}
          </span>
          <span className={styles.conversationMetaRow}>
            <span className={`${styles.conversationKindBadge} ${styles.conversationKindBadgeGroup}`}>
              {kindLabel}
            </span>
            <span>{lang === "zh" ? "成员" : "Members"} · {conversation.participantCount ?? 0}</span>
            <time>{formatTime(conversation.updatedAt)}</time>
          </span>
        </span>
      </button>
    </div>
  );
}

type TeamConversationIndexItemProps = {
  active: boolean;
  lang: "zh" | "en";
  roomId: string;
  team: Team;
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
  const itemClassName = active
    ? `${styles.sessionItem} ${styles.teamTreeItem} ${styles.sessionItemActive}`
    : `${styles.sessionItem} ${styles.teamTreeItem}`;
  const roomLabel = team.linkedChatRoom?.title || (roomId ? roomId : (lang === "zh" ? "未同步" : "not linked"));

  return (
    <div
      aria-current={active ? "true" : undefined}
      className={itemClassName}
    >
      <button
        type="button"
        className={styles.sessionItemMain}
        disabled={!roomId}
        onClick={() => onOpen(roomId)}
      >
        <span className={`${styles.conversationAvatar} ${styles.conversationAvatarGroup}`} aria-hidden="true">
          <UsersRound size={18} />
        </span>
        <span className={styles.conversationCopy}>
          <span className={styles.conversationTitleRow}>
            <span className={styles.sessionItemTitle}>{team.name}</span>
            <span className={styles.sessionState}>{teamStatusLabel(team.status, lang, statusLabel)}</span>
          </span>
          <span className={styles.sessionItemSummary} title={team.purpose || team.linkedChatRoom?.title || team.teamId}>
            {team.purpose || team.linkedChatRoom?.title || (lang === "zh" ? "团队通讯与成员协作" : "Team communication and members")}
          </span>
          <span className={styles.conversationMetaRow}>
            <span className={`${styles.conversationKindBadge} ${styles.conversationKindBadgeGroup}`}>
              {lang === "zh" ? "团队" : "Team"}
            </span>
            <span>{lang === "zh" ? "群" : "Room"} · {roomLabel}</span>
            <span>{lang === "zh" ? "成员" : "Members"} · {team.memberCount}</span>
          </span>
        </span>
      </button>
      <div className={styles.teamTreeLabelRow}>
        <span>{lang === "zh" ? "团队分类" : "Team category"}</span>
        <strong>{teamCategoryLabel(team, lang)}</strong>
        <Link to={teamRoute}>{lang === "zh" ? "打开团队" : "Open team"}</Link>
      </div>
      <div className={styles.teamTreeChildren}>
        <button
          type="button"
          className={styles.teamTreeChild}
          disabled={!roomId}
          onClick={() => onOpen(roomId)}
        >
          <MessageCircleHeart size={13} />
          <span>{lang === "zh" ? "团队群聊" : "Team room"}</span>
          <strong>{team.linkedChatRoom?.status || (roomId ? "ready" : (lang === "zh" ? "待同步" : "sync"))}</strong>
        </button>
        <Link className={styles.teamTreeChild} to={teamRoute}>
          <UsersRound size={13} />
          <span>{lang === "zh" ? "群成员" : "Members"}</span>
          <strong>{teamMemberPreview(team, lang)}</strong>
        </Link>
      </div>
    </div>
  );
}
