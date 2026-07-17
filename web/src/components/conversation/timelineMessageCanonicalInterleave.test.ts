import { describe, expect, it } from "vitest";

import { projectTimelineProcessMessages } from "./timelineMessageProcessProjection";

const TOOL_NAMES = [
  "get_git_status_summary_tool",
  "get_recent_changes_tool",
  "explain_current_worktree_tool",
  "get_core_context_tool",
  "get_current_goal_tool",
] as const;

function nativeTranscript(messageId: string, cells: Record<string, unknown>[]) {
  return {
    version: 1,
    source: "native",
    messageId,
    cells,
    toolCalls: [],
    terminalOperations: [],
    terminalSessions: [],
    modelObservations: [],
  };
}

function toolResultMessage(turnId: string, toolName: string, index: number) {
  const messageId = `tool-result-${index}`;
  return {
    id: messageId,
    role: "assistant",
    content: "",
    timestamp: `2026-07-17T21:52:${String(index).padStart(2, "0")}`,
    codexTranscript: nativeTranscript(messageId, [
      {
        id: `${messageId}-cell`,
        kind: "tool_call",
        messageId,
        status: "completed",
        tone: "neutral",
        title: toolName,
        summary: `result ${index}`,
      },
    ]),
    metadata: {
      kind: "tool_result",
      turnId,
      correlationId: `call-${index}`,
    },
  };
}

describe("canonical committed transcript interleaving", () => {
  it("keeps committed commentary and tools interleaved across durable tool-result replay", () => {
    const turnId = "turn-five-tools";
    const committedMessageId = "assistant-committed";
    const committedCells: Record<string, unknown>[] = TOOL_NAMES.flatMap((toolName, index) => {
      const round = index + 1;
      return [
        {
          id: `commentary-${round}`,
          kind: "assistant_markdown",
          messageId: committedMessageId,
          status: "completed",
          tone: "neutral",
          channel: "commentary",
          phase: "commentary",
          text: `第 ${round} 轮：执行 ${toolName}`,
        },
        {
          id: `canonical-tool-${round}`,
          kind: "tool_call",
          messageId: committedMessageId,
          status: "completed",
          tone: "neutral",
          title: toolName,
          summary: `result ${round}`,
        },
      ];
    });
    committedCells.push({
      id: "final-answer",
      kind: "assistant_markdown",
      messageId: committedMessageId,
      status: "completed",
      tone: "neutral",
      phase: "final",
      text: "链路完整。",
    });

    const projected = projectTimelineProcessMessages([
      ...TOOL_NAMES.map((toolName, index) => toolResultMessage(turnId, toolName, index + 1)),
      {
        id: committedMessageId,
        role: "assistant",
        content: "链路完整。",
        timestamp: "2026-07-17T21:52:47",
        codexTranscript: nativeTranscript(committedMessageId, committedCells),
        metadata: {
          kind: "assistant_item_committed",
          turnId,
        },
      },
    ] as never[]);

    expect(projected).toHaveLength(1);
    expect(projected[0]?.codexTranscript?.cells.map((cell) => cell.id)).toEqual([
      "commentary-1",
      "canonical-tool-1",
      "commentary-2",
      "canonical-tool-2",
      "commentary-3",
      "canonical-tool-3",
      "commentary-4",
      "canonical-tool-4",
      "commentary-5",
      "canonical-tool-5",
      "final-answer",
    ]);
    expect(
      projected[0]?.codexTranscript?.cells
        .filter((cell) => cell.kind === "tool_call")
        .map((cell) => cell.title),
    ).toEqual(TOOL_NAMES);
  });
});
