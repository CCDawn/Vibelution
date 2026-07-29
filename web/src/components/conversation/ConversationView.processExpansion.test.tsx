import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";
import styles from "./ConversationView.styles";
import conversationViewSource from "./ConversationView.tsx?raw";

function renderConversation(messages: ConversationMessage[]) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

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
  it("keeps feedback process typography on dense VUI row tokens", () => {
    expect(styles.answerOnlyProcessTitle).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.answerOnlyProcessTitle).not.toContain("[font-size:var(--vui-font-title)]");
    expect(styles.answerOnlyProcessMeta).toContain("[font-size:var(--vui-font-xs)]");
    expect(styles.operationName).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.reActOperationTitle).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.reActToolName).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.reActToolSummary).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.reActToolStatus).toContain("[font-size:var(--vui-font-xs)]");
    expect(styles.reActResultToggle).toContain("[font-size:var(--vui-font-xs)]");
  });

  it("keeps legacy feedback details flat under the process disclosure", () => {
    const feedbackStart = conversationViewSource.indexOf("function renderFeedbackTimelineGroup(");
    const feedbackEnd = conversationViewSource.indexOf("function renderAnswerOnlyProcessGroup(", feedbackStart);
    const feedbackRenderer = conversationViewSource.slice(feedbackStart, feedbackEnd);

    expect(feedbackRenderer).toContain("renderFeedbackTimelineDetails(messageId, operations)");
    expect(feedbackRenderer).not.toContain("renderReActOperationGroup(");
  });

  it("suspends follow-latest and wires a stable scroll anchor for explicit process toggles", () => {
    const handlerStart = conversationViewSource.indexOf("const handleProcessDisclosureUserToggle");
    const handlerEnd = conversationViewSource.indexOf(
      "// Stick-to-bottom:",
      handlerStart,
    );
    const handler = conversationViewSource.slice(handlerStart, handlerEnd);

    expect(handler).toContain("followLatestRef.current = false");
    expect(handler).toContain("captureConversationProcessScrollAnchor(timeline, summary)");
    expect(handler).toContain("restoreConversationProcessScrollAnchor(timeline, summary, anchor)");
    expect(handler.match(/window\.requestAnimationFrame/g)).toHaveLength(2);
    expect(conversationViewSource).toContain("onUserToggle={handleProcessDisclosureUserToggle}");
  });

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

  it("keeps an answer-mode feedback process to one disclosure layer", () => {
    const html = renderConversation([
      {
        id: "message-answer-mode-feedback-process",
        role: "assistant",
        content: "",
        timestamp: "2026-07-25T15:57:00Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "done",
            name: "source_collection_context_tool",
            summary: "Reading source context.",
          },
          {
            sequence: 2,
            kind: "tool",
            status: "running",
            name: "search_code_tool",
            summary: "Searching source.",
          },
        ],
      },
    ]);

    expect(html).toContain('data-agent-process-kind="answer-only"');
    expect(html).not.toContain(styles.reActOperationSummary);
    expect(html).not.toContain("source_collection_context_tool");
    expect(html).not.toContain("search_code_tool");
  });

  it("keeps the running fallback tool row compact and uses the mapped operation label", () => {
    const html = renderConversation([
      {
        id: "message-running-cli-fallback",
        role: "assistant",
        content: "",
        timestamp: "2026-07-14T08:00:00Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "running",
            name: "cli_tool",
            summary: "正在检查工作区",
            resultPreview: "PowerShell 命令仍在运行",
            timestamp: "2026-07-14T08:00:01Z",
          },
        ],
        timelineItems: [
          {
            id: "timeline-running-cli-fallback",
            kind: "operation",
            status: "running",
            title: "cli_tool",
            summary: "正在检查工作区",
            operationIds: ["message-running-cli-fallback-feedback-1"],
          },
        ],
      },
    ]);

    expect(html).toContain("命令");
    expect(html).toContain("运行中");
    expect(html).toContain("正在检查工作区");
    expect(html).not.toContain(">cli_tool<");
    expect(html).not.toContain("调用开始");
    expect(html).not.toContain("运行开始");
    expect(styles.timelineCellHeader).toContain("grid-cols-[20px_minmax(0,1fr)]");
    expect(styles.timelineCellHeader).not.toContain("grid-cols-[20px_minmax(0,1fr)_24px]");
    expect(styles.rolloutTraceList).not.toContain("col-start-2");
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

  it("keeps settled process summaries compact without leaking raw internal labels", () => {
    const html = renderConversation([
      {
        id: "message-settled-raw-process",
        role: "assistant",
        content: "状态\n已经接到真实状态了。",
        timestamp: "2026-07-07T14:21:00Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "thought",
            status: "done",
            summary: "思考过程",
            resultPreview: "internal",
          },
          {
            sequence: 2,
            kind: "tool",
            status: "done",
            name: "read_file_tool",
            summary: "opened latest package",
            resultPreview: "raw read result",
          },
          {
            sequence: 3,
            kind: "tool",
            status: "done",
            name: "search_code_tool",
            summary: "searched session detail",
            resultPreview: "raw search result",
          },
        ],
      },
    ]);

    expect(html).toContain("过程");
    expect(html).toContain("工具调用 2");
    expect(html).not.toContain("思考过程 1");
    expect(html).toContain("状态");
    expect(html).toContain("已经接到真实状态了。");
    expect(html).not.toContain(">internal<");
    expect(html).not.toContain("read_file_tool");
    expect(html).not.toContain("search_code_tool");
    expect(html).not.toContain("opened latest package");
    expect(html).not.toContain("searched session detail");
    expect(html).not.toContain("调用开始");
    expect(html).not.toContain("运行开始");
  });
});
