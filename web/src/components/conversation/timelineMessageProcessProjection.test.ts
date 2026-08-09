import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { mergeCodexTranscripts, projectTimelineProcessMessages } from "./timelineMessageProcessProjection";

const timelineProcessProjectionModulePath = new URL("./timelineMessageProcessProjection.ts", import.meta.url);
const retiredAgentMessageProjectionModulePath = new URL("./agentMessageProcessProjection.ts", import.meta.url);
const retiredConversationProjectionModulePath = new URL("./conversationProcessProjection.ts", import.meta.url);
const timelineProjectionSource = readFileSync(
  new URL("./useAgentMessageTimelineProjection.ts", import.meta.url),
  "utf8",
);

function toolMessage(
  id: string,
  summary: string,
  patch: Partial<ConversationMessage> = {},
): ConversationMessage {
  return {
    id,
    role: "assistant",
    content: "",
    timestamp: "2026-06-26T14:56:00Z",
    feedbackEvents: [
      {
        sequence: 0,
        kind: "tool",
        status: "done",
        name: "apply_diff_edit_tool",
        summary,
      },
    ],
    metadata: { turnId: "turn-edit" },
    ...patch,
  };
}

describe("timeline message process projection", () => {
  it("uses the timeline process projection module as the only production DTO packet entry", () => {
    expect(existsSync(timelineProcessProjectionModulePath)).toBe(true);
    expect(existsSync(retiredAgentMessageProjectionModulePath)).toBe(false);
    expect(existsSync(retiredConversationProjectionModulePath)).toBe(false);
    expect(timelineProjectionSource).toContain("./timelineMessageProcessProjection");
    expect(timelineProjectionSource).not.toContain("./agentMessageProcessProjection");
    expect(timelineProjectionSource).not.toContain("./conversationProcessProjection");
  });it("replaces running canonical snapshots with the completed snapshot for the same call", () => {
    const projected = projectTimelineProcessMessages([
      {
        ...toolMessage("message-tool-running", "reading VERSION"),
        streaming: true,
        feedbackEvents: [{
          sequence: 1,
          kind: "tool",
          callId: "call-read-version",
          status: "running",
          name: "read_file_tool",
          summary: "reading VERSION",
        }],
        timelineItems: [{
          id: "timeline-call-read-version",
          kind: "operation",
          status: "running",
          title: "read_file_tool",
          summary: "reading VERSION",
          operationIds: ["call-read-version"],
        }],
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "message-tool-running",
          streaming: true,
          cells: [{
            id: "tool-live-cell",
            sourceItemId: "tool-call-read-version",
            kind: "tool_call",
            messageId: "message-tool-running",
            status: "running",
            tone: "running",
            title: "read_file_tool",
            text: "reading VERSION",
          }],
          toolCalls: [],
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      },
      {
        ...toolMessage("message-tool-completed", "VERSION -> 1.2.3"),
        timestamp: "2026-06-26T14:56:01Z",
        streaming: false,
        feedbackEvents: [{
          sequence: 1,
          kind: "tool",
          callId: "call-read-version",
          status: "done",
          name: "read_file_tool",
          summary: "VERSION -> 1.2.3",
        }],
        timelineItems: [{
          id: "timeline-call-read-version",
          kind: "operation",
          status: "completed",
          title: "read_file_tool",
          summary: "VERSION -> 1.2.3",
          operationIds: ["call-read-version"],
        }],
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "message-tool-completed",
          streaming: false,
          cells: [{
            id: "tool-persisted-cell",
            sourceItemId: "tool-call-read-version",
            kind: "tool_call",
            messageId: "message-tool-completed",
            status: "completed",
            tone: "neutral",
            title: "read_file_tool",
            text: "VERSION -> 1.2.3",
          }],
          toolCalls: [],
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      },
    ]);

    expect(projected).toHaveLength(1);
    expect(projected[0].streaming).toBe(false);
    expect(projected[0].feedbackEvents).toEqual([
      expect.objectContaining({
        callId: "call-read-version",
        status: "done",
        summary: "VERSION -> 1.2.3",
      }),
    ]);
    expect(projected[0].timelineItems).toEqual([
      expect.objectContaining({
        id: "timeline-call-read-version",
        status: "completed",
      }),
    ]);
    expect(projected[0].codexTranscript?.streaming).toBe(false);
    expect(projected[0].codexTranscript?.cells).toEqual([
      expect.objectContaining({
        id: "tool-persisted-cell",
        sourceItemId: "tool-call-read-version",
        status: "completed",
      }),
    ]);
  });
  it("deduplicates a durable tool result replayed by the same-turn final assistant item", () => {
    const turnId = "session-turn-terra-tool-replay";
    const resultPreview = JSON.stringify({
      dirty_summary: "工作区干净",
      modified_paths: [],
    });
    const persistedToolCell = {
      id: "session-message-46-feedback-1",
      sourceItemId: "session-message-46-feedback-1",
      kind: "tool_call" as const,
      messageId: "session-message-46",
      status: "completed" as const,
      tone: "neutral" as const,
      title: "get_git_status_summary_tool",
      summary: "工作区干净",
      toolLifecycleModel: {
        toolCalls: [{
          toolCallId: "tool_call:session-message-46-feedback-1",
          rawOperationId: "session-message-46-feedback-1",
          status: "completed" as const,
          title: "get_git_status_summary_tool",
          summary: "工作区干净",
          rawToolName: "get_git_status_summary_tool",
          runtimeKind: "tool" as const,
          sequence: 1,
          resultPreview,
        }],
        terminalOperations: [],
        terminalSessions: [],
        modelObservations: [],
      },
    };
    const finalReplayToolCell = {
      ...persistedToolCell,
      id: "session-message-47-feedback-5",
      sourceItemId: "session-message-47-feedback-5",
      messageId: "session-message-47",
      toolLifecycleModel: {
        ...persistedToolCell.toolLifecycleModel,
        toolCalls: [{
          ...persistedToolCell.toolLifecycleModel.toolCalls[0],
          toolCallId: "tool_call:session-message-47-feedback-5",
          rawOperationId: "session-message-47-feedback-5",
          sequence: 5,
        }],
      },
    };
    const projected = projectTimelineProcessMessages([
      {
        id: "session-message-46",
        role: "assistant",
        content: "",
        timestamp: "2026-07-17T10:28:08Z",
        metadata: {
          kind: "tool_result",
          turnId,
          correlationId: "call_56qsyNjZH9c3dQlRlDTTqIIc",
        },
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "session-message-46",
          streaming: false,
          cells: [persistedToolCell],
          toolCalls: persistedToolCell.toolLifecycleModel.toolCalls,
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      },
      {
        id: "session-message-47",
        role: "assistant",
        content: "已检查：工作树干净。",
        timestamp: "2026-07-17T10:30:19Z",
        metadata: {
          kind: "assistant_item_committed",
          turnId,
        },
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "session-message-47",
          streaming: false,
          cells: [
            finalReplayToolCell,
            {
              id: "session-message-47-assistant-markdown",
              kind: "assistant_markdown",
              messageId: "session-message-47",
              status: "completed",
              tone: "neutral",
              text: "已检查：工作树干净。",
            },
          ],
          toolCalls: finalReplayToolCell.toolLifecycleModel.toolCalls,
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      },
    ]);

    expect(projected).toHaveLength(1);
    expect(projected[0].codexTranscript?.cells).toEqual([
      expect.objectContaining({
        id: "session-message-47-feedback-5",
        title: "get_git_status_summary_tool",
      }),
      expect.objectContaining({
        kind: "assistant_markdown",
        text: "已检查：工作树干净。",
      }),
    ]);
  });});
