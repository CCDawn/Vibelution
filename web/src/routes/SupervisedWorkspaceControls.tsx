import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { ConfigSummary, EvolutionOverview } from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { VButton } from "../components/vui";
import { useAppI18n } from "../i18n/useAppI18n";
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

const intakeControlClass = "inline-flex min-h-[34px] flex-none items-center gap-1 whitespace-nowrap rounded-full border border-vui-border-soft bg-vui-surface-panel p-[3px]";
const controlLabelClass = "py-0 pl-[7px] pr-[5px] text-[var(--vui-font-xs)] text-vui-fg-secondary max-[760px]:hidden";
const intakeSegmentedClass = "inline-flex gap-1";
const intakeButtonClass = [
  "min-h-[26px] rounded-full border-0 bg-transparent px-2 text-[var(--vui-font-xs)] text-vui-fg-secondary",
  "transition-colors duration-150 hover:bg-vui-surface-row-hover hover:text-vui-fg-primary disabled:cursor-wait disabled:opacity-70",
].join(" ");
const intakeButtonActiveClass = "bg-[color-mix(in_srgb,var(--accent-warm)_16%,transparent)] text-[var(--accent-warm-2)]";

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

      <div className={intakeControlClass}>
        <span className={controlLabelClass}>{t("intakeMode")}</span>
        <div className={intakeSegmentedClass}>
          {(["manual_review", "auto"] as const).map((mode) => (
            <VButton
              key={mode}
              type="button"
              className={
                currentIntakeMode === mode
                  ? `${intakeButtonClass} ${intakeButtonActiveClass}`
                  : intakeButtonClass
              }
              aria-pressed={currentIntakeMode === mode}
              isDisabled={intakeModeMutation.isPending}
              onClick={() => intakeModeMutation.mutate(mode)}
            >
              {intakeModeLabel(mode)}
            </VButton>
          ))}
        </div>
      </div>
    </>
  );
}
