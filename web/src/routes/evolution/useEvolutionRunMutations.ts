/**
 * Evolution run start / action mutations (T3).
 * Draft/selection state is injected via options so callers stay thin.
 */
import { useMutation } from "@tanstack/react-query";
import type { Dispatch, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import type {
  EvolutionRunActionResponse,
  SelfEvolutionHistoryDeleteResponse,
  SelfObservationRun,
  SupervisedWorktreeRun,
} from "../../api/types";

export type UseEvolutionRunMutationsOptions = {
  lang: "zh" | "en";
  t: (key: any) => string;
  statusLabel: (status: any) => string;
  locationPathname: string;
  locationSearch: string;
  getStartPayload: () => {
    sourceKind: string;
    datasetName: string;
    datasetLimit: number | null;
    bundleName: string;
    keepWorktree: boolean;
    mentalModelMode: string;
    currentIntakeMode: string;
    placeholderAgentBindings: unknown;
  };
  getSelfStartPayload: () => { goal: string; bundleName: string };
  setActionFeedback: Dispatch<SetStateAction<string>>;
  setSelfActionFeedback: Dispatch<SetStateAction<string>>;
  setLiveActiveRun: Dispatch<SetStateAction<any>>;
  setSelectedSelfObservationRunId: Dispatch<SetStateAction<string>>;
  buildSupervisedStartPlaceholder: (input: any) => any;
  isLocalSupervisedStartPlaceholder: (run: any) => boolean;
  isSelfEvolutionWorktreeRun: (run: any) => boolean;
  afterWorktreeRunChanged: () => Promise<unknown> | unknown;
  afterSelfEvolutionChanged: () => Promise<unknown> | unknown;
  afterSupervisedWorkspaceChanged: () => Promise<unknown> | unknown;
};

export function useEvolutionRunMutations(options: UseEvolutionRunMutationsOptions) {
  const uiRoute = () => `${options.locationPathname}${options.locationSearch}`;

  const startWorktreeRunMutation = useMutation({
    onMutate: () => {
      const payload = options.getStartPayload();
      options.setActionFeedback(
        options.lang === "zh"
          ? "启动请求已提交，正在等待运行记录刷新。"
          : "Start request submitted; waiting for the run record to refresh.",
      );
      options.setLiveActiveRun(
        options.buildSupervisedStartPlaceholder({
          sourceKind: payload.sourceKind,
          datasetName: payload.sourceKind === "dataset" ? payload.datasetName : "",
          datasetLimit: payload.datasetLimit,
          bundleName: payload.sourceKind === "bundle" ? payload.bundleName : "",
          keepWorktree: payload.keepWorktree,
          mentalModelMode: payload.mentalModelMode,
          agentBindings: payload.placeholderAgentBindings,
          lang: options.lang,
        }),
      );
    },
    mutationFn: () => {
      const payload = options.getStartPayload();
      return fetchJson<SupervisedWorktreeRun>("/api/evolution/worktree-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceKind: payload.sourceKind,
          datasetName: payload.sourceKind === "dataset" ? payload.datasetName : "",
          datasetLimit: payload.datasetLimit,
          bundleName: payload.sourceKind === "bundle" ? payload.bundleName : "",
          keepWorktree: true,
          mode: payload.currentIntakeMode === "auto" ? "auto" : "manual",
          executionMode: "real",
          confirmRealLlmCost: true,
          mentalModelMode: payload.mentalModelMode,
          uiRoute: uiRoute(),
          clientAction: "start_supervised_worktree_run",
        }),
      });
    },
    onSuccess: async (snapshot) => {
      options.setActionFeedback(snapshot.latestMessage || options.t("startClosedLoopQueued"));
      options.setLiveActiveRun((current: any) =>
        options.isLocalSupervisedStartPlaceholder(current) ? null : current,
      );
      await options.afterWorktreeRunChanged();
    },
    onError: () => {
      options.setLiveActiveRun((current: any) =>
        options.isLocalSupervisedStartPlaceholder(current) ? null : current,
      );
      void options.afterWorktreeRunChanged();
    },
  });

  const startSimulationWorktreeRunMutation = useMutation({
    onMutate: () => {
      options.setActionFeedback("");
    },
    mutationFn: () => {
      const payload = options.getStartPayload();
      return fetchJson<SupervisedWorktreeRun>("/api/evolution/worktree-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceKind: payload.sourceKind,
          datasetName: payload.sourceKind === "dataset" ? payload.datasetName : "",
          datasetLimit: payload.datasetLimit,
          bundleName: payload.sourceKind === "bundle" ? payload.bundleName : "",
          keepWorktree: true,
          mode: payload.currentIntakeMode === "auto" ? "auto" : "manual",
          executionMode: "simulation",
          confirmRealLlmCost: false,
          mentalModelMode: payload.mentalModelMode,
          uiRoute: uiRoute(),
          clientAction: "start_supervised_worktree_simulation",
        }),
      });
    },
    onSuccess: async (snapshot) => {
      options.setActionFeedback(snapshot.latestMessage || options.t("startClosedLoopQueued"));
      await options.afterWorktreeRunChanged();
    },
  });

  const startSelfWorktreeRunMutation = useMutation({
    onMutate: () => {
      options.setSelfActionFeedback("");
    },
    mutationFn: () => {
      const payload = options.getSelfStartPayload();
      return fetchJson<SupervisedWorktreeRun>("/api/evolution/self/worktree-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          goal: payload.goal,
          sourceKind: "bundle",
          bundleName: payload.bundleName,
          mode: "manual",
          executionMode: "simulation",
          confirmRealLlmCost: false,
          uiRoute: uiRoute(),
        }),
      });
    },
    onSuccess: async (snapshot) => {
      options.setSelfActionFeedback(snapshot.latestMessage || options.t("startSelfWorktreeQueued"));
      await options.afterWorktreeRunChanged();
    },
  });

  const startSelfObservationMutation = useMutation({
    onMutate: () => {
      options.setSelfActionFeedback("");
    },
    mutationFn: (payload: Record<string, unknown>) =>
      fetchJson<SelfObservationRun>("/api/evolution/self/observation-runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, uiRoute: "/evolution?track=self" }),
      }),
    onSuccess: async (snapshot) => {
      options.setSelectedSelfObservationRunId(snapshot.runId);
      options.setSelfActionFeedback(snapshot.latestMessage || "");
      await options.afterSelfEvolutionChanged();
    },
  });

  const selfObservationActionMutation = useMutation({
    onMutate: () => {
      options.setSelfActionFeedback("");
    },
    mutationFn: ({ runId, action }: { runId: string; action: string }) =>
      fetchJson<SelfObservationRun>(
        `/api/evolution/self/observation-runs/${encodeURIComponent(runId)}/actions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action }),
        },
      ),
    onSuccess: async (snapshot) => {
      options.setSelectedSelfObservationRunId(snapshot.runId);
      options.setSelfActionFeedback(snapshot.latestMessage || "");
      await options.afterSelfEvolutionChanged();
    },
  });

  const deleteSelfHistoryMutation = useMutation({
    onMutate: () => {
      options.setSelfActionFeedback("");
    },
    mutationFn: (txnIds: string[]) =>
      fetchJson<SelfEvolutionHistoryDeleteResponse>("/api/evolution/self/history/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ txnIds }),
      }),
    onSuccess: async (payload) => {
      options.setSelfActionFeedback(payload.summary || "");
      await options.afterSelfEvolutionChanged();
    },
  });

  const actionMutation = useMutation({
    mutationFn: (variables: { sessionId: string; action: string }) =>
      fetchJson<EvolutionRunActionResponse>(`/api/evolution/runs/${variables.sessionId}/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: variables.action }),
      }),
    onSuccess: async (payload) => {
      options.setActionFeedback(payload.summary);
      await options.afterSupervisedWorkspaceChanged();
    },
  });

  const approvalWorktreeActionMutation = useMutation({
    onMutate: () => {
      options.setActionFeedback("");
    },
    mutationFn: (variables: { runId: string; action: string; reviewerNote?: string }) =>
      fetchJson<SupervisedWorktreeRun>(
        `/api/evolution/worktree-runs/${encodeURIComponent(variables.runId)}/actions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: variables.action,
            reviewerNote: variables.reviewerNote ?? "",
          }),
        },
      ),
    onSuccess: async (snapshot) => {
      options.setActionFeedback(snapshot.latestMessage || options.statusLabel(snapshot.status));
      if (options.isSelfEvolutionWorktreeRun(snapshot)) {
        options.setSelfActionFeedback(snapshot.latestMessage || options.statusLabel(snapshot.status));
      }
      await options.afterWorktreeRunChanged();
    },
  });

  return {
    startWorktreeRunMutation,
    startSimulationWorktreeRunMutation,
    startSelfWorktreeRunMutation,
    startSelfObservationMutation,
    selfObservationActionMutation,
    deleteSelfHistoryMutation,
    actionMutation,
    approvalWorktreeActionMutation,
  };
}
