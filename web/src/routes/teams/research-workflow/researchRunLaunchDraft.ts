import {
  createResearchRunSafetyBudget,
  RESEARCH_RUN_SAFETY_STAGES,
  type ResearchRunSafetyBudget,
} from "./researchRunSafetyBudget";

// Launch form draft is a per-session UI convenience, not layout memory (pane
// sizes stay on WORKBENCH_LAYOUT_IDS) and not shareable deep-link state, so it
// lives in sessionStorage keyed by team.
const LAUNCH_DRAFT_STORAGE_PREFIX = "vibelution.research-run-launch.";

export type ResearchRunLaunchDraft = {
  questionId: string;
  query: string;
  safetyBudget: ResearchRunSafetyBudget;
};

function storageAvailable(): boolean {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined";
}

function positiveInteger(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : fallback;
}

function normalizeSafetyBudget(value: unknown): ResearchRunSafetyBudget {
  const fallback = createResearchRunSafetyBudget();
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return fallback;
  }
  const record = value as Record<string, unknown>;
  const stageTokens = (record.stageTokens && typeof record.stageTokens === "object" && !Array.isArray(record.stageTokens)
    ? record.stageTokens
    : {}) as Record<string, unknown>;
  return {
    stageTokens: Object.fromEntries(
      RESEARCH_RUN_SAFETY_STAGES.map((stageId) => [
        stageId,
        positiveInteger(stageTokens[stageId], fallback.stageTokens[stageId]),
      ]),
    ) as ResearchRunSafetyBudget["stageTokens"],
    toolCalls: positiveInteger(record.toolCalls, fallback.toolCalls),
    wallClockSeconds: positiveInteger(record.wallClockSeconds, fallback.wallClockSeconds),
    maxRetries: positiveInteger(record.maxRetries, fallback.maxRetries),
  };
}

export function readResearchRunLaunchDraft(teamId: string): ResearchRunLaunchDraft | null {
  if (!teamId || !storageAvailable()) {
    return null;
  }
  try {
    const raw = window.sessionStorage.getItem(LAUNCH_DRAFT_STORAGE_PREFIX + teamId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ResearchRunLaunchDraft> | null;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      questionId: typeof parsed.questionId === "string" ? parsed.questionId : "",
      query: typeof parsed.query === "string" ? parsed.query : "",
      safetyBudget: normalizeSafetyBudget(parsed.safetyBudget),
    };
  } catch {
    return null;
  }
}

export function writeResearchRunLaunchDraft(teamId: string, draft: ResearchRunLaunchDraft): void {
  if (!teamId || !storageAvailable()) {
    return;
  }
  try {
    window.sessionStorage.setItem(LAUNCH_DRAFT_STORAGE_PREFIX + teamId, JSON.stringify(draft));
  } catch {
    // Storage blocked/full: draft recovery is a convenience, never fatal.
  }
}

export function clearResearchRunLaunchDraft(teamId: string): void {
  if (!teamId || !storageAvailable()) {
    return;
  }
  try {
    window.sessionStorage.removeItem(LAUNCH_DRAFT_STORAGE_PREFIX + teamId);
  } catch {
    // Storage blocked: nothing to clear.
  }
}
