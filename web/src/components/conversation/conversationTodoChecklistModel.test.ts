import { describe, expect, it } from "vitest";

import type { SessionTurnItem } from "../../api/types/chat";
import {
  deriveLatestTodoChecklist,
  type TodoChecklistSnapshot,
} from "./conversationTodoChecklistModel";

type ToolCallItemInput = Extract<SessionTurnItem, { type: "tool_call" }>;

function toolCallItem(input: unknown, overrides: Partial<ToolCallItemInput> = {}): ToolCallItemInput {
  return {
    id: `id-${Math.random().toString(36).slice(2)}`,
    itemId: `item-${Math.random().toString(36).slice(2)}`,
    type: "tool_call",
    version: 3,
    sessionId: "session-1",
    turnId: "turn-1",
    status: "completed",
    revision: 1,
    sequence: 1,
    callId: `call-${Math.random().toString(36).slice(2)}`,
    toolName: "todo_write",
    input: typeof input === "string" ? input : JSON.stringify(input),
    ...overrides,
  } as ToolCallItemInput;
}

function assistantItem(sequence: number): SessionTurnItem {
  return {
    id: `answer-${sequence}`,
    itemId: `answer-${sequence}`,
    type: "agent_message",
    version: 3,
    sessionId: "session-1",
    turnId: "turn-1",
    phase: "final_answer",
    status: "completed",
    revision: 1,
    sequence,
    text: "done",
  } as SessionTurnItem;
}

const SNAPSHOT_A: TodoChecklistSnapshot = {
  items: [
    { content: "a", activeForm: "doing a", status: "completed" },
    { content: "b", activeForm: "doing b", status: "in_progress" },
    { content: "c", activeForm: "doing c", status: "pending" },
  ],
  completedCount: 1,
  total: 3,
  hasUnfinished: true,
};

describe("deriveLatestTodoChecklist", () => {
  it("derives the checklist from the latest todo_write call", () => {
    const snapshot = deriveLatestTodoChecklist([
      toolCallItem({ todos: SNAPSHOT_A.items }, { sequence: 1 }),
    ]);

    expect(snapshot).toEqual({ items: SNAPSHOT_A.items, completedCount: 1, total: 3, hasUnfinished: true });
  });

  it("applies full-replacement semantics: the last call wins over earlier ones", () => {
    const snapshot = deriveLatestTodoChecklist([
      toolCallItem({ todos: SNAPSHOT_A.items }, { sequence: 1 }),
      toolCallItem(
        { todos: [{ content: "only", activeForm: "only", status: "completed" }] },
        { sequence: 2 },
      ),
    ]);

    expect(snapshot?.total).toBe(1);
    expect(snapshot?.items[0]?.content).toBe("only");
    expect(snapshot?.hasUnfinished).toBe(false);
  });

  it("falls back to the previous valid snapshot when a later one is unparsable", () => {
    const snapshot = deriveLatestTodoChecklist([
      toolCallItem({ todos: SNAPSHOT_A.items }, { sequence: 1 }),
      toolCallItem("{ still streaming", { sequence: 2 }),
    ]);

    expect(snapshot?.total).toBe(3);
  });

  it("returns undefined when the turn has no todo_write call", () => {
    expect(deriveLatestTodoChecklist([assistantItem(1)])).toBeUndefined();
    expect(deriveLatestTodoChecklist(undefined)).toBeUndefined();
  });

  it("ignores other tools and malformed todo entries", () => {
    const snapshot = deriveLatestTodoChecklist([
      toolCallItem({ todos: SNAPSHOT_A.items }, {
        toolName: "grep_search_tool",
        sequence: 1,
      }),
      toolCallItem({ todos: [{ content: "", status: "pending" }, "junk", { content: "ok", status: "weird" }] }, { sequence: 2 }),
    ]);

    expect(snapshot).toBeUndefined();
  });

  it("defaults a missing activeForm to content and accepts JSON string input", () => {
    const snapshot = deriveLatestTodoChecklist([
      toolCallItem({ todos: [{ content: "祈使句", status: "in_progress" }] }),
    ]);

    expect(snapshot?.items[0]).toEqual({
      content: "祈使句",
      activeForm: "祈使句",
      status: "in_progress",
    });
  });
});
