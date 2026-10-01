/**
 * Team create mutations: template instantiate + blank team create.
 * Self-contained hook — owns cache invalidation, telemetry, and the success
 * outcome handed to the shell (which switches to the created team).
 * Kept out of useTeamShellMutations (8-mutation contract there).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { createTeam, instantiateTeamTemplate } from "../../api/teams";
import { startUserAction } from "../../app/userActionTelemetry";
import type { Team } from "../../api/types";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";

export type TeamCreateOutcome = {
  team: Team;
  /** Agents created from the template; 0 for the blank path. */
  createdAgentCount: number;
  /** Source template display name; "" for the blank path. */
  templateName: string;
  /** True when the template linked chat room is ready. */
  chatRoomReady: boolean;
};

export type TeamCreateSubmitInput = {
  /** Template id; "" = blank team. */
  templateId: string;
  name: string;
};

export type UseTeamCreateActionsOptions = {
  /** Called with the created team so the shell can switch to it. */
  onTeamCreated?: (team: Team) => void;
};

export function useTeamCreateActions({ onTeamCreated }: UseTeamCreateActionsOptions = {}) {
  const queryClient = useQueryClient();
  const chatWorkspaceCache = useMemo(() => createChatWorkspaceCache(queryClient), [queryClient]);
  const [outcome, setOutcome] = useState<TeamCreateOutcome | null>(null);

  const acceptCreatedTeam = (
    team: Team,
    createdAgentCount: number,
    templateName: string,
    context: { telemetry?: { succeeded: (fields?: Record<string, unknown>) => void } } | undefined,
  ) => {
    const chatRoomReady = Boolean(team.linkedChatRoom || team.linkedChatRoomId);
    context?.telemetry?.succeeded({ teamId: team.teamId, createdAgentCount });
    setOutcome({ team, createdAgentCount, templateName, chatRoomReady });
    onTeamCreated?.(team);
    void chatWorkspaceCache.afterTeamChanged(team.teamId);
  };

  const instantiateMutation = useMutation({
    mutationFn: ({ templateId, name }: TeamCreateSubmitInput) =>
      instantiateTeamTemplate(templateId, name),
    onMutate: () => ({
      telemetry: startUserAction("team_create", { mode: "template" }),
    }),
    onSuccess: (payload, _variables, context) => {
      acceptCreatedTeam(
        payload.team,
        payload.createdAgents.length,
        payload.template?.name ?? "",
        context,
      );
    },
    onError: (error, _variables, context) => {
      context?.telemetry?.failed(error);
    },
  });

  const blankMutation = useMutation({
    mutationFn: ({ name }: TeamCreateSubmitInput) => createTeam({ name }),
    onMutate: () => ({
      telemetry: startUserAction("team_create", { mode: "blank" }),
    }),
    onSuccess: (team, _variables, context) => {
      acceptCreatedTeam(team, 0, "", context);
    },
    onError: (error, _variables, context) => {
      context?.telemetry?.failed(error);
    },
  });

  const submit = (input: TeamCreateSubmitInput) => {
    if (input.templateId) {
      instantiateMutation.mutate(input);
    } else {
      blankMutation.mutate(input);
    }
  };

  const error = instantiateMutation.error ?? blankMutation.error ?? null;
  const errorMessage = error instanceof Error ? error.message : error ? String(error) : "";

  const reset = () => {
    setOutcome(null);
    instantiateMutation.reset();
    blankMutation.reset();
  };

  return {
    outcome,
    pending: instantiateMutation.isPending || blankMutation.isPending,
    errorMessage,
    submit,
    reset,
  };
}
