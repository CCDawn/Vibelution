import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ConversationView } from "./ConversationView";

function renderConversation(messages: ConversationMessage[]) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationView
        sessionId="session-process-default-expanded"
        title="Session"
        phase="running"
        messages={messages}
        showHeader={false}
        showSessionOverview={false}
        showComposer={false}
        composerValue=""
        composerPlaceholder="Type"
        composerDisabled={false}
        composerPending={false}
        defaultFileContext="workspace"
        onComposerChange={() => undefined}
        onSubmit={() => undefined}
        onEditUserMessage={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView process expansion defaults", () => {
  it("keeps running process details expanded by default", () => {
    const html = renderConversation([
      {
        id: "message-running-process",
        role: "assistant",
        content: "上下文已读取。",
        timestamp: "2026-06-30T08:24:00Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "thought",
            status: "running",
            summary: "正在分析下一步。",
            resultPreview: "运行中思考详情默认展开。",
          },
          {
            sequence: 2,
            kind: "tool",
            status: "running",
            name: "source_collection_context_tool",
            summary: "正在读取上下文。",
            resultPreview: "运行中工具详情默认展开。",
          },
        ],
      },
    ]);

    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain("运行中思考详情默认展开。");
    expect(html).toContain("正在读取上下文。");
  });

  it("keeps completed process details collapsed by default", () => {
    const html = renderConversation([
      {
        id: "message-completed-process",
        role: "assistant",
        content: "最终回答。",
        timestamp: "2026-06-30T08:25:00Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "thought",
            status: "done",
            summary: "已经完成分析。",
            resultPreview: "完成态思考详情仍需手动展开。",
          },
          {
            sequence: 2,
            kind: "tool",
            status: "done",
            name: "source_collection_context_tool",
            summary: "上下文读取完成。",
            resultPreview: "完成态工具详情仍需手动展开。",
          },
        ],
      },
    ]);

    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("完成态思考详情仍需手动展开。");
    expect(html).not.toContain("完成态工具详情仍需手动展开。");
  });
});
