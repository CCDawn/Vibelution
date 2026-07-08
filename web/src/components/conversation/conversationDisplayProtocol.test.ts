import { describe, expect, it } from "vitest";

import {
  shouldDisplayRuntimeStatus,
  shouldDisplayTranscriptCell,
} from "./conversationDisplayProtocol";

describe("conversationDisplayProtocol", () => {
  it("hides internal runtime statuses from visible conversation surfaces", () => {
    expect(shouldDisplayRuntimeStatus({
      kind: "status",
      name: "context_prepare",
      status: "done",
      summary: "正在准备对话上下文...",
    })).toBe(false);
    expect(shouldDisplayRuntimeStatus({
      kind: "status",
      name: "retrying",
      status: "done",
      summary: "第 1/5 次；原因：server_error。",
    })).toBe(false);
  });

  it("keeps failed internal runtime statuses visible as temporary error information", () => {
    expect(shouldDisplayRuntimeStatus({
      kind: "status",
      name: "model_request",
      status: "failed",
      error: "server_error",
    })).toBe(true);
  });

  it("keeps recoverable long-loop progress visible", () => {
    expect(shouldDisplayRuntimeStatus({
      kind: "status",
      name: "long_loop_progress",
      status: "running",
      summary: "尚未形成最终回答 · web_fetch_tool 第 3 次工具调用",
    })).toBe(true);
  });

  it("applies the same visibility policy to transcript cells", () => {
    expect(shouldDisplayTranscriptCell({
      id: "status-context",
      kind: "status",
      messageId: "message-1",
      status: "completed",
      tone: "neutral",
      title: "context_prepare",
      summary: "正在准备对话上下文...",
    })).toBe(false);
    expect(shouldDisplayTranscriptCell({
      id: "tool-call",
      kind: "tool_call",
      messageId: "message-1",
      status: "completed",
      tone: "neutral",
      title: "grep_search_tool",
    })).toBe(true);
    expect(shouldDisplayTranscriptCell({
      id: "status-error",
      kind: "status",
      messageId: "message-1",
      status: "failed",
      tone: "error",
      title: "model_request",
      summary: "server_error",
    })).toBe(true);
  });

  it("hides native assistant markdown cells that only contain internal pipeline statuses", () => {
    expect(shouldDisplayTranscriptCell({
      id: "assistant-status-markdown",
      kind: "assistant_markdown",
      messageId: "message-1",
      status: "completed",
      tone: "neutral",
      text: "context_prepare\n正在准备对话上下文...\n\nmodel_request\n正在请求模型，等待首个响应片段...\n\nretrying\n模型连接正在重试...\n第 1/5 次；原因：server_error。本轮仍在继续，请不要重复提交。",
    })).toBe(false);
  });
});
