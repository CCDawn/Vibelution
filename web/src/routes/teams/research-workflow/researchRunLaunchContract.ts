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

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value) ?? "null";
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableJson(item)).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableJson(record[key])}`)
    .join(",")}}`;
}

function fingerprint64(value: string): string {
  let hash = 0xcbf29ce484222325n;
  const prime = 0x100000001b3n;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= BigInt(value.charCodeAt(index));
    hash = BigInt.asUintN(64, hash * prime);
  }
  return hash.toString(16).padStart(16, "0");
}

export function buildResearchRunCreateIdempotencyKey(
  input: Omit<CreateResearchWorkflowRunInput, "idempotencyKey">,
): string {
  return `create:v2:${fingerprint64(stableJson(input))}`;
}

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
  const input: Omit<CreateResearchWorkflowRunInput, "idempotencyKey"> = {
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
  };
  return {
    ...input,
    idempotencyKey: buildResearchRunCreateIdempotencyKey(input),
  };
}
