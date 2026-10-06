/**
 * Unified team settings mutations: PATCH aggregate config (basics + members)
 * and the create-and-link chat room action. Self-contained hook — owns cache
 * invalidation, telemetry, and error surfacing. Kept out of
 * useTeamShellMutations (8-mutation contract there).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import { syncTeamChatRoom, updateTeam } from "../../api/teams";
import { startUserAction } from "../../app/userActionTelemetry";
import type { Team } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import type { TeamSettingsPayload } from "./teamSettingsModel";

export type UseTeamSettingsActionsOptions = {
  /** Extra callback after a successful save (e.g. close the dialog). */
  onSaved?: (team: Team) => void;
};

export function useTeamSettingsActions({ onSaved }: UseTeamSettingsActionsOptions = {}) {
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);

  const applyTeamResult = (team: Team) => {
    queryClient.setQueryData(queryKeys.team(team.teamId, "full"), team);
    queryClient.setQueryData(queryKeys.team(team.teamId, "light"), team);
    void queryClient.invalidateQueries({ queryKey: queryKeys.teams() });
    // Members changed -> the canvas projection was rewritten server-side.
    void queryClient.invalidateQueries({ queryKey: queryKeys.teamCanvas(team.teamId) });
    void chatWorkspaceCache.afterTeamChanged(team.teamId);
    if (team.linkedChatRoom?.roomId) {
      void chatWorkspaceCache.afterTeamRoomMembershipChanged(team.teamId, team.linkedChatRoom.roomId);
    }
    onSaved?.(team);
  };

  const updateTeamMutation = useMutation({
    mutationFn: ({ teamId, payload }: { teamId: string; payload: TeamSettingsPayload }) =>
      updateTeam(teamId, payload),
    onMutate: ({ teamId, payload }) => ({
      telemetry: startUserAction("team_settings_update", {
        teamId,
        memberCount: payload.members?.length ?? -1,
      }),
    }),
    onSuccess: (team, _variables, context) => {
      context?.telemetry?.succeeded({ teamId: team.teamId });
      applyTeamResult(team);
    },
    onError: (error, { teamId }, context) => {
      context?.telemetry?.failed(error, { teamId });
    },
  });

  const createRoomMutation = useMutation({
    mutationFn: (teamId: string) => syncTeamChatRoom(teamId),
    onMutate: (teamId) => ({
      telemetry: startUserAction("team_settings_room_create", { teamId }),
    }),
    onSuccess: (team, teamId, context) => {
      context?.telemetry?.succeeded({ teamId });
      applyTeamResult(team);
    },
    onError: (error, teamId, context) => {
      context?.telemetry?.failed(error, { teamId });
    },
  });

  return {
    submit: (teamId: string, payload: TeamSettingsPayload) => updateTeamMutation.mutate({ teamId, payload }),
    createRoom: (teamId: string) => createRoomMutation.mutate(teamId),
    pending: updateTeamMutation.isPending,
    createRoomPending: createRoomMutation.isPending,
    errorMessage:
      updateTeamMutation.error instanceof Error
        ? updateTeamMutation.error.message
        : updateTeamMutation.error
          ? String(updateTeamMutation.error)
          : createRoomMutation.error instanceof Error
            ? createRoomMutation.error.message
            : createRoomMutation.error
              ? String(createRoomMutation.error)
              : "",
    reset: () => {
      updateTeamMutation.reset();
      createRoomMutation.reset();
    },
  };
}
