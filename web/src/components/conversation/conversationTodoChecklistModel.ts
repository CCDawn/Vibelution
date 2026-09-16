import type { SessionTurnItem } from "../../api/types/chat";
import { parseToolCallInput } from "../../api/toolCallInput";
import { consolidateSessionTurnItemsV2 } from "../../routes/chatTurnProtocol";

/**
 * Client-derived todo checklist state (Claude Code TodoWrite paradigm).
 *
 * The `todo_write` tool carries one FULL checklist snapshot per call; the
 * checklist card is derived from the journaled tool-call arguments — no extra
 * SSE event, no server-side checklist store. The last valid snapshot in turn
 * order wins (full-replacement semantics).
 */

export type TodoChecklistItemStatus = "pending" | "in_progress" | "completed";

export type TodoChecklistItem = {
  content: string;
  activeForm: string;
  status: TodoChecklistItemStatus;
};

export type TodoChecklistSnapshot = {
  items: TodoChecklistItem[];
  completedCount: number;
  total: number;
  /** True while any item is still pending or in_progress. */
  hasUnfinished: boolean;
};

export const TODO_WRITE_TOOL_NAME = "todo_write";

const VALID_STATUSES: ReadonlySet<string> = new Set(["pending", "in_progress", "completed"]);
const MAX_RENDERED_ITEMS = 50;

function compactText(value: unknown): string {
  return String(value ?? "").trim();
}

function normalizeTodoItem(raw: unknown): TodoChecklistItem | undefined {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return undefined;
  }
  const record = raw as Record<string, unknown>;
  const content = compactText(record.content);
  if (!content) {
    return undefined;
  }
  const status = compactText(record.status).toLowerCase();
  if (!VALID_STATUSES.has(status)) {
    return undefined;
  }
  // Claude Code paradigm: content is imperative, activeForm is present
  // continuous. Tolerate a missing activeForm by falling back to content.
  const activeForm = compactText(record.activeForm) || content;
  return { content, activeForm, status: status as TodoChecklistItemStatus };
}

function parseTodoSnapshot(item: SessionTurnItem): TodoChecklistSnapshot | undefined {
  const input = parseToolCallInput((item as Extract<SessionTurnItem, { type: "tool_call" }>).input);
  const rawTodos = input?.todos;
  if (!Array.isArray(rawTodos)) {
    return undefined;
  }
  const items: TodoChecklistItem[] = [];
  for (const raw of rawTodos.slice(0, MAX_RENDERED_ITEMS)) {
    const normalized = normalizeTodoItem(raw);
    if (normalized) {
      items.push(normalized);
    }
  }
  if (items.length === 0) {
    return undefined;
  }
  const completedCount = items.filter((item) => item.status === "completed").length;
  return {
    items,
    completedCount,
    total: items.length,
    hasUnfinished: completedCount < items.length,
  };
}

/**
 * Latest valid `todo_write` snapshot for one turn, or `undefined` when the
 * turn never carried a parsable checklist. Snapshots that fail to parse
 * (still streaming, malformed) fall back to the previous valid snapshot so
 * the card never flickers away mid-stream.
 */
export function deriveLatestTodoChecklist(
  turnItems: readonly SessionTurnItem[] | undefined,
): TodoChecklistSnapshot | undefined {
  const canonical = consolidateSessionTurnItemsV2(turnItems);
  let latest: TodoChecklistSnapshot | undefined;
  for (const item of canonical) {
    if (item.type !== "tool_call" || compactText(item.toolName) !== TODO_WRITE_TOOL_NAME) {
      continue;
    }
    const snapshot = parseTodoSnapshot(item);
    if (snapshot) {
      latest = snapshot;
    }
  }
  return latest;
}
