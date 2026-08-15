import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { fetchPublicConfig, updateIntakeMode } from "../api/config";
import { queryKeys } from "../api/queryKeys";
import { EvolutionOverview } from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { VTabs } from "../components/vui";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./SupervisedWorkspaceControls.styles";
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
  const { lang, t, intakeModeLabel } = useAppI18n({ domains: ["evolution"] });
  const queryClient = useQueryClient();
  const shouldFetchConfig = configIntakeMode == null;
  const shouldFetchOverview = overviewIntakeMode == null;
  const pageVisible = usePageVisibility();

  const configQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchPublicConfig(),
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
    mutationFn: (intakeMode: IntakeMode) => updateIntakeMode(intakeMode),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.configPublic() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.runtimeSummary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionOverview() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionWorkbench() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionLibrary() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.evolutionChatReview() }),
      ]);
    },
  });

  const currentIntakeMode = getEffectiveIntakeMode(
    overviewIntakeMode ?? overviewQuery.data?.intakeMode,
    configIntakeMode ?? configQuery.data?.intakeMode,
  );
  const modeImpactHint = (mode: IntakeMode) => {
    if (mode === "auto") {
      return lang === "zh"
        ? "候选会自动进入审核流程；候选池的手工治理动作会被锁定。"
        : "Candidates enter review automatically; manual candidate-governance actions are locked.";
    }
    return lang === "zh"
      ? "逐步确认候选，并保留接纳、激活、回滚和删除操作。"
      : "Review candidates step by step and keep accept, activate, rollback, and delete actions available.";
  };

  return (
    <div className={styles.controlsShellClass}>
      <div className={styles.flowRegionClass}>
        <SupervisedWorkspaceTabs
          activeView={activeView}
          activeWorkflowStepId={activeWorkflowStepId}
          onWorkflowStepSelect={onWorkflowStepSelect}
          summaries={tabSummaries}
        />
      </div>

      <div className={styles.modeRegionClass}>
        <div className={styles.intakeControlClass}>
          <span className={styles.controlLabelClass}>{t("intakeMode")}</span>
          <VTabs
            density="compact"
            className={styles.intakeTabsClass}
            listClassName={styles.intakeTabsListClass}
            triggerClassName={styles.intakeTabsTriggerClass}
            aria-label={t("intakeMode")}
            value={currentIntakeMode}
            onValueChange={(value) => {
              if (intakeModeMutation.isPending) {
                return;
              }
              if (value === "manual_review" || value === "auto") {
                intakeModeMutation.mutate(value);
              }
            }}
            items={[
              {
                id: "manual_review",
                label: intakeModeLabel("manual_review"),
                title: modeImpactHint("manual_review"),
                disabled: intakeModeMutation.isPending,
              },
              {
                id: "auto",
                label: intakeModeLabel("auto"),
                title: modeImpactHint("auto"),
                disabled: intakeModeMutation.isPending,
              },
            ]}
          />
        </div>
      </div>
    </div>
  );
}
