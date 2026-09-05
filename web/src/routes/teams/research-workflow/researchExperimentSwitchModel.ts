import type { ResearchWorkflowLaunchOption } from "../../../api/researchWorkflow";
import { getNodeAdapter } from "./nodeAdapterModel";
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
};

function normalizeQuestionId(value: string): string {
  return value.trim().toUpperCase();
}

function truncateTitle(title: string, limit = 48): string {
  const trimmed = title.trim();
  if (trimmed.length <= limit) return trimmed;
  return `${trimmed.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}

/** Question identity is not a research-state projection. */
export function formatExperimentSwitchLabel(questionId: string, title: string): string {
  const id = normalizeQuestionId(questionId);
  return title.trim() && title.trim() !== id ? `${id} · ${truncateTitle(title)}` : id;
}

function checkpointAvailability(question: ResearchWorkflowLaunchOption): string {
  const checkpoint = question.checkpoint;
  if (!checkpoint) return "尚无正式运行记录";
  const currentNodeLabel = getNodeAdapter(checkpoint.currentNodeId)?.label
    || checkpoint.currentNodeLabel?.trim()
    || checkpoint.currentNodeId?.trim()
    || "";
  return [
    researchRunStatusLabel(checkpoint.status),
    `已完成 ${checkpoint.completedCount}/${checkpoint.totalSteps} 步`,
    currentNodeLabel ? `节点：${currentNodeLabel}` : "",
  ].filter(Boolean).join(" · ");
}

function optionFromQuestion(
  question: ResearchWorkflowLaunchOption,
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
    label: formatExperimentSwitchLabel(questionId, title),
    description: `最近运行记录：${checkpointAvailability(question)}`,
  };
}

export function buildExperimentSwitchOptions(input: {
  questions: readonly ResearchWorkflowLaunchOption[];
  current?: {
    questionId: string;
    title?: string;
    runId: string;
    currentNodeId?: string;
  };
}): ExperimentSwitchOption[] {
  const byQuestion = new Map<string, ExperimentSwitchOption>();
  const currentQuestionId = normalizeQuestionId(input.current?.questionId ?? "");
  for (const question of input.questions) {
    const option = optionFromQuestion(question);
    if (option) byQuestion.set(option.questionId, option);
  }
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
        input.current?.title || currentQuestionId,
      ),
      description: `${truncateTitle(input.current?.title?.trim() || currentQuestionId)} · ${currentRunId ? "当前运行" : "尚无正式运行记录"}`,
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
}): ExperimentChromeIdentity | null {
  const questionId = normalizeQuestionId(input.questionId);
  if (!questionId) return null;
  return {
    questionId,
    title: truncateTitle(input.title?.trim() || questionId, 64),
  };
}
