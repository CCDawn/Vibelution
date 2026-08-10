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

export function useResearchWorkflowInsights(teamId: string, runId: string) {
  const enabled = Boolean(teamId.trim() && runId.trim());
  const [ledger, budget, hypotheses, campaigns, evaluation, handoffs] = useQueries({
    queries: [
      {
        queryKey: queryKeys.researchWorkflowLedger(runId, teamId),
        queryFn: () => fetchResearchWorkflowResearchLedger(runId, { teamId }),
        enabled,
      },
      {
        queryKey: queryKeys.researchWorkflowBudget(runId, teamId),
        queryFn: () => fetchResearchWorkflowBudget(runId, { teamId }),
        enabled,
      },
      {
        queryKey: queryKeys.researchWorkflowHypotheses(runId, teamId),
        queryFn: () => fetchResearchWorkflowHypotheses(runId, { teamId }),
        enabled,
      },
      {
        queryKey: queryKeys.researchWorkflowCampaigns(runId, teamId),
        queryFn: () => fetchResearchWorkflowExperimentCampaigns(runId, { teamId }),
        enabled,
      },
      {
        queryKey: queryKeys.researchWorkflowEvaluation(runId, teamId),
        queryFn: () => fetchResearchWorkflowEvaluation(runId, { teamId }),
        enabled,
      },
      {
        queryKey: queryKeys.researchWorkflowHandoffs(runId, teamId),
        queryFn: () => fetchResearchWorkflowHandoffs(runId, { teamId }),
        enabled,
      },
    ],
  });

  const firstError = [ledger, budget, hypotheses, campaigns, evaluation, handoffs]
    .map((query) => query.error)
    .find(Boolean);

  return {
    ledger: ledger.data ?? null,
    budget: budget.data ?? null,
    hypotheses: hypotheses.data ?? null,
    campaigns: campaigns.data ?? null,
    evaluation: evaluation.data ?? null,
    handoffs: handoffs.data ?? null,
    loading: enabled && [ledger, budget, hypotheses, campaigns, evaluation, handoffs].some(
      (query) => query.isPending,
    ),
    error: firstError instanceof Error ? firstError.message : firstError ? String(firstError) : null,
  };
}

export type ResearchWorkflowInsights = ReturnType<typeof useResearchWorkflowInsights>;
