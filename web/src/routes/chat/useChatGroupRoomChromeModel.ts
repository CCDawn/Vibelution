import type { UseQueryResult } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import type { ChatRoomDetail, ChatRoomParticipant, SessionDetail, Team } from "../../api/types";
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

  const availableGroupParticipants = useMemo(
    () => (activeGroupRoom?.participants ?? []).filter(isAvailableGroupParticipant),
    [activeGroupRoom?.participants],
  );

  const availableGroupParticipantCount = availableGroupParticipants.length;

  const activeGroupRound = latestChatRoomRound(activeGroupRoom);

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
    activeGroupParticipantSessionIds: activeGroupParticipantSessionSet,
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
