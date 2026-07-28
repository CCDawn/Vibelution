import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import {
  getResearchProjectAgentTaskStatus,
  listTeamResearchProjects,
  startResearchProjectAgentTask,
} from "../../../api/researchProjectAgentTasks";
import type {
  ResearchProjectAgentTaskKind,
  TeamResearchProjectAgentTask,
  TeamResearchProjectAgentTaskStatusPayload,
} from "../../../api/types";
import { researchProjectQueryKey } from "./ResearchProjectSwitcher";

export type StartResearchProjectAgentTaskOptions = {
  targetRef?: string;
  formalRetry?: boolean;
  retryTaskId?: string;
  returnTo: string;
  returnLabel: string;
};

export function researchProjectAgentTaskStatusQueryKey(teamId: string, projectId: string) {
  return ["teams", teamId, "research-projects", projectId, "agent-tasks"] as const;
}

export function latestResearchProjectAgentTaskByKind(
  tasks: TeamResearchProjectAgentTask[],
  taskKind: ResearchProjectAgentTaskKind,
): TeamResearchProjectAgentTask | null {
  return tasks
    .filter((task) => task.taskKind === taskKind)
    .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))[0] ?? null;
}

export function buildResearchProjectAgentTaskIdempotencyKey(
  taskKind: ResearchProjectAgentTaskKind,
  nonce: string,
) {
  return `research-project-ui:${taskKind}:${nonce}`.slice(0, 240);
}

function clickNonce() {
  return globalThis.crypto?.randomUUID?.()
    ?? `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function useResearchProjectAgentTasks(options: {
  teamId: string;
  enabled: boolean;
}) {
  const queryClient = useQueryClient();
  const projectsQuery = useQuery({
    queryKey: researchProjectQueryKey(options.teamId),
    queryFn: () => listTeamResearchProjects(options.teamId),
    enabled: options.enabled && Boolean(options.teamId),
  });
  const activeProjectId = projectsQuery.data?.activeProjectId || "";
  const statusQuery = useQuery({
    queryKey: researchProjectAgentTaskStatusQueryKey(options.teamId, activeProjectId),
    queryFn: () => getResearchProjectAgentTaskStatus(options.teamId, activeProjectId),
    enabled: options.enabled && Boolean(options.teamId && activeProjectId),
    refetchInterval: (query) => {
      const data = query.state.data as TeamResearchProjectAgentTaskStatusPayload | undefined;
      return data?.activeTasks.length ? 3_000 : false;
    },
  });
  const startMutation = useMutation({
    mutationFn: (variables: {
      projectId: string;
      taskKind: ResearchProjectAgentTaskKind;
      targetRef: string;
      idempotencyKey: string;
      formalRetry: boolean;
      retryTaskId: string;
      returnTo: string;
      returnLabel: string;
    }) => startResearchProjectAgentTask(options.teamId, variables.projectId, {
      taskKind: variables.taskKind,
      targetRef: variables.targetRef,
      idempotencyKey: variables.idempotencyKey,
      formalRetry: variables.formalRetry,
      retryTaskId: variables.retryTaskId,
      returnTo: variables.returnTo,
      returnLabel: variables.returnLabel,
    }),
    onSuccess: async (payload) => {
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: researchProjectAgentTaskStatusQueryKey(options.teamId, payload.researchProjectId),
        }),
        queryClient.invalidateQueries({
          queryKey: researchProjectQueryKey(options.teamId),
        }),
      ]);
    },
  });

  const startTask = useCallback(
    (
      taskKind: ResearchProjectAgentTaskKind,
      startOptions: StartResearchProjectAgentTaskOptions,
    ) => {
      if (!activeProjectId) {
        return Promise.reject(new Error("No active research project."));
      }
      return startMutation.mutateAsync({
        projectId: activeProjectId,
        taskKind,
        targetRef: startOptions.targetRef?.trim() || "",
        idempotencyKey: buildResearchProjectAgentTaskIdempotencyKey(taskKind, clickNonce()),
        formalRetry: startOptions.formalRetry === true,
        retryTaskId: startOptions.retryTaskId?.trim() || "",
        returnTo: startOptions.returnTo,
        returnLabel: startOptions.returnLabel,
      });
    },
    [activeProjectId, startMutation],
  );

  return {
    activeProjectId,
    tasks: statusQuery.data?.tasks ?? [],
    supportedTaskKinds: statusQuery.data?.supportedTaskKinds ?? [],
    isLoading: projectsQuery.isPending || (Boolean(activeProjectId) && statusQuery.isPending),
    isFetching: projectsQuery.isFetching || statusQuery.isFetching,
    isStarting: startMutation.isPending,
    startingTaskKind: startMutation.variables?.taskKind ?? null,
    error: startMutation.error || statusQuery.error || projectsQuery.error,
    startTask,
    refetch: statusQuery.refetch,
  };
}
