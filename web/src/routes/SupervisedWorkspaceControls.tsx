import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ConfigSummary, EvolutionOverview } from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./SupervisedWorkspaceControls.module.css";
import {
  SupervisedWorkspaceTabs,
  type SupervisedWorkspaceTabSummary,
  type SupervisedWorkspaceView,
  type SupervisedWorkspaceWorkflowStep,
} from "./SupervisedWorkspaceTabs";

type IntakeMode = "manual_review" | "auto";

type SupervisedWorkspaceControlsProps = {
  activeView: SupervisedWorkspaceView;
  activeWorkflowStepId?: SupervisedWorkspaceWorkflowStep | string | null;
  onWorkflowStepSelect?: (stepId: SupervisedWorkspaceWorkflowStep) => void;
  overviewIntakeMode?: string | null;
  configIntakeMode?: string | null;
  tabSummaries?: SupervisedWorkspaceTabSummary;
};

export function getEffectiveIntakeMode(
  overviewIntakeMode?: string | null,
  configIntakeMode?: string | null,
): IntakeMode {
  if (overviewIntakeMode === "auto" || configIntakeMode === "auto") {
    return "auto";
  }
  return "manual_review";
}

export function SupervisedWorkspaceControls({
  activeView,
  activeWorkflowStepId,
  onWorkflowStepSelect,
  overviewIntakeMode,
  configIntakeMode,
  tabSummaries,
}: SupervisedWorkspaceControlsProps) {
  const { t, intakeModeLabel } = useAppI18n();
  const queryClient = useQueryClient();
  const shouldFetchConfig = configIntakeMode == null;
  const shouldFetchOverview = overviewIntakeMode == null;
  const pageVisible = usePageVisibility();

  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchJson<ConfigSummary>("/api/config/public"),
    enabled: shouldFetchConfig,
  });
  const overviewQuery = useQuery({
    queryKey: queryKeys.evolutionOverview(),
    queryFn: () => fetchJson<EvolutionOverview>("/api/evolution/overview"),
    enabled: shouldFetchOverview,
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
  });
  const intakeModeMutation = useMutation({
    mutationFn: (intakeMode: IntakeMode) =>
      fetchJson<ConfigSummary>("/api/config/intake-mode", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ intakeMode }),
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionRuns() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() }),
      ]);
    },
  });

  const currentIntakeMode = getEffectiveIntakeMode(
    overviewIntakeMode ?? overviewQuery.data?.intakeMode,
    configIntakeMode ?? configQuery.data?.intakeMode,
  );

  return (
    <>
      <SupervisedWorkspaceTabs
        activeView={activeView}
        activeWorkflowStepId={activeWorkflowStepId}
        onWorkflowStepSelect={onWorkflowStepSelect}
        summaries={tabSummaries}
      />

      <div className={styles.intakeControl}>
        <span className={styles.controlLabel}>{t("intakeMode")}</span>
        <div className={styles.intakeSegmented}>
          {(["manual_review", "auto"] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              className={
                currentIntakeMode === mode
                  ? `${styles.intakeButton} ${styles.intakeButtonActive}`
                  : styles.intakeButton
              }
              aria-pressed={currentIntakeMode === mode}
              disabled={intakeModeMutation.isPending}
              onClick={() => intakeModeMutation.mutate(mode)}
            >
              {intakeModeLabel(mode)}
            </button>
          ))}
        </div>
      </div>
    </>
  );
}
