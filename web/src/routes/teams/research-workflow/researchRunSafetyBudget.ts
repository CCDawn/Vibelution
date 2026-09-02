export const RESEARCH_RUN_SAFETY_STAGES = [
  "knowledge_collection",
  "experiment_design",
  "execution_iteration",
] as const;

export type ResearchRunSafetyStageId = (typeof RESEARCH_RUN_SAFETY_STAGES)[number];
export type ResearchRunSafetyPresetId = "steady" | "recommended" | "extended";

export type ResearchRunSafetyBudget = {
  stageTokens: Record<ResearchRunSafetyStageId, number>;
  toolCalls: number;
  wallClockSeconds: number;
  maxRetries: number;
};

// Stage token presets must stay above the observed worst single formal-node
// attempt (production: one source_finding attempt settled ~407K tokens,
// metering allowed overrun to 460K+).  A stage limit below one real attempt
// deadlocks the stage after the first attempt settles (remaining 0 < the
// admission reference), forcing a manual extend_budget.  The default
// (recommended) preset therefore calibrates at 1M tokens per stage, matching
// the backend launch authority (budget_contract DEFAULT_STAGE_TOKENS = 2M,
// never below the observed attempt scale).
export const RESEARCH_RUN_SAFETY_PRESETS: Record<
  ResearchRunSafetyPresetId,
  { label: string; tokens: number; toolCalls: number; wallClockSeconds: number; maxRetries: number }
> = {
  steady: { label: "稳妥", tokens: 800000, toolCalls: 220, wallClockSeconds: 14400, maxRetries: 2 },
  recommended: { label: "推荐", tokens: 1000000, toolCalls: 300, wallClockSeconds: 21600, maxRetries: 2 },
  extended: { label: "宽裕", tokens: 1500000, toolCalls: 480, wallClockSeconds: 28800, maxRetries: 2 },
};

const DEFAULT_PRESET_ID: ResearchRunSafetyPresetId = "recommended";

function positiveInteger(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : fallback;
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function parseContract(contractJson: string): Record<string, unknown> {
  try {
    const contract = JSON.parse(contractJson) as unknown;
    if (!contract || typeof contract !== "object" || Array.isArray(contract)) {
      throw new Error("invalid contract");
    }
    return contract as Record<string, unknown>;
  } catch {
    throw new Error("运行合同 JSON 无效");
  }
}

function stageTokensFor(tokens: number): Record<ResearchRunSafetyStageId, number> {
  return Object.fromEntries(RESEARCH_RUN_SAFETY_STAGES.map((stageId) => [stageId, tokens])) as Record<ResearchRunSafetyStageId, number>;
}

export function createResearchRunSafetyBudget(
  presetId: ResearchRunSafetyPresetId = DEFAULT_PRESET_ID,
): ResearchRunSafetyBudget {
  const preset = RESEARCH_RUN_SAFETY_PRESETS[presetId];
  return {
    stageTokens: stageTokensFor(preset.tokens),
    toolCalls: preset.toolCalls,
    wallClockSeconds: preset.wallClockSeconds,
    maxRetries: preset.maxRetries,
  };
}

export function totalResearchRunSafetyTokens(budget: ResearchRunSafetyBudget): number {
  return RESEARCH_RUN_SAFETY_STAGES.reduce((total, stageId) => total + budget.stageTokens[stageId], 0);
}

export function matchingResearchRunSafetyPreset(
  budget: ResearchRunSafetyBudget,
): ResearchRunSafetyPresetId | null {
  return (Object.keys(RESEARCH_RUN_SAFETY_PRESETS) as ResearchRunSafetyPresetId[]).find((presetId) => {
    const presetBudget = createResearchRunSafetyBudget(presetId);
    return (
      totalResearchRunSafetyTokens(presetBudget) === totalResearchRunSafetyTokens(budget)
      && RESEARCH_RUN_SAFETY_STAGES.every((stageId) => presetBudget.stageTokens[stageId] === budget.stageTokens[stageId])
      && presetBudget.toolCalls === budget.toolCalls
      && presetBudget.wallClockSeconds === budget.wallClockSeconds
      && presetBudget.maxRetries === budget.maxRetries
    );
  }) ?? null;
}

export function readResearchRunSafetyBudget(contractJson: string): ResearchRunSafetyBudget {
  const contract = parseContract(contractJson);
  const budgetPolicy = record(contract.budgetPolicy);
  if (Object.keys(budgetPolicy).length === 0) {
    throw new Error("运行合同缺少 budgetPolicy");
  }
  const fallback = createResearchRunSafetyBudget();
  const stageBudgets = record(budgetPolicy.stageBudgets);
  return {
    stageTokens: Object.fromEntries(RESEARCH_RUN_SAFETY_STAGES.map((stageId) => {
      const stageBudget = record(stageBudgets[stageId]);
      return [stageId, positiveInteger(stageBudget.tokens, positiveInteger(budgetPolicy.tokens, fallback.stageTokens[stageId]))];
    })) as Record<ResearchRunSafetyStageId, number>,
    toolCalls: positiveInteger(budgetPolicy.toolCalls, fallback.toolCalls),
    wallClockSeconds: positiveInteger(budgetPolicy.wallClockSeconds, fallback.wallClockSeconds),
    maxRetries: positiveInteger(budgetPolicy.maxRetries, fallback.maxRetries),
  };
}

export function createResearchRunSafetyBudgetPolicy(
  safetyBudget: ResearchRunSafetyBudget,
  priorPolicy: Record<string, unknown> = {},
): Record<string, unknown> {
  const stageBudgets = record(priorPolicy.stageBudgets);
  const experiments = positiveInteger(priorPolicy.experiments, 12);
  const computeUnits = positiveInteger(priorPolicy.computeUnits, 100);
  const nextStageBudgets = Object.fromEntries(RESEARCH_RUN_SAFETY_STAGES.map((stageId) => {
    const prior = record(stageBudgets[stageId]);
    return [stageId, {
      ...prior,
      tokens: safetyBudget.stageTokens[stageId],
      toolCalls: safetyBudget.toolCalls,
      wallClockSeconds: safetyBudget.wallClockSeconds,
      experiments: positiveInteger(prior.experiments, experiments),
      computeUnits: positiveInteger(prior.computeUnits, computeUnits),
    }];
  }));
  return {
    ...priorPolicy,
    tokens: Math.max(...RESEARCH_RUN_SAFETY_STAGES.map((stageId) => safetyBudget.stageTokens[stageId])),
    toolCalls: safetyBudget.toolCalls,
    wallClockSeconds: safetyBudget.wallClockSeconds,
    maxRetries: safetyBudget.maxRetries,
    stageBudgets: nextStageBudgets,
  };
}

export function writeResearchRunSafetyBudget(
  contractJson: string,
  safetyBudget: ResearchRunSafetyBudget,
): string {
  const contract = parseContract(contractJson);
  const budgetPolicy = record(contract.budgetPolicy);
  if (Object.keys(budgetPolicy).length === 0) {
    throw new Error("运行合同缺少 budgetPolicy");
  }
  return JSON.stringify({
    ...contract,
    budgetPolicy: createResearchRunSafetyBudgetPolicy(safetyBudget, budgetPolicy),
  }, null, 2);
}
