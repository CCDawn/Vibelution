import type {
  ResearchBudgetProjection,
  ResearchEvaluationProjection,
  ResearchExperimentCampaignsProjection,
  ResearchHandoffsProjection,
  ResearchHypothesesProjection,
  ResearchLedgerProjection,
  ResearchQuestionLineageProjection,
} from "../types/researchWorkflow";
import { fetchJson, teamQuery } from "./client";

export async function fetchResearchWorkflowHandoffs(
  runId: string,
  options: { teamId: string },
): Promise<ResearchHandoffsProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/handoffs${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowResearchLedger(
  runId: string,
  options: { teamId: string },
): Promise<ResearchLedgerProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/research-ledger${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowBudget(
  runId: string,
  options: { teamId: string },
): Promise<ResearchBudgetProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/budget${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowHypotheses(
  runId: string,
  options: { teamId: string },
): Promise<ResearchHypothesesProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/hypotheses${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowExperimentCampaigns(
  runId: string,
  options: { teamId: string },
): Promise<ResearchExperimentCampaignsProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/experiment-campaigns${teamQuery(options.teamId)}`,
  );
}

export async function fetchResearchWorkflowEvaluation(
  runId: string,
  options: { teamId: string },
): Promise<ResearchEvaluationProjection> {
  return fetchJson(
    `/api/research/workflow-runs/${encodeURIComponent(runId)}/evaluation${teamQuery(options.teamId)}`,
  );
}

/** R4.5 single-question full-chain lineage projection (read-only). */
export async function fetchResearchWorkflowQuestionLineage(
  questionId: string,
  options: { teamId: string },
): Promise<ResearchQuestionLineageProjection> {
  return fetchJson(
    `/api/research/questions/${encodeURIComponent(questionId)}/lineage${teamQuery(options.teamId)}`,
  );
}
