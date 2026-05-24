import { describe, expect, it } from "vitest";

import { filterStructuredLogEntries, parseStructuredLogPreview } from "./structuredLogPreview";

describe("structuredLogPreview", () => {
  it("parses conversation jsonl and separates dialogue, thinking, tool, and system entries", () => {
    const model = parseStructuredLogPreview(
      [
        JSON.stringify({
          type: "external_request",
          turn: 1,
          timestamp: "2026-05-25T01:00:00Z",
          actor: "main",
          content_preview: "请检查日志",
          content_ref: "payloads/user.txt",
        }),
        JSON.stringify({
          type: "reasoning_delta",
          timestamp: "2026-05-25T01:00:01Z",
          role: "assistant",
          content_preview: "我需要先定位最新日志包",
        }),
        JSON.stringify({
          type: "tool_call",
          timestamp: "2026-05-25T01:00:02Z",
          tool_name: "exec_command",
          tool_args: "{\"cmd\":\"rg logs\"}",
        }),
        JSON.stringify({
          event_code: "session.created",
          ts: "2026-05-25T01:00:03Z",
          component: "runtime",
          message: "session initialized",
        }),
      ].join("\n"),
    );

    expect(model?.entries.map((entry) => entry.category)).toEqual(["dialogue", "thinking", "tool", "system"]);
    expect(model?.entries[2].fields).toContainEqual({ key: "tool_name", value: "exec_command" });
  });

  it("parses prefixed backend logs and exposes json payload fields", () => {
    const model = parseStructuredLogPreview(
      '[2026-05-24T16:40:58.813854+00:00] backend.api.request [error] GET /api/logs/runtime-scenes/{scene_id} -> 500 :: {"method":"GET","path":"/api/logs/runtime-scenes/abc","statusCode":500,"durationMs":202.25,"exceptionType":"TypeError","exceptionMessage":"bad call"}',
    );

    expect(model?.kind).toBe("prefixed-log");
    expect(model?.entries[0]).toMatchObject({
      title: "backend.api.request",
      level: "error",
      category: "problem",
    });
    expect(model?.entries[0].fields).toContainEqual({ key: "statusCode", value: "500" });
    expect(model?.entries[0].fields).toContainEqual({ key: "exceptionType", value: "TypeError" });
  });

  it("keeps bad lines out of structured entries and filters by category plus severity", () => {
    const model = parseStructuredLogPreview(
      [
        "not json",
        JSON.stringify({ type: "assistant_message", role: "assistant", content_preview: "done" }),
        JSON.stringify({ type: "tool_result", level: "warning", message: "retrying" }),
      ].join("\n"),
    );

    expect(model?.parseableLineCount).toBe(2);
    expect(model?.totalLineCount).toBe(3);
    expect(filterStructuredLogEntries(model?.entries ?? [], "dialogue", "all")).toHaveLength(1);
    expect(filterStructuredLogEntries(model?.entries ?? [], "all", "warning")).toHaveLength(1);
  });
});
