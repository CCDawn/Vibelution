/**
 * Toolbar experiment switcher (display + URL restore).
 *
 * Mature canvas products (LangGraph Studio threads, n8n executions, AutoGen
 * Studio sessions) keep one graph and switch *instances*. Here the instance is
 * a catalog question's latest workflow checkpoint — the same record the launch
 * panel already attaches. The switcher lists the full launch-options catalog
 * (every question, including checkpoint-less and cancelled checkpoints) and
 * each option surfaces checkpoint availability/status/progress. Selecting an
 * option backed by a checkpoint restores `questionId` + `runId` + the focus
 * node; selecting a checkpoint-less option clears stale runId/node and opens
 * the launch panel prefilled for the question without auto-creating a run. It
 * does not fork, compare, or list the frozen Program EXP-* campaign records.
 */
import type {
  ResearchWorkflowLaunchOption,
} from "../../../api/researchWorkflow";
import { researchRunStatusLabel } from "./researchRunPresentation";

export type ExperimentSwitchOption = {
  questionId: string;
  title: string;
  runId?: string;
  currentNodeId?: string;
  label: string;
  description: string;
};

export type ExperimentSwitchLocationPatch = {
  questionId: string;
  runId: string;
  node: string | null;
  panel: "node" | "launch";
};

export type ExperimentChromeIdentity = {
  questionId: string;
  title: string;
  hypothesisSummary: string;
};

function normalizeQuestionId(value: string): string {
  return value.trim().toUpperCase();
}

function truncateTitle(title: string, limit = 48): string {
  const trimmed = title.trim();
  if (trimmed.length <= limit) return trimmed;
  return `${trimmed.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

export function formatHypothesisSummary(
  selectedCandidateIds: readonly string[] | null | undefined,
  questionId: string,
  chain?: { meetingCount?: number; roundBudget?: number; hypothesisConverged?: boolean } | null,
): string {
  if (!normalizeQuestionId(questionId)) return "";
  const ids = (selectedCandidateIds ?? []).map((item) => item.trim()).filter(Boolean);
  const base = !ids.length
    ? "尚未选择假说"
    : ids.length <= 2
      ? `假说 ${ids.join("、")}`
      : `已选 ${ids.length} 个假说`;
  if (!chain || !ids.length) return base;
  if (chain.hypothesisConverged) return `${base} · 已收敛`;
  const round = Number(chain.meetingCount ?? 0);
  if (round > 0) return `${base} · 第 ${round} 轮讨论`;
  return base;
}

export function formatExperimentSwitchLabel(
  questionId: string,
  hypothesisSummary: string,
): string {
  return `${normalizeQuestionId(questionId)} · ${hypothesisSummary.trim() || "尚未选择假说"}`;
}

function hypothesisForQuestion(
  questionId: string,
  current?: {
    questionId: string;
    selectedCandidateIds?: readonly string[] | null;
  },
): string {
  if (current && normalizeQuestionId(current.questionId) === questionId) {
    return formatHypothesisSummary(current.selectedCandidateIds, questionId);
  }
  return formatHypothesisSummary([], questionId);
}

function checkpointAvailability(question: ResearchWorkflowLaunchOption): string {
  const checkpoint = question.checkpoint;
  if (!checkpoint) return "无 checkpoint";
  return [
    checkpoint.currentNodeLabel?.trim() || checkpoint.currentNodeId?.trim() || "未开始",
    `${checkpoint.completedCount}/${checkpoint.totalSteps}`,
    researchRunStatusLabel(checkpoint.status),
  ].filter(Boolean).join(" · ");
}

function optionFromQuestion(
  question: ResearchWorkflowLaunchOption,
  current?: {
    questionId: string;
    selectedCandidateIds?: readonly string[] | null;
  },
): ExperimentSwitchOption | null {
  const questionId = normalizeQuestionId(question.questionId);
  if (!questionId) return null;
  const checkpoint = question.checkpoint;
  const title = question.title.trim() || questionId;
  return {
    questionId,
    title,
    runId: checkpoint?.runId || undefined,
    currentNodeId: checkpoint?.currentNodeId.trim() || undefined,
    label: formatExperimentSwitchLabel(questionId, hypothesisForQuestion(questionId, current)),
    description: `${truncateTitle(title)} · ${checkpointAvailability(question)}`,
  };
}

export function buildExperimentSwitchOptions(input: {
  questions: readonly ResearchWorkflowLaunchOption[];
  current?: {
    questionId: string;
    title?: string;
    runId: string;
    currentNodeId?: string;
    selectedCandidateIds?: readonly string[] | null;
  };
}): ExperimentSwitchOption[] {
  const byQuestion = new Map<string, ExperimentSwitchOption>();
  for (const question of input.questions) {
    const option = optionFromQuestion(question, input.current);
    if (option) byQuestion.set(option.questionId, option);
  }
  const currentQuestionId = normalizeQuestionId(input.current?.questionId ?? "");
  const currentRunId = input.current?.runId.trim() ?? "";
  if (currentQuestionId && !byQuestion.has(currentQuestionId)) {
    const currentNodeId = input.current?.currentNodeId?.trim() ?? "";
    byQuestion.set(currentQuestionId, {
      questionId: currentQuestionId,
      title: input.current?.title?.trim() || currentQuestionId,
      runId: currentRunId || undefined,
      currentNodeId: currentNodeId || undefined,
      label: formatExperimentSwitchLabel(
        currentQuestionId,
        hypothesisForQuestion(currentQuestionId, input.current),
      ),
      description: `${truncateTitle(input.current?.title?.trim() || currentQuestionId)} · ${currentRunId ? "当前运行" : "无 checkpoint"}`,
    });
  }
  const ordered = [...byQuestion.values()];
  if (!currentQuestionId) return ordered;
  return ordered.sort((left, right) => {
    if (left.questionId === currentQuestionId) return -1;
    if (right.questionId === currentQuestionId) return 1;
    return 0;
  });
}

export function resolveExperimentSwitch(
  options: readonly ExperimentSwitchOption[],
  questionId: string,
  focusNodeId?: string | null,
): ExperimentSwitchLocationPatch | null {
  const normalized = normalizeQuestionId(questionId);
  const match = options.find((item) => item.questionId === normalized);
  if (!match) return null;
  if (!match.runId) {
    return {
      questionId: match.questionId,
      runId: "",
      node: null,
      panel: "launch",
    };
  }
  const focused = String(focusNodeId || "").trim();
  return {
    questionId: match.questionId,
    runId: match.runId,
    node: focused || match.currentNodeId || null,
    panel: "node",
  };
}

export function buildExperimentChromeIdentity(input: {
  questionId: string;
  title?: string;
  selectedCandidateIds?: readonly string[] | null;
  chain?: { meetingCount?: number; roundBudget?: number; hypothesisConverged?: boolean } | null;
}): ExperimentChromeIdentity | null {
  const questionId = normalizeQuestionId(input.questionId);
  if (!questionId) return null;
  return {
    questionId,
    title: truncateTitle(input.title?.trim() || questionId, 64),
    hypothesisSummary: formatHypothesisSummary(input.selectedCandidateIds, questionId, input.chain),
  };
}
