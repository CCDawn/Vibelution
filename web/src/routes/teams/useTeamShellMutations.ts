/**
 * Team workbench shell write mutations (archive/canvas/message/sync/repair/round).
 * EventSource-free; Route remains draft/view orchestration boundary.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { startChatRoomRound } from "../../api/chat";
import {
  revokeProjectAgentBusMessage,
  sendTeamProjectBusMessage,
} from "../../api/projectAgentBus";
import { queryKeys } from "../../api/queryKeys";
import {
  archiveTeam,
  repairChallengeCupTeamAgents,
  repairKnowledgeExpansionTeamAgents,
  saveTeamCanvas,
  syncTeamChatRoom,
} from "../../api/teams";
import type { ChatRoomDetail, Team, TeamOrganizationCanvas } from "../../api/types";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";

export type TeamShellChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;

export type UseTeamShellMutationsOptions = {
  selectedTeamId: string;
  setSelectedTeamId: Dispatch<SetStateAction<string>>;
  setSelectedNodeId: Dispatch<SetStateAction<string>>;
  clearTeamSearchParams: () => void;
  setTeamMessage: Dispatch<SetStateAction<string>>;
  setTeamTaskTopic: Dispatch<SetStateAction<string>>;
  chatWorkspaceCache: TeamShellChatWorkspaceCache;
};

export function useTeamShellMutations(options: UseTeamShellMutationsOptions) {
  const queryClient = useQueryClient();
  const { chatWorkspaceCache } = options;

  const archiveTeamMutation = useMutation({
    mutationFn: (teamId: string) => archiveTeam(teamId),
    onSuccess: (team, teamId) => {
      options.setSelectedTeamId("");
      options.setSelectedNodeId("");
      options.clearTeamSearchParams();
      void chatWorkspaceCache.afterTeamArchived(teamId, team.linkedChatRoomId || team.linkedChatRoom?.roomId);
    },
  });

  const saveCanvasMutation = useMutation({
    mutationFn: (nextCanvas: TeamOrganizationCanvas) => saveTeamCanvas(nextCanvas),
    onSuccess: (canvas, variables) => {
      queryClient.setQueryData(queryKeys.teamCanvas(variables.teamId), canvas);
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
  });

  const sendTeamMessageMutation = useMutation({
    mutationFn: (payload: { teamId: string; content: string; interruptMode: string }) =>
      sendTeamProjectBusMessage(payload),
    onSuccess: (_payload, variables) => {
      if (variables.teamId === options.selectedTeamId) {
        options.setTeamMessage("");
      }
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
  });

  const revokeTeamMessageMutation = useMutation({
    mutationFn: (payload: { teamId: string; eventId: string }) =>
      revokeProjectAgentBusMessage({
        eventId: payload.eventId,
        reason: "Revoked from Agent Center team broadcast history.",
      }),
    onSuccess: (_payload, variables) => {
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
  });

  const syncTeamChatRoomMutation = useMutation({
    mutationFn: (teamId: string) => syncTeamChatRoom(teamId),
    onSuccess: (team) => {
      queryClient.setQueryData(queryKeys.team(team.teamId, "light"), team);
      queryClient.setQueryData(queryKeys.team(team.teamId, "full"), team);
      if (team.linkedChatRoom?.roomId) {
        void chatWorkspaceCache.afterTeamRoomMembershipChanged(team.teamId, team.linkedChatRoom.roomId);
      } else {
        void chatWorkspaceCache.afterTeamChanged(team.teamId);
      }
    },
  });

  const repairChallengeCupTeamAgentsMutation = useMutation({
    mutationFn: (teamId: string) => repairChallengeCupTeamAgents(teamId),
    onSuccess: (payload, teamId) => {
      if (payload.team) {
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "light"), payload.team);
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "full"), payload.team);
      }
      void chatWorkspaceCache.afterTeamChanged(payload.team?.teamId || teamId);
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
  });

  const repairKnowledgeExpansionTeamAgentsMutation = useMutation({
    mutationFn: (teamId: string) => repairKnowledgeExpansionTeamAgents(teamId),
    onSuccess: (payload, teamId) => {
      if (payload.team) {
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "light"), payload.team);
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "full"), payload.team);
      }
      void chatWorkspaceCache.afterTeamChanged(payload.team?.teamId || teamId);
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
  });

  const startTeamRoundMutation = useMutation({
    mutationFn: (payload: { roomId: string; teamId: string; topic: string; mode: string; purpose: string }) =>
      startChatRoomRound(payload.roomId, {
        topic: payload.topic,
        mode: payload.mode,
        purpose: payload.purpose,
        config: {
          source: "team_workspace",
          teamId: payload.teamId,
        },
      }),
    onSuccess: (room, variables) => {
      options.setTeamTaskTopic("");
      queryClient.setQueryData(queryKeys.chatRoom(room.roomId), room);
      void chatWorkspaceCache.afterTeamRoomMembershipChanged(variables.teamId, room.roomId);
    },
  });

  return {
    archiveTeamMutation,
    saveCanvasMutation,
    sendTeamMessageMutation,
    revokeTeamMessageMutation,
    syncTeamChatRoomMutation,
    repairChallengeCupTeamAgentsMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    startTeamRoundMutation,
  };
}
