import type { ChatRoomDetail } from "../../api/types";

export type ChatGroupRoundState = {
  groupRoundRunning: boolean;
  groupRoundStopping: boolean;
  groupRoundActive: boolean;
};

export function deriveChatGroupRoundState(
  room: ChatRoomDetail | null | undefined,
): ChatGroupRoundState {
  const activeGroupRoomStatus = String(room?.status ?? "").trim().toLowerCase();
  const groupRoundRunning = activeGroupRoomStatus === "running";
  const groupRoundStopping = activeGroupRoomStatus === "stopping";
  return {
    groupRoundRunning,
    groupRoundStopping,
    groupRoundActive: groupRoundRunning || groupRoundStopping,
  };
}

export type ChatGroupManageChangedInput = {
  standardGroupRoomActive: boolean;
  activeGroupRoom: Pick<ChatRoomDetail, "title" | "mode" | "purpose"> | null | undefined;
  groupManageTitleDraft: string;
  groupManageModeDraft: string;
  groupManagePurposeDraft: string;
  groupManageSessionIds: readonly string[];
  activeGroupParticipantSessionIds: ReadonlySet<string>;
};

export function buildChatGroupManageChanged({
  standardGroupRoomActive,
  activeGroupRoom,
  groupManageTitleDraft,
  groupManageModeDraft,
  groupManagePurposeDraft,
  groupManageSessionIds,
  activeGroupParticipantSessionIds,
}: ChatGroupManageChangedInput): boolean {
  return Boolean(
    standardGroupRoomActive
    && activeGroupRoom
    && (
      groupManageTitleDraft.trim() !== (activeGroupRoom.title || "").trim()
      || groupManageModeDraft !== (activeGroupRoom.mode || "round_robin")
      || groupManagePurposeDraft !== (activeGroupRoom.purpose || "discussion")
      || groupManageSessionIds.length !== activeGroupParticipantSessionIds.size
      || groupManageSessionIds.some((sessionId) => !activeGroupParticipantSessionIds.has(sessionId))
    ),
  );
}

export type ChatGroupRoomActionDisabledInput = {
  standardGroupRoomActive: boolean;
  activeGroupRoom: ChatRoomDetail | null | undefined;
  activeGroupTeamOwned: boolean;
  groupRoundActive: boolean;
  groupRoundRunning: boolean;
  groupManageTitleDraft: string;
  groupManageSessionIds: readonly string[];
  groupManageModeDraft: string;
  groupManagePurposeDraft: string;
  updateGroupRoomPending: boolean;
  deleteGroupRoomPending: boolean;
  resetGroupRoomPending: boolean;
  stopGroupRoundPending: boolean;
};

export type ChatGroupRoomActionDisabledFlags = {
  groupManageDisabled: boolean;
  groupDeleteDisabled: boolean;
  groupResetDisabled: boolean;
  groupStopDisabled: boolean;
};

export function buildChatGroupRoomActionDisabledFlags({
  standardGroupRoomActive,
  activeGroupRoom,
  activeGroupTeamOwned,
  groupRoundActive,
  groupRoundRunning,
  groupManageTitleDraft,
  groupManageSessionIds,
  groupManageModeDraft,
  groupManagePurposeDraft,
  updateGroupRoomPending,
  deleteGroupRoomPending,
  resetGroupRoomPending,
  stopGroupRoundPending,
}: ChatGroupRoomActionDisabledInput): ChatGroupRoomActionDisabledFlags {
  const groupManageDisabled =
    !standardGroupRoomActive
    || !activeGroupRoom
    || activeGroupTeamOwned
    || groupRoundActive
    || updateGroupRoomPending
    || !groupManageTitleDraft.trim()
    || groupManageSessionIds.length < 2
    || !groupManageModeDraft
    || !groupManagePurposeDraft;
  const groupDeleteDisabled =
    !standardGroupRoomActive
    || !activeGroupRoom
    || activeGroupTeamOwned
    || groupRoundActive
    || deleteGroupRoomPending;
  const groupResetDisabled =
    !standardGroupRoomActive
    || !activeGroupRoom
    || groupRoundActive
    || resetGroupRoomPending
    || (activeGroupRoom?.rounds ?? []).length < 1;
  const groupStopDisabled =
    !standardGroupRoomActive
    || !activeGroupRoom
    || !groupRoundRunning
    || stopGroupRoundPending;
  return {
    groupManageDisabled,
    groupDeleteDisabled,
    groupResetDisabled,
    groupStopDisabled,
  };
}
