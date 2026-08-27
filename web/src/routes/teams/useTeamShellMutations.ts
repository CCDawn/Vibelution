/**
 * Team workbench shell write mutations (archive/canvas/message/sync/repair/round).
 * EventSource-free; Route remains draft/view orchestration boundary.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { startChatRoomRound, stopChatRoomRound } from "../../api/chat";
import {
  revokeProjectAgentBusMessage,
  sendTeamProjectBusMessage,
} from "../../api/projectAgentBus";
import { startUserAction } from "../../app/userActionTelemetry";
import { queryKeys } from "../../api/queryKeys";
import {
  archiveTeam,
  repairChallengeCupTeamAgents,
  repairKnowledgeExpansionTeamAgents,
  saveTeamCanvas,
  syncTeamChatRoom,
} from "../../api/teams";
import type { ChatRoomDetail, Team, TeamOrganizationCanvas } from "../../api/types";
import { observeChallengeTeamAgentsAutoRepair } from "./challengeCupTelemetry";
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
    onMutate: (teamId) => ({
      telemetry: startUserAction("team_archive", { teamId }, { destructive: true }),
    }),
    onSuccess: (team, teamId, context) => {
      context?.telemetry?.succeeded({ teamId });
      options.setSelectedTeamId("");
      options.setSelectedNodeId("");
      options.clearTeamSearchParams();
      void chatWorkspaceCache.afterTeamArchived(teamId, team.linkedChatRoomId || team.linkedChatRoom?.roomId);
    },
    onError: (error, teamId, context) => {
      context?.telemetry?.failed(error, { teamId });
    },
  });

  const saveCanvasMutation = useMutation({
    mutationFn: (nextCanvas: TeamOrganizationCanvas) => saveTeamCanvas(nextCanvas),
    onMutate: (variables) => ({
      telemetry: startUserAction("team_canvas_save", { teamId: variables.teamId }),
    }),
    onSuccess: (canvas, variables, context) => {
      context?.telemetry?.succeeded({ teamId: variables.teamId });
      queryClient.setQueryData(queryKeys.teamCanvas(variables.teamId), canvas);
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { teamId: variables.teamId });
    },
  });

  const sendTeamMessageMutation = useMutation({
    mutationFn: (payload: { teamId: string; content: string; interruptMode: string }) =>
      sendTeamProjectBusMessage(payload),
    onMutate: (variables) => ({
      telemetry: startUserAction("team_message_send", {
        teamId: variables.teamId,
        interruptMode: variables.interruptMode,
      }),
    }),
    onSuccess: (_payload, variables, context) => {
      context?.telemetry?.succeeded({ teamId: variables.teamId });
      if (variables.teamId === options.selectedTeamId) {
        options.setTeamMessage("");
      }
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, { teamId: variables.teamId });
    },
  });

  const revokeTeamMessageMutation = useMutation({
    mutationFn: (payload: { teamId: string; eventId: string }) =>
      revokeProjectAgentBusMessage({
        eventId: payload.eventId,
        reason: "Revoked from Agent Center team broadcast history.",
      }),
    onMutate: (variables) => ({
      telemetry: startUserAction("team_message_revoke", {
        teamId: variables.teamId,
        eventId: variables.eventId,
      }, { destructive: true }),
    }),
    onSuccess: (_payload, variables, context) => {
      context?.telemetry?.succeeded({ teamId: variables.teamId, eventId: variables.eventId });
      void chatWorkspaceCache.afterTeamChanged(variables.teamId);
    },
    onError: (error, variables, context) => {
      context?.telemetry?.failed(error, {
        teamId: variables.teamId,
        eventId: variables.eventId,
      });
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
      observeChallengeTeamAgentsAutoRepair({ teamId });
      if (payload.team) {
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "light"), payload.team);
        queryClient.setQueryData(queryKeys.team(payload.team.teamId, "full"), payload.team);
      }
      void chatWorkspaceCache.afterTeamChanged(payload.team?.teamId || teamId);
      void chatWorkspaceCache.afterAgentWorkspaceChanged();
    },
    onError: (error: unknown, teamId) => {
      observeChallengeTeamAgentsAutoRepair({ teamId, error });
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

  const stopTeamRoundMutation = useMutation({
    mutationFn: (payload: { roomId: string; teamId: string }) => stopChatRoomRound(payload.roomId),
    onSuccess: (room, variables) => {
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
    stopTeamRoundMutation,
    repairChallengeCupTeamAgentsMutation,
    repairKnowledgeExpansionTeamAgentsMutation,
    startTeamRoundMutation,
  };
}
