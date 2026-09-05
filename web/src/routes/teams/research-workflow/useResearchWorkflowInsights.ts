import { useQueries } from "@tanstack/react-query";

import {
  fetchResearchWorkflowBudget,
  fetchResearchWorkflowEvaluation,
  fetchResearchWorkflowExperimentCampaigns,
  fetchResearchWorkflowHandoffs,
  fetchResearchWorkflowHypotheses,
  fetchResearchWorkflowResearchLedger,
} from "../../../api/researchWorkflow";
import { queryKeys } from "../../../api/queryKeys";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";

export function useResearchWorkflowInsights(teamId: string, runId: string, panel: ResearchProcessPanel | null) {
  const scoped = Boolean(teamId.trim() && runId.trim());
  const overviewEnabled = scoped && panel === "timeline";
  const nodeEnabled = scoped && (panel === "node" || panel === "timeline");
  const [ledger, budget, hypotheses, campaigns, evaluation, handoffs] = useQueries({
    queries: [
      {
        queryKey: queryKeys.researchWorkflowLedger(runId, teamId),
        queryFn: () => fetchResearchWorkflowResearchLedger(runId, { teamId }),
        enabled: overviewEnabled,
      },
      {
        queryKey: queryKeys.researchWorkflowBudget(runId, teamId),
        queryFn: () => fetchResearchWorkflowBudget(runId, { teamId }),
        enabled: nodeEnabled,
      },
      {
        queryKey: queryKeys.researchWorkflowHypotheses(runId, teamId),
        queryFn: () => fetchResearchWorkflowHypotheses(runId, { teamId }),
        enabled: overviewEnabled,
      },
      {
        queryKey: queryKeys.researchWorkflowCampaigns(runId, teamId),
        queryFn: () => fetchResearchWorkflowExperimentCampaigns(runId, { teamId }),
        enabled: overviewEnabled,
      },
      {
        queryKey: queryKeys.researchWorkflowEvaluation(runId, teamId),
        queryFn: () => fetchResearchWorkflowEvaluation(runId, { teamId }),
        enabled: overviewEnabled,
      },
      {
        queryKey: queryKeys.researchWorkflowHandoffs(runId, teamId),
        queryFn: () => fetchResearchWorkflowHandoffs(runId, { teamId }),
        enabled: nodeEnabled,
      },
    ],
  });

  const activeQueries = overviewEnabled ? [ledger, budget, hypotheses, campaigns, evaluation, handoffs]
    : nodeEnabled ? [budget, handoffs] : [];
  const firstError = activeQueries
    .map((query) => query.error)
    .find(Boolean);

  return {
    ledger: ledger.data ?? null,
    budget: budget.data ?? null,
    hypotheses: hypotheses.data ?? null,
    campaigns: campaigns.data ?? null,
    evaluation: evaluation.data ?? null,
    handoffs: handoffs.data ?? null,
    loading: activeQueries.some(
      (query) => query.isPending,
    ),
    error: firstError instanceof Error ? firstError.message : firstError ? String(firstError) : null,
  };
}

export type ResearchWorkflowInsights = ReturnType<typeof useResearchWorkflowInsights>;
