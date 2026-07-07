import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ConversationView } from "./ConversationView";

function renderConversation(messages: ConversationMessage[]) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationView
        sessionId="session-1"
        title="Session"
        phase="ready"
        messages={messages}
        showHeader={false}
        showSessionOverview={false}
        showComposer={false}
        processDisplayMode="trace"
        composerValue=""
        composerPlaceholder="Type"
        composerDisabled={false}
        composerPending={false}
        defaultFileContext="workspace"
        onComposerChange={() => undefined}
        onSubmit={() => undefined}
        onStop={() => undefined}
        onClear={() => undefined}
        onJumpToLatest={() => undefined}
        onCreateNewSession={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView native Codex transcript surface", () => {
  it("renders native transcript as the primary assistant surface without duplicating legacy process or response", () => {
    const html = renderConversation([
      {
        id: "assistant-native",
        role: "assistant",
        content: "legacy response should not duplicate",
        timestamp: "2026-07-07T11:00:00Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "done",
            name: "legacy_tool",
            summary: "legacy process should not render",
          },
        ],
        timelineItems: [
          {
            id: "legacy-operation",
            kind: "operation",
            status: "completed",
            title: "legacy_tool",
            summary: "legacy process should not render",
            operationIds: ["assistant-native-feedback-1"],
          },
        ],
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native",
          cells: [
            {
              id: "native-tool",
              kind: "tool_call",
              messageId: "assistant-native",
              status: "completed",
              tone: "neutral",
              title: "native_tool",
              summary: "native process renders",
            },
            {
              id: "native-answer",
              kind: "assistant_markdown",
              messageId: "assistant-native",
              status: "completed",
              tone: "neutral",
              text: "native answer renders",
            },
          ],
        },
      },
    ]);

    expect(html).toContain('data-codex-transcript-surface="true"');
    expect(html).toContain('data-codex-transcript-cell-kind="tool_call"');
    expect(html).toContain('data-codex-transcript-cell-kind="assistant_markdown"');
    expect(html).toContain("native process renders");
    expect(html).toContain("native answer renders");
    expect(html).not.toContain("legacy process should not render");
    expect(html).not.toContain("legacy response should not duplicate");
    expect(html).not.toContain("data-agent-process-kind");
    expect(html).not.toContain("responseSection");
  });

  it("does not render stale native assistant transcript cells on user messages", () => {
    const html = renderConversation([
      {
        id: "user-native-stale",
        role: "user",
        content: "用户消息不应重复显示",
        timestamp: "2026-07-07T11:00:00Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "user-native-stale",
          cells: [
            {
              id: "user-native-stale-assistant-markdown",
              kind: "assistant_markdown",
              messageId: "user-native-stale",
              status: "completed",
              tone: "neutral",
              text: "用户消息不应重复显示",
            },
          ],
        },
      },
    ]);

    expect(html.match(/用户消息不应重复显示/g)).toHaveLength(1);
    expect(html).not.toContain('data-codex-transcript-surface="true"');
    expect(html).not.toContain('data-codex-transcript-cell-kind="assistant_markdown"');
  });

  it("keeps the final answer visible when same-turn process packets carry tool-only native transcript cells", () => {
    const html = renderConversation([
      {
        id: "assistant-native-tool",
        role: "assistant",
        content: "",
        timestamp: "2026-07-07T11:00:00Z",
        metadata: { turnId: "turn-native-answer" },
        toolCalls: [{ name: "grep_search_tool", status: "done", summary: "未找到匹配项" }],
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-tool",
          cells: [
            {
              id: "native-tool-only",
              kind: "tool_call",
              messageId: "assistant-native-tool",
              status: "completed",
              tone: "neutral",
              title: "grep_search_tool",
              summary: "未找到匹配项",
            },
          ],
          toolCalls: [],
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      },
      {
        id: "assistant-native-answer",
        role: "assistant",
        content: "最终回答应该显示。",
        timestamp: "2026-07-07T11:00:10Z",
        metadata: { turnId: "turn-native-answer" },
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-answer",
          cells: [
            {
              id: "native-answer-visible",
              kind: "assistant_markdown",
              messageId: "assistant-native-answer",
              status: "completed",
              tone: "neutral",
              text: "最终回答应该显示。",
            },
          ],
          toolCalls: [],
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      },
    ]);

    expect(html).toContain("grep_search_tool");
    expect(html).toContain("最终回答应该显示。");
    expect(html).toContain('data-codex-transcript-cell-kind="assistant_markdown"');
  });

  it("keeps the legacy projection path when native transcript is unavailable", () => {
    const html = renderConversation([
      {
        id: "assistant-legacy",
        role: "assistant",
        content: "legacy response remains visible",
        timestamp: "2026-07-07T11:05:00Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "done",
            name: "legacy_tool",
            summary: "legacy process renders",
          },
        ],
        timelineItems: [
          {
            id: "legacy-operation",
            kind: "operation",
            status: "completed",
            title: "legacy_tool",
            summary: "legacy process renders",
            operationIds: ["assistant-legacy-feedback-1"],
          },
        ],
      },
    ]);

    expect(html).toContain("legacy process renders");
    expect(html).toContain("data-agent-process-kind");
  });
});
