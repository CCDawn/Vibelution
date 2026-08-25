import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import type {
  ChatRoomDetail,
  ChatRoomParticipant,
  ChatRoomRound,
  SessionDetail,
  Team,
} from "../../api/types";
import { isAvailableGroupParticipant } from "./chatRoutePresentation";
import {
  buildChatGroupManageChanged,
  buildChatGroupRoomActionDisabledFlags,
  deriveChatGroupRoundState,
} from "./chatGroupRoomActionModel";
import { buildLinkedTeamRoomIds, resolveActiveGroupTeam } from "./chatGroupTeamLinkageModel";
import { latestChatRoomRound } from "./chatSessionDetailHelpers";

export type UseChatGroupRoomChromeModelInput = {
  teams: readonly Team[];
  activeGroupRoom: ChatRoomDetail | null | undefined;
  activeGroupRoomId: string;
  groupPanelActive: boolean;
  standardGroupRoomActive: boolean;
  expandedGroupAgentSessionIds: readonly string[];
  setExpandedGroupAgentSessionIds: React.Dispatch<React.SetStateAction<string[]>>;
  expandedGroupAgentDetailQueries: ReadonlyArray<UseQueryResult<SessionDetail | undefined>>;
  groupManageTitleDraft: string;
  groupManageModeDraft: string;
  groupManagePurposeDraft: string;
  groupManageSessionIds: readonly string[];
  updateGroupRoomPending: boolean;
  deleteGroupRoomPending: boolean;
  resetGroupRoomPending: boolean;
  stopGroupRoundPending: boolean;
};

export type UseChatGroupRoomChromeModelResult = {
  linkedTeamRoomIds: Set<string>;
  activeGroupTeam: Team | null;
  activeGroupTeamOwned: boolean;
  availableGroupParticipants: ChatRoomParticipant[];
  availableGroupParticipantCount: number;
  activeGroupRound: ReturnType<typeof latestChatRoomRound>;
  groupRoundRunning: boolean;
  groupRoundStopping: boolean;
  groupRoundActive: boolean;
  activeGroupParticipantById: Map<string, ChatRoomParticipant>;
  expandedGroupAgentDetailsBySessionId: Map<string, UseQueryResult<SessionDetail | undefined>>;
  groupManageChanged: boolean;
  groupManageDisabled: boolean;
  groupDeleteDisabled: boolean;
  groupResetDisabled: boolean;
  groupStopDisabled: boolean;
};

const FORMAL_MEETING_TYPES = new Set([
  "hypothesis_candidate_generation",
  "hypothesis_review",
]);

function isFormalChatRoomRound(round: ChatRoomRound): boolean {
  const config = round.config && typeof round.config === "object" ? round.config : {};
  const meetingRoundId = String(config.meetingRoundId ?? "").trim();
  if (!meetingRoundId) {
    return false;
  }
  const meetingType = String(config.meetingType ?? "").trim().toLowerCase();
  const receiptAuthority = config.modelInvocationReceiptAuthority;
  const hasReceiptAuthority = Boolean(
    receiptAuthority && typeof receiptAuthority === "object" && !Array.isArray(receiptAuthority),
  );
  return FORMAL_MEETING_TYPES.has(meetingType) || hasReceiptAuthority;
}

export function latestFormalChatRoomRound(
  room: ChatRoomDetail | null | undefined,
): ChatRoomRound | null {
  const rounds = room?.rounds ?? [];
  const latestRound = rounds.length ? rounds[rounds.length - 1] : null;
  return latestRound && isFormalChatRoomRound(latestRound) ? latestRound : null;
}

/**
 * Keep the room roster as the source of identity, while a formal round owns
 * the smaller set and order that is currently visible in the group chrome.
 */
export function deriveAvailableGroupParticipants(
  participants: readonly ChatRoomParticipant[],
  speakerOrder: readonly string[] | null | undefined,
): ChatRoomParticipant[] {
  const availableParticipants = participants.filter(isAvailableGroupParticipant);
  if (!speakerOrder?.length) {
    return availableParticipants;
  }

  const participantsById = new Map<string, ChatRoomParticipant>();
  for (const participant of availableParticipants) {
    if (!participantsById.has(participant.participantId)) {
      participantsById.set(participant.participantId, participant);
    }
  }
  const visibleParticipants: ChatRoomParticipant[] = [];
  const seenParticipantIds = new Set<string>();
  for (const rawParticipantId of speakerOrder) {
    const participantId = String(rawParticipantId ?? "").trim();
    if (!participantId || seenParticipantIds.has(participantId)) {
      continue;
    }
    seenParticipantIds.add(participantId);
    const participant = participantsById.get(participantId);
    if (participant) {
      visibleParticipants.push(participant);
    }
  }
  return visibleParticipants;
}

export function deriveManageableGroupParticipantSessionIds(
  participants: readonly ChatRoomParticipant[],
): Set<string> {
  return new Set(
    participants
      .filter(isAvailableGroupParticipant)
      .map((participant) => participant.sessionId),
  );
}

export function useChatGroupRoomChromeModel({
  teams,
  activeGroupRoom,
  activeGroupRoomId,
  groupPanelActive,
  standardGroupRoomActive,
  expandedGroupAgentSessionIds,
  setExpandedGroupAgentSessionIds,
  expandedGroupAgentDetailQueries,
  groupManageTitleDraft,
  groupManageModeDraft,
  groupManagePurposeDraft,
  groupManageSessionIds,
  updateGroupRoomPending,
  deleteGroupRoomPending,
  resetGroupRoomPending,
  stopGroupRoundPending,
}: UseChatGroupRoomChromeModelInput): UseChatGroupRoomChromeModelResult {
  const linkedTeamRoomIds = useMemo(
    () => buildLinkedTeamRoomIds(teams),
    [teams],
  );

  const activeGroupTeam = useMemo(
    () => resolveActiveGroupTeam(teams, activeGroupRoom, activeGroupRoomId),
    [activeGroupRoom, activeGroupRoomId, teams],
  );

  const activeGroupTeamOwned = Boolean(activeGroupTeam);

  const activeGroupRound = latestChatRoomRound(activeGroupRoom);
  const latestFormalGroupRound = latestFormalChatRoomRound(activeGroupRoom);

  const availableGroupParticipants = useMemo(
    () => deriveAvailableGroupParticipants(
      activeGroupRoom?.participants ?? [],
      latestFormalGroupRound?.speakerOrder,
    ),
    [activeGroupRoom?.participants, latestFormalGroupRound?.speakerOrder],
  );

  const availableGroupParticipantCount = availableGroupParticipants.length;

  const {
    groupRoundRunning,
    groupRoundStopping,
    groupRoundActive,
  } = deriveChatGroupRoundState(activeGroupRoom);

  const activeGroupParticipantById = useMemo(() => {
    const entries = (activeGroupRoom?.participants ?? []).map(
      (participant) => [participant.participantId, participant] as const,
    );
    return new Map(entries);
  }, [activeGroupRoom?.participants]);

  const activeGroupParticipantSessionSet = useMemo(
    () => new Set(availableGroupParticipants.map((participant) => participant.sessionId)),
    [availableGroupParticipants],
  );
  const activeGroupManageParticipantSessionSet = useMemo(
    () => deriveManageableGroupParticipantSessionIds(activeGroupRoom?.participants ?? []),
    [activeGroupRoom?.participants],
  );

  const expandedGroupAgentDetailsBySessionId = useMemo(() => {
    const entries = expandedGroupAgentSessionIds.map((sessionId, index) => {
      const query = expandedGroupAgentDetailQueries[index];
      return [sessionId, query] as const;
    });
    return new Map(entries);
  }, [expandedGroupAgentDetailQueries, expandedGroupAgentSessionIds]);

  useEffect(() => {
    if (!groupPanelActive) {
      if (expandedGroupAgentSessionIds.length) {
        setExpandedGroupAgentSessionIds([]);
      }
      return;
    }
    const nextExpanded = expandedGroupAgentSessionIds.filter(
      (sessionId) => activeGroupParticipantSessionSet.has(sessionId),
    );
    if (nextExpanded.length !== expandedGroupAgentSessionIds.length) {
      setExpandedGroupAgentSessionIds(nextExpanded);
    }
  }, [
    activeGroupParticipantSessionSet,
    expandedGroupAgentSessionIds,
    groupPanelActive,
    setExpandedGroupAgentSessionIds,
  ]);

  const groupManageChanged = buildChatGroupManageChanged({
    standardGroupRoomActive,
    activeGroupRoom,
    groupManageTitleDraft,
    groupManageModeDraft,
    groupManagePurposeDraft,
    groupManageSessionIds,
    activeGroupParticipantSessionIds: activeGroupManageParticipantSessionSet,
  });

  const {
    groupManageDisabled,
    groupDeleteDisabled,
    groupResetDisabled,
    groupStopDisabled,
  } = buildChatGroupRoomActionDisabledFlags({
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
  });

  return {
    linkedTeamRoomIds,
    activeGroupTeam,
    activeGroupTeamOwned,
    availableGroupParticipants,
    availableGroupParticipantCount,
    activeGroupRound,
    groupRoundRunning,
    groupRoundStopping,
    groupRoundActive,
    activeGroupParticipantById,
    expandedGroupAgentDetailsBySessionId,
    groupManageChanged,
    groupManageDisabled,
    groupDeleteDisabled,
    groupResetDisabled,
    groupStopDisabled,
  };
}
