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
});
