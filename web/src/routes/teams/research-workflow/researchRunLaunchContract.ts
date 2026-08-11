import type {
  CreateResearchWorkflowRunInput,
  ResearchWorkflowSafetyLimits,
} from "../../../api/researchWorkflow";
import type { ResearchRunSafetyBudget } from "./researchRunSafetyBudget";

function stableJson(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) return `[${value.map((item) => stableJson(item)).join(",")}]`;
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

function requireText(value: string, field: string): string {
  const normalized = value.trim();
  if (!normalized) throw new Error(`${field} 不能为空`);
  return normalized;
}

export function safetyLimitsFromBudget(
  budget: ResearchRunSafetyBudget,
): ResearchWorkflowSafetyLimits {
  return {
    stageTokens: {
      knowledge_collection: budget.stageTokens.knowledge_collection,
      experiment_design: budget.stageTokens.experiment_design,
      execution_iteration: budget.stageTokens.execution_iteration,
    },
    toolCalls: budget.toolCalls,
    wallClockSeconds: budget.wallClockSeconds,
    maxRetries: budget.maxRetries,
  };
}

export function buildResearchRunCreateIdempotencyKey(
  input: Omit<CreateResearchWorkflowRunInput, "idempotencyKey">,
): string {
  return `create:v3:${fingerprint64(stableJson(input))}`;
}

export function buildResearchRunInput(options: {
  teamId: string;
  questionId: string;
  safetyBudget: ResearchRunSafetyBudget;
}): CreateResearchWorkflowRunInput {
  const input: Omit<CreateResearchWorkflowRunInput, "idempotencyKey"> = {
    teamId: requireText(options.teamId, "teamId"),
    questionId: requireText(options.questionId, "questionId"),
    safetyLimits: safetyLimitsFromBudget(options.safetyBudget),
  };
  return {
    ...input,
    idempotencyKey: buildResearchRunCreateIdempotencyKey(input),
  };
}
