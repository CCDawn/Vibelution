import { parseToolCallInput } from "../../api/toolCallInput";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { codexTranscriptToolRawName } from "./conversationToolActivityModel";
import type { ConversationToolPresentationLanguage } from "./conversationToolPresentation";

export type ConversationToolChecklistItemStatus = "pending" | "in_progress" | "completed";

export type ConversationToolChecklistItem = {
  id: string;
  label: string;
  status: ConversationToolChecklistItemStatus;
};

export type ConversationToolChecklistModel = {
  /** Canonical row identity of the cell the checklist is projected from. */
  cellId: string;
  toolName: string;
  title: string;
  explanation: string;
  items: ConversationToolChecklistItem[];
  completedCount: number;
};

/** Task/plan tools whose canonical input is a checklist. */
const CHECKLIST_TOOL_IDENTITIES = new Map<string, string>([
  ["plan_update_tool", "plan_update_tool"],
  ["task_create_tool", "task_create_tool"],
  // Human-facing aliases the transcript surface may already have projected.
  ["更新计划", "plan_update_tool"],
  ["创建任务", "task_create_tool"],
]);

const PLAN_TITLE: Record<ConversationToolPresentationLanguage, string> = {
  zh: "计划",
  en: "Plan",
};

const TASK_TITLE: Record<ConversationToolPresentationLanguage, string> = {
  zh: "任务清单",
  en: "Task list",
};

const PLAN_ITEM_LABEL_KEYS = ["step", "text", "title", "description"] as const;
const TASK_ITEM_LABEL_KEYS = ["description", "step", "task", "title", "text"] as const;

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

function normalizeItemStatus(value: unknown): ConversationToolChecklistItemStatus {
  const normalized = compactText(value).toLowerCase().replace(/[\s-]+/g, "_");
  if (normalized === "completed" || normalized === "complete" || normalized === "done") {
    return "completed";
  }
  if (normalized === "in_progress" || normalized === "running" || normalized === "active") {
    return "in_progress";
  }
  return "pending";
}

function parseJsonList(value: unknown): unknown[] {
  if (Array.isArray(value)) {
    return value;
  }
  const text = compactText(value);
  if (!text.startsWith("[")) {
    return [];
  }
  try {
    const parsed = JSON.parse(text);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function itemLabel(item: unknown, keys: readonly string[]): string {
  if (typeof item === "string") {
    return compactText(item);
  }
  if (!item || typeof item !== "object") {
    return "";
  }
  const record = item as Record<string, unknown>;
  for (const key of keys) {
    const label = compactText(record[key]);
    if (label) {
      return label;
    }
  }
  return "";
}

function checklistItems(
  rawItems: unknown[],
  keys: readonly string[],
  withStatus: boolean,
): ConversationToolChecklistItem[] {
  return rawItems.flatMap((item, index) => {
    const label = itemLabel(item, keys);
    if (!label) {
      return [];
    }
    const status = withStatus && item && typeof item === "object"
      ? normalizeItemStatus((item as Record<string, unknown>).status)
      : "pending";
    return [{
      id: `checklist-item-${index}`,
      label,
      status,
    }];
  });
}

function resolveChecklistToolName(cell: CodexTranscriptCell): string {
  const candidates = [
    codexTranscriptToolRawName(cell),
    String(cell.toolLifecycleModel?.toolCalls?.[0]?.rawToolName ?? ""),
    String(cell.diagnosticSummary?.rawToolName ?? ""),
  ];
  for (const candidate of candidates) {
    const identity = CHECKLIST_TOOL_IDENTITIES.get(candidate.trim().toLowerCase());
    if (identity) {
      return identity;
    }
  }
  return "";
}

function cellChecklistInput(cell: CodexTranscriptCell): Record<string, unknown> | undefined {
  return cell.toolArguments ?? parseToolCallInput(cell.toolArguments);
}

/**
 * Project a task/plan tool call onto a checklist model.
 *
 * `plan_update_tool` carries the full plan with per-step status; `task_create_tool`
 * carries the freshly registered task list (all steps pending). Anything that
 * cannot be projected (other tools, failed calls, unparseable or empty input)
 * returns null so the row keeps its generic tool rendering.
 */
export function conversationToolChecklistModel(
  cell: CodexTranscriptCell,
  language: ConversationToolPresentationLanguage,
): ConversationToolChecklistModel | null {
  if (cell.kind !== "tool_call" || cell.status === "failed" || cell.tone === "error") {
    return null;
  }
  const toolName = resolveChecklistToolName(cell);
  if (!toolName) {
    return null;
  }
  const args = cellChecklistInput(cell);
  if (!args) {
    return null;
  }
  let title: string;
  let explanation = "";
  let items: ConversationToolChecklistItem[];
  if (toolName === "plan_update_tool") {
    items = checklistItems(parseJsonList(args.plan), PLAN_ITEM_LABEL_KEYS, true);
    title = PLAN_TITLE[language];
    explanation = compactText(args.explanation);
  } else {
    items = checklistItems(parseJsonList(args.task_list ?? args.taskList), TASK_ITEM_LABEL_KEYS, false);
    title = compactText(args.goal) || TASK_TITLE[language];
  }
  if (items.length === 0) {
    return null;
  }
  return {
    cellId: cell.id,
    toolName,
    title,
    explanation,
    items,
    completedCount: items.filter((item) => item.status === "completed").length,
  };
}
