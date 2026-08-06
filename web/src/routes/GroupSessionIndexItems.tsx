import { UsersRound } from "lucide-react";

import type { ConversationSummary, Team } from "../api/types";
import { VNativeButton, VStatusChip, VTooltip, type VStatusTone } from "../components/vui";
import type { ConversationIndexTeam } from "./conversationIndexModel";
import { conversationIndexTeamMemberCount } from "./conversationIndexModel";
import styles from "./GroupSessionIndexItems.styles";

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

function statusKindTone(kind: "active" | "pending" | "muted"): VStatusTone {
  if (kind === "active") return "success";
  if (kind === "pending") return "warning";
  return "neutral";
}

export function teamMemberPreview(team: Pick<Team, "members" | "memberCount">, lang: "zh" | "en") {
  const memberCount = conversationIndexTeamMemberCount(team);
  if (lang === "zh") {
    return `${memberCount} 人`;
  }
  return String(memberCount);
}

export function teamMemberStatusTitle(team: Pick<Team, "members" | "memberCount">, lang: "zh" | "en") {
  const memberCount = conversationIndexTeamMemberCount(team);
  if (!memberCount) {
    return lang === "zh" ? "成员：0 人 / 未配置成员" : "Members: 0 / not configured";
  }
  return lang === "zh" ? `成员：${teamMemberPreview(team, lang)}` : `Members: ${teamMemberPreview(team, lang)}`;
}

export function teamCategoryLabel(team: Pick<Team, "teamCategory" | "teamKind">, lang: "zh" | "en") {
  return team.teamCategory || team.teamKind || (lang === "zh" ? "自定义团队" : "Custom team");
}

function indexItemTooltip(title: string, details: string[]) {
  return (
    <span className={styles.sessionItemTooltip}>
      <strong>{title}</strong>
      {details.filter(Boolean).map((detail) => <span key={detail}>{detail}</span>)}
    </span>
  );
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
  const title = conversation.title.trim() || fallbackSummary;
  const itemClassName = active
    ? `${styles.sessionItem} ${styles.groupSessionItem} ${styles.teamTreeItemActive}`
    : `${styles.sessionItem} ${styles.groupSessionItem}`;
  const groupStatus = statusLabel(conversation.status);
  const memberLabel = lang === "zh"
    ? `成员：${conversation.participantCount ?? 0} 人`
    : `Members: ${conversation.participantCount ?? 0}`;
  const memberPreview = lang === "zh"
    ? `${conversation.participantCount ?? 0} 人`
    : String(conversation.participantCount ?? 0);
  const tooltip = indexItemTooltip(title, [groupStatus, `${kindLabel} · ${memberLabel}`]);
  const statusKind = String(conversation.status || "").trim().toLowerCase() === "active" ? "active" : "muted";

  return (
    <div className={itemClassName}>
      <VTooltip content={tooltip} width="wide">
        <VNativeButton
          type="button"
          className={styles.teamSessionItemMain}
          aria-current={active ? "true" : undefined}
          aria-label={[title, groupStatus, kindLabel, memberLabel].join(" · ")}
          onClick={() => onOpen(roomId)}
        >
          <span className={styles.conversationAvatarGroup} aria-hidden="true">
            <UsersRound size={15} />
          </span>
          <span className={styles.conversationCopy}>
            <span className={styles.conversationTitleRow}>
              <span className={styles.teamSessionItemTitle}>{title}</span>
              <VStatusChip
                tone={statusKindTone(statusKind)}
                className={styles.sessionStatusChip}
                aria-label={groupStatus}
              >
                {groupStatus}
              </VStatusChip>
            </span>
            <span className={styles.teamConversationMetaRow}>
              <span className={styles.conversationMetaItem}>{kindLabel}</span>
              <span className={styles.conversationMetaMuted}>{memberPreview}</span>
              <time className={styles.conversationMetaMuted}>{formatTime(conversation.updatedAt)}</time>
            </span>
          </span>
        </VNativeButton>
      </VTooltip>
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
  /** When nested under a team section header, prefer a chat-only title. */
  displayTitle?: string;
  onOpen: (roomId: string) => void;
};

export function TeamConversationIndexItem({
  active,
  lang,
  roomId,
  team,
  teamRoute,
  statusLabel,
  displayTitle,
  onOpen,
}: TeamConversationIndexItemProps) {
  void teamRoute;
  const itemClassName = active
    ? `${styles.sessionItem} ${styles.teamTreeItem} ${styles.teamTreeItemActive}`
    : `${styles.sessionItem} ${styles.teamTreeItem}`;
  const title = String(displayTitle || team.name || "").trim() || team.name;
  const teamName = String(team.name || "").trim();
  const secondaryTeamName = teamName && teamName !== title ? teamName : "";
  const teamStatus = teamStatusLabel(team.status, lang, statusLabel);
  const roomLinked = Boolean(roomId);
  const roomTitle = roomLinked
    ? (lang === "zh" ? "团队群聊已同步" : "Team room linked")
    : (lang === "zh" ? "团队群聊待同步" : "Team room pending");
  const roomMeta = roomLinked
    ? (lang === "zh" ? "已同步" : "Linked")
    : (lang === "zh" ? "待同步" : "Pending");
  const memberTitle = teamMemberStatusTitle(team, lang);
  const memberPreview = teamMemberPreview(team, lang);
  const duplicateCount = Number(team.conversationIndexDuplicateCount) || 0;
  const duplicateTitle = lang === "zh"
    ? `已合并 ${duplicateCount} 个同名团队记录`
    : `${duplicateCount} same-name Team records merged`;
  const duplicateMeta = lang === "zh" ? `合并 ${duplicateCount}` : `merged ${duplicateCount}`;
  const disabledReasonId = roomId ? undefined : `team-row-disabled-reason-${team.teamId}`;
  const tooltip = indexItemTooltip(title, [
    secondaryTeamName,
    teamStatus,
    memberTitle,
    roomTitle,
    duplicateCount > 1 ? duplicateTitle : "",
  ]);
  const statusKind: "active" | "pending" | "muted" = !roomLinked
    ? "pending"
    : String(team.status || "").trim().toLowerCase() === "active"
      ? "active"
      : "muted";

  const row = (
    <VNativeButton
      type="button"
      className={styles.teamSessionItemMain}
      disabled={!roomId}
      aria-current={active ? "true" : undefined}
      aria-describedby={disabledReasonId}
      aria-label={[
        title,
        secondaryTeamName,
        teamStatus,
        memberTitle,
        roomTitle,
        duplicateCount > 1 ? duplicateTitle : "",
      ].filter(Boolean).join(" · ")}
      onClick={() => onOpen(roomId)}
    >
      <span className={styles.conversationAvatarGroup} aria-hidden="true">
        <UsersRound size={15} />
      </span>
      <span className={styles.conversationCopy}>
        <span className={styles.conversationTitleRow}>
          <span className={styles.teamSessionItemTitle}>{title}</span>
          <VStatusChip
            tone={statusKindTone(statusKind)}
            className={styles.sessionStatusChip}
            aria-label={roomLinked ? teamStatus : roomTitle}
          >
            {roomLinked ? teamStatus : roomTitle}
          </VStatusChip>
        </span>
        <span className={styles.teamConversationMetaRow}>
          {secondaryTeamName ? (
            <span className={styles.conversationMetaItem}>{secondaryTeamName}</span>
          ) : (
            <span className={styles.conversationMetaItem}>
              {lang === "zh" ? "群聊" : "Group chat"}
            </span>
          )}
          <span className={styles.conversationMetaMuted}>{memberPreview}</span>
          <span className={styles.conversationMetaMuted}>{roomMeta}</span>
          {duplicateCount > 1 ? (
            <span className={styles.conversationMetaMuted} aria-label={duplicateTitle}>
              {duplicateMeta}
            </span>
          ) : null}
        </span>
      </span>
      {disabledReasonId ? (
        <span id={disabledReasonId} className="sr-only">{roomTitle}</span>
      ) : null}
    </VNativeButton>
  );

  return (
    <div className={itemClassName}>
      {roomId ? <VTooltip content={tooltip} width="wide">{row}</VTooltip> : row}
    </div>
  );
}
