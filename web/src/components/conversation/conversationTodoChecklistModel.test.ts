import { describe, expect, it } from "vitest";

import type { SessionTurnItem } from "../../api/types/chat";
import type { ConversationMessage } from "../../api/types";
import {
  deriveLatestTodoChecklist,
  deriveSessionTodoChecklist,
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

  it("clears a previous checklist when the last full snapshot is explicitly empty", () => {
    expect(deriveLatestTodoChecklist([
      toolCallItem({ todos: SNAPSHOT_A.items }, { sequence: 1 }),
      toolCallItem({ todos: [] }, { sequence: 2 }),
    ])).toBeUndefined();
  });

  it("does not resurrect cleared items when a later snapshot is still malformed", () => {
    expect(deriveLatestTodoChecklist([
      toolCallItem({ todos: SNAPSHOT_A.items }, { sequence: 1 }),
      toolCallItem({ todos: [] }, { sequence: 2 }),
      toolCallItem("{ still streaming", { sequence: 3 }),
    ])).toBeUndefined();
  });

  it("replaces a clear with the next valid checklist", () => {
    const snapshot = deriveLatestTodoChecklist([
      toolCallItem({ todos: [] }, { sequence: 1 }),
      toolCallItem({ todos: SNAPSHOT_A.items }, { sequence: 2 }),
    ]);
    expect(snapshot).toEqual(SNAPSHOT_A);
  });

  it.each([
    { status: "failed" as const },
    { output: JSON.stringify({ status: "error", code: "INVALID_TODOS" }) },
  ])("keeps the previous snapshot when a later call explicitly fails: %j", (failure) => {
    const snapshot = deriveLatestTodoChecklist([
      toolCallItem({ todos: SNAPSHOT_A.items }, { sequence: 1 }),
      toolCallItem({ todos: [] }, { sequence: 2, ...failure }),
    ]);
    expect(snapshot).toEqual(SNAPSHOT_A);
  });

  it.each(["pending", "running"] as const)("keeps a %s snapshot available while the tool streams", (status) => {
    expect(deriveLatestTodoChecklist([
      toolCallItem({ todos: SNAPSHOT_A.items }, { status }),
    ])).toEqual(SNAPSHOT_A);
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

function assistantMessage(
  id: string,
  turnItems: SessionTurnItem[],
  status: "completed" | "running",
): ConversationMessage {
  return {
    id,
    role: "assistant",
    timestamp: "2026-10-12T10:00:00Z",
    turnId: `${id}-turn`,
    status,
    turnItems,
  };
}

describe("deriveSessionTodoChecklist", () => {
  it("returns undefined when no assistant turn carried a checklist", () => {
    expect(deriveSessionTodoChecklist(undefined)).toBeUndefined();
    expect(deriveSessionTodoChecklist([])).toBeUndefined();
    expect(deriveSessionTodoChecklist([
      { id: "u1", role: "user", timestamp: "2026-10-12T10:00:00Z", content: "hi" },
    ])).toBeUndefined();
    expect(deriveSessionTodoChecklist([assistantMessage("a1", [assistantItem(1)], "completed")])).toBeUndefined();
  });

  it("projects the newest checklist turn and its settled state", () => {
    const projection = deriveSessionTodoChecklist([
      assistantMessage("a1", [
        toolCallItem({ todos: SNAPSHOT_A.items }, { sequence: 1 }),
        { ...assistantItem(2), terminal: true } as SessionTurnItem,
      ], "completed"),
      assistantMessage("a2", [assistantItem(1)], "running"),
    ]);

    expect(projection?.messageId).toBe("a1");
    expect(projection?.turnSettled).toBe(true);
    expect(projection?.snapshot.total).toBe(3);
  });

  it("stops at a later clear instead of recovering an older turn's checklist", () => {
    expect(deriveSessionTodoChecklist([
      assistantMessage("a1", [toolCallItem({ todos: SNAPSHOT_A.items })], "completed"),
      assistantMessage("a2", [toolCallItem({ todos: [] })], "completed"),
      assistantMessage("a3", [toolCallItem("{ still streaming")], "running"),
    ])).toBeUndefined();
  });

  it("ignores a failed later turn and retains the last valid session snapshot", () => {
    const projection = deriveSessionTodoChecklist([
      assistantMessage("a1", [toolCallItem({ todos: SNAPSHOT_A.items })], "completed"),
      assistantMessage("a2", [toolCallItem({ todos: [] }, { status: "failed" })], "completed"),
    ]);
    expect(projection?.messageId).toBe("a1");
    expect(projection?.snapshot).toEqual(SNAPSHOT_A);
  });

  it("marks the projection unsettled while the checklist turn is still running", () => {
    const projection = deriveSessionTodoChecklist([
      assistantMessage("a1", [assistantItem(1)], "completed"),
      assistantMessage("a2", [toolCallItem({ todos: SNAPSHOT_A.items }, { sequence: 1 })], "running"),
    ]);

    expect(projection?.messageId).toBe("a2");
    expect(projection?.turnSettled).toBe(false);
  });
});
