import { ArrowUpRight, Check, RotateCcw, Trash2 } from "lucide-react";
import type { Dispatch, ReactNode, SetStateAction } from "react";

import type {
  AgentInstance,
  ChatRoomDetail,
  ChatRoomMode,
  ChatRoomPurpose,
  SessionSummary,
} from "../../api/types";
import { PersistedHeightListShell } from "../../components/layout/PersistedHeightListShell";
import { VButton, VDialog, VNativeInput, VStringSelect } from "../../components/vui";
import { sessionAgentDisplayInfo } from "../agentDisplay";
import {
  CHAT_GROUP_MEMBER_PICKER_HEIGHT_PANE,
  CHAT_LIST_HEIGHT_LAYOUT_ID,
} from "./chatListHeights";
import styles from "./ChatGroupManagementDialog.styles";

export type ChatGroupManagementDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  lang: "zh" | "en";
  activeGroupRoom: ChatRoomDetail | null | undefined;
  activeGroupTeamOwned: boolean;
  activeGroupTeam: { teamId: string } | null | undefined;
  groupManageChanged: boolean;
  groupManageDisabled: boolean;
  groupDeleteDisabled: boolean;
  groupResetDisabled: boolean;
  groupRoundActive: boolean;
  groupRoundRunning: boolean;
  groupRoomActionError: string;
  setGroupRoomActionError: Dispatch<SetStateAction<string>>;
  groupManageTitleDraft: string;
  setGroupManageTitleDraft: Dispatch<SetStateAction<string>>;
  groupManageModeDraft: string;
  setGroupManageModeDraft: Dispatch<SetStateAction<string>>;
  groupManagePurposeDraft: string;
  setGroupManagePurposeDraft: Dispatch<SetStateAction<string>>;
  readyChatRoomModes: ChatRoomMode[];
  availableChatRoomPurposes: ChatRoomPurpose[];
  chatRoomModeLabel: (mode: ChatRoomMode, lang: "zh" | "en") => string;
  chatRoomPurposeLabel: (purpose: ChatRoomPurpose, lang: "zh" | "en") => string;
  groupManageSessionIds: string[];
  groupManageSessionSet: Set<string>;
  sessions: SessionSummary[] | undefined;
  agentsById: Map<string, AgentInstance>;
  resolveModelLabel: (modelId: string) => string | undefined;
  renderAgentAvatar: (className: string, imageUrl: string | undefined, fallback: string) => ReactNode;
  avatarInitials: (agentCode?: string, name?: string, fallback?: string) => string;
  agentRoleClass: (tone: string) => string;
  avatarImageUrlFrom: (...sources: unknown[]) => string | undefined;
  updateGroupRoomPending: boolean;
  deleteGroupRoomPending: boolean;
  resetGroupRoomPending: boolean;
  onOpenTeam: (teamId: string) => void;
  onApplyGroupRoomManagement: () => void;
  onDeleteActiveGroupRoom: () => void;
  onResetActiveGroupRoom: () => void;
  onToggleGroupManageSession: (sessionId: string) => void;
};

export function ChatGroupManagementDialog(props: ChatGroupManagementDialogProps) {
  const {
    open,
    onOpenChange,
    lang,
    activeGroupRoom,
    activeGroupTeamOwned,
    activeGroupTeam,
    groupManageChanged,
    groupManageDisabled,
    groupDeleteDisabled,
    groupResetDisabled,
    groupRoundActive,
    groupRoundRunning,
    groupRoomActionError,
    setGroupRoomActionError,
    groupManageTitleDraft,
    setGroupManageTitleDraft,
    groupManageModeDraft,
    setGroupManageModeDraft,
    groupManagePurposeDraft,
    setGroupManagePurposeDraft,
    readyChatRoomModes,
    availableChatRoomPurposes,
    chatRoomModeLabel,
    chatRoomPurposeLabel,
    groupManageSessionIds,
    groupManageSessionSet,
    sessions,
    agentsById,
    resolveModelLabel,
    renderAgentAvatar,
    avatarInitials,
    agentRoleClass,
    avatarImageUrlFrom,
    updateGroupRoomPending,
    deleteGroupRoomPending,
    resetGroupRoomPending,
    onOpenTeam,
    onApplyGroupRoomManagement,
    onDeleteActiveGroupRoom,
    onResetActiveGroupRoom,
    onToggleGroupManageSession,
  } = props;

  return (
    <VDialog
      open={open}
      onOpenChange={onOpenChange}
      title={lang === "zh" ? "管理群聊" : "Manage group"}
      description={activeGroupTeamOwned
        ? (lang === "zh" ? "团队关联群聊由团队页维护成员与角色；这里保留只读引用与消息维护操作。" : "Team membership and roles are managed in Teams; this dialog keeps the reference and message maintenance actions.")
        : (lang === "zh" ? "调整群资料、调度方式、目的与成员。" : "Edit group profile, scheduling, purpose, and members.")}
      size="xl"
      contentClassName={styles.dialogContent}
    >
      <div className={styles.dialogBody}>
        <div className={styles.header}>
          <div className={styles.identity}>
            <strong>{activeGroupRoom?.title ?? (lang === "zh" ? "群聊加载中" : "Loading group")}</strong>
            <span className={styles.identityMeta}>
              {groupManageSessionIds.length}/{sessions?.length ?? 0} {lang === "zh" ? "位成员已选" : "members selected"}
            </span>
          </div>
          <div className={styles.actions}>
            {activeGroupTeamOwned && activeGroupTeam ? (
              <VButton
                type="button"
                className={styles.secondaryButton}
                onClick={() => onOpenTeam(activeGroupTeam.teamId)}
                icon={<ArrowUpRight size={14} />}
              >
                <span>{lang === "zh" ? "打开团队" : "Open team"}</span>
              </VButton>
            ) : null}
            <VButton
              type="button"
              className={groupManageChanged ? styles.applyButton : styles.secondaryButton}
              isDisabled={groupManageDisabled || !groupManageChanged}
              onClick={onApplyGroupRoomManagement}
              icon={<Check size={14} />}
            >
              <span>{updateGroupRoomPending ? (lang === "zh" ? "应用中" : "Applying") : (lang === "zh" ? "应用变更" : "Apply")}</span>
            </VButton>
            <VButton
              type="button"
              className={styles.secondaryButton}
              isDisabled={groupResetDisabled}
              onClick={onResetActiveGroupRoom}
              icon={<RotateCcw size={14} />}
            >
              <span>{resetGroupRoomPending ? (lang === "zh" ? "重置中" : "Resetting") : (lang === "zh" ? "重置消息" : "Reset messages")}</span>
            </VButton>
            <VButton
              type="button"
              className={styles.deleteButton}
              isDisabled={groupDeleteDisabled}
              onClick={onDeleteActiveGroupRoom}
              icon={<Trash2 size={14} />}
            >
              <span>{deleteGroupRoomPending ? (lang === "zh" ? "删除中" : "Deleting") : (lang === "zh" ? "删除群聊" : "Delete group")}</span>
            </VButton>
          </div>
        </div>

        {groupRoomActionError ? <div className={styles.notice}>{groupRoomActionError}</div> : null}

        <div className={styles.controls}>
          <label className={styles.titleField}>
            <span>{lang === "zh" ? "群名" : "Name"}</span>
            <VNativeInput
              value={groupManageTitleDraft}
              maxLength={80}
              disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomPending}
              onChange={(event) => {
                setGroupRoomActionError("");
                setGroupManageTitleDraft(event.target.value);
              }}
            />
          </label>
          <label className={styles.selectField}>
            <span>{lang === "zh" ? "调度模式" : "Mode"}</span>
            <VStringSelect
              ariaLabel={lang === "zh" ? "调度模式" : "Mode"}
              value={groupManageModeDraft}
              isDisabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomPending}
              onValueChange={(value) => {
                setGroupRoomActionError("");
                setGroupManageModeDraft(value);
              }}
              options={readyChatRoomModes.map((mode) => ({ value: mode.id, label: chatRoomModeLabel(mode, lang) }))}
            />
          </label>
          <label className={styles.selectField}>
            <span>{lang === "zh" ? "对话目的" : "Purpose"}</span>
            <VStringSelect
              ariaLabel={lang === "zh" ? "对话目的" : "Purpose"}
              value={groupManagePurposeDraft}
              isDisabled={activeGroupTeamOwned || groupRoundRunning || updateGroupRoomPending}
              onValueChange={(value) => {
                setGroupRoomActionError("");
                setGroupManagePurposeDraft(value);
              }}
              options={availableChatRoomPurposes.map((purpose) => ({ value: purpose.id, label: chatRoomPurposeLabel(purpose, lang) }))}
            />
          </label>
          <PersistedHeightListShell
            layoutId={CHAT_LIST_HEIGHT_LAYOUT_ID}
            pane={CHAT_GROUP_MEMBER_PICKER_HEIGHT_PANE}
            label={lang === "zh" ? "调整群成员选择列表高度" : "Resize group member picker height"}
            className={styles.memberPicker}
            resizeHandleClassName={styles.memberPickerResizeHandle}
            role="region"
            aria-label={lang === "zh" ? "群成员选择" : "Group member picker"}
          >
            {(sessions ?? []).map((session) => {
              const selected = groupManageSessionSet.has(session.id);
              const sessionAgent = session.agentId ? agentsById.get(session.agentId) : undefined;
              const display = sessionAgentDisplayInfo(session, sessionAgent, lang, resolveModelLabel);
              const sessionAvatarImageUrl = avatarImageUrlFrom(sessionAgent, session);
              const missingMessage = session.agentMissing
                ? session.agentStatusMessage || (lang === "zh" ? "缺少有效 Agent" : "Missing valid Agent")
                : "";
              return (
                <label key={session.id} className={selected ? `${styles.memberChip} ${styles.memberChipSelected}` : styles.memberChip}>
                  <VNativeInput
                    type="checkbox"
                    checked={selected}
                    disabled={activeGroupTeamOwned || groupRoundActive || updateGroupRoomPending}
                    onChange={() => onToggleGroupManageSession(session.id)}
                  />
                  {renderAgentAvatar(styles.agentAvatar, sessionAvatarImageUrl, avatarInitials(session.agentCode, display.name))}
                  <span className={styles.memberCopy}>
                    <strong>{display.name}</strong>
                    <small className={`${styles.agentRoleTag} ${styles[agentRoleClass(display.tone)]}`}>{display.functionLabel}</small>
                  </span>
                  {missingMessage ? <span className={styles.missingInline} title={missingMessage}>{lang === "zh" ? "缺少有效 Agent" : "Missing Agent"}</span> : null}
                </label>
              );
            })}
          </PersistedHeightListShell>
          {groupRoundActive ? (
            <p className={styles.hint}>{lang === "zh" ? "群聊运行中，成员和模式会在本轮结束后允许修改。" : "The group is running. Members and mode can be changed after this round finishes."}</p>
          ) : groupManageSessionIds.length < 2 ? (
            <p className={styles.hint}>{lang === "zh" ? "群聊至少需要保留 2 位 Agent。" : "A group needs at least 2 agents."}</p>
          ) : null}
        </div>
      </div>
    </VDialog>
  );
}
