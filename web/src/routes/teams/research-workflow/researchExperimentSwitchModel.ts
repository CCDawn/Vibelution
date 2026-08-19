/**
 * Toolbar experiment switcher (display + URL restore).
 *
 * Mature canvas products (LangGraph Studio threads, n8n executions, AutoGen
 * Studio sessions) keep one graph and switch *instances*. Here the instance is
 * a catalog question's latest workflow checkpoint — the same record the launch
 * panel already attaches. Switching restores `questionId` + `runId` + the
 * checkpoint node; it does not fork, compare, or list the frozen Program
 * EXP-* campaign records.
 */
import type {
  ResearchWorkflowLaunchOption,
} from "../../../api/researchWorkflow";
import { researchRunStatusLabel } from "./researchRunPresentation";

export type ExperimentSwitchOption = {
  questionId: string;
  title: string;
  runId: string;
  currentNodeId: string;
  label: string;
  description: string;
};

export type ExperimentSwitchLocationPatch = {
  questionId: string;
  runId: string;
  node: string | null;
  panel: "node";
};

export type ExperimentChromeIdentity = {
  questionId: string;
  title: string;
  hypothesisSummary: string;
};

type LaunchCheckpoint = NonNullable<ResearchWorkflowLaunchOption["checkpoint"]>;

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
): string {
  if (!normalizeQuestionId(questionId)) return "";
  const ids = (selectedCandidateIds ?? []).map((item) => item.trim()).filter(Boolean);
  if (!ids.length) return "尚未选择假说";
  if (ids.length <= 2) return `假说 ${ids.join("、")}`;
  return `已选 ${ids.length} 个假说`;
}

export function formatExperimentSwitchLabel(
  questionId: string,
  checkpoint: Pick<LaunchCheckpoint, "currentNodeLabel" | "currentNodeId" | "completedCount" | "totalSteps" | "status">,
): string {
  const node = checkpoint.currentNodeLabel.trim() || checkpoint.currentNodeId.trim() || "起点";
  return `${normalizeQuestionId(questionId)} · ${node} · ${checkpoint.completedCount}/${checkpoint.totalSteps} · ${researchRunStatusLabel(checkpoint.status)}`;
}

function optionFromQuestion(question: ResearchWorkflowLaunchOption): ExperimentSwitchOption | null {
  const questionId = normalizeQuestionId(question.questionId);
  const checkpoint = question.checkpoint;
  if (!questionId || !checkpoint?.runId) return null;
  return {
    questionId,
    title: question.title.trim() || questionId,
    runId: checkpoint.runId,
    currentNodeId: checkpoint.currentNodeId.trim(),
    label: formatExperimentSwitchLabel(questionId, checkpoint),
    description: truncateTitle(question.title.trim() || questionId),
  };
}

export function buildExperimentSwitchOptions(input: {
  questions: readonly ResearchWorkflowLaunchOption[];
  current?: {
    questionId: string;
    title?: string;
    runId: string;
    currentNodeId?: string;
    currentNodeLabel?: string;
    status?: string;
    completedCount?: number;
    totalSteps?: number;
  };
}): ExperimentSwitchOption[] {
  const byQuestion = new Map<string, ExperimentSwitchOption>();
  for (const question of input.questions) {
    const option = optionFromQuestion(question);
    if (option) byQuestion.set(option.questionId, option);
  }
  const currentQuestionId = normalizeQuestionId(input.current?.questionId ?? "");
  const currentRunId = input.current?.runId.trim() ?? "";
  if (currentQuestionId && currentRunId && !byQuestion.has(currentQuestionId)) {
    const currentNodeId = input.current?.currentNodeId?.trim() ?? "";
    byQuestion.set(currentQuestionId, {
      questionId: currentQuestionId,
      title: input.current?.title?.trim() || currentQuestionId,
      runId: currentRunId,
      currentNodeId,
      label: formatExperimentSwitchLabel(currentQuestionId, {
        currentNodeLabel: input.current?.currentNodeLabel ?? "",
        currentNodeId,
        completedCount: input.current?.completedCount ?? 0,
        totalSteps: input.current?.totalSteps ?? 16,
        status: input.current?.status ?? "",
      }),
      description: truncateTitle(input.current?.title?.trim() || currentQuestionId),
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
): ExperimentSwitchLocationPatch | null {
  const normalized = normalizeQuestionId(questionId);
  const match = options.find((item) => item.questionId === normalized);
  if (!match) return null;
  return {
    questionId: match.questionId,
    runId: match.runId,
    node: match.currentNodeId || null,
    panel: "node",
  };
}

export function buildExperimentChromeIdentity(input: {
  questionId: string;
  title?: string;
  selectedCandidateIds?: readonly string[] | null;
}): ExperimentChromeIdentity | null {
  const questionId = normalizeQuestionId(input.questionId);
  if (!questionId) return null;
  return {
    questionId,
    title: truncateTitle(input.title?.trim() || questionId, 64),
    hypothesisSummary: formatHypothesisSummary(input.selectedCandidateIds, questionId),
  };
}
