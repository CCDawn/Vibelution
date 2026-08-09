import type { CreateResearchWorkflowRunInput } from "../../../api/researchWorkflow";

export const RESEARCH_MODEL_ROUTING_PURPOSES = [
  "source_discovery",
  "extraction",
  "reasoning",
  "review",
  "governance",
] as const;

export type ResearchRunLaunchDraft = {
  questionId: string;
  researchBriefHash: string;
  datasetRefs: string;
  competitionRuleRef: string;
  competitionRuleVersion: string;
  environmentSnapshotRef: string;
  contractJson: string;
};

export function buildResearchRunInput(options: {
  teamId: string;
  projectId: string;
  draft: ResearchRunLaunchDraft;
}): CreateResearchWorkflowRunInput {
  const { teamId, projectId, draft } = options;
  const required = {
    teamId: teamId.trim(),
    projectId: projectId.trim(),
    questionId: draft.questionId.trim(),
    researchBriefHash: draft.researchBriefHash.trim(),
    competitionRuleRef: draft.competitionRuleRef.trim(),
    competitionRuleVersion: draft.competitionRuleVersion.trim(),
    environmentSnapshotRef: draft.environmentSnapshotRef.trim(),
  };
  const missing = Object.entries(required).find(([, value]) => !value);
  if (missing) throw new Error(`${missing[0]} 不能为空`);
  let contract: Record<string, unknown>;
  try {
    contract = JSON.parse(draft.contractJson) as Record<string, unknown>;
  } catch {
    throw new Error("运行合同 JSON 无效");
  }
  const keys = [
    "metricContract",
    "constraintSnapshot",
    "trackAndRubricSnapshot",
    "researchObjectiveContract",
    "sourcePolicy",
    "budgetPolicy",
    "stopPolicy",
    "modelRoutingPolicy",
    "evaluationContract",
  ] as const;
  for (const key of keys) {
    if (!contract[key] || typeof contract[key] !== "object" || Array.isArray(contract[key])) {
      throw new Error(`运行合同缺少 ${key}`);
    }
  }
  const modelRoutingPolicy = contract.modelRoutingPolicy as Record<string, unknown>;
  for (const purpose of RESEARCH_MODEL_ROUTING_PURPOSES) {
    const route = modelRoutingPolicy[purpose];
    const modelRef = typeof route === "string"
      ? route.trim()
      : route && typeof route === "object" && !Array.isArray(route)
        ? String((route as Record<string, unknown>).modelRef || "").trim()
        : "";
    if (!modelRef) throw new Error(`运行合同缺少 modelRoutingPolicy.${purpose}`);
  }
  const datasets = draft.datasetRefs
    .split(/[\n,]/)
    .map((value) => value.trim())
    .filter(Boolean);
  const keySeed = [required.teamId, required.projectId, required.questionId, required.researchBriefHash]
    .join(":")
    .replace(/[^a-zA-Z0-9:._-]/g, "-")
    .slice(0, 180);
  return {
    ...required,
    datasetRefs: datasets,
    metricContract: contract.metricContract as Record<string, unknown>,
    constraintSnapshot: contract.constraintSnapshot as Record<string, unknown>,
    trackAndRubricSnapshot: contract.trackAndRubricSnapshot as Record<string, unknown>,
    researchObjectiveContract: contract.researchObjectiveContract as Record<string, unknown>,
    sourcePolicy: contract.sourcePolicy as Record<string, unknown>,
    budgetPolicy: contract.budgetPolicy as Record<string, unknown>,
    stopPolicy: contract.stopPolicy as Record<string, unknown>,
    modelRoutingPolicy,
    evaluationContract: contract.evaluationContract as Record<string, unknown>,
    idempotencyKey: `create:${keySeed}`,
  };
}
