import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AgentThread } from ".";
import { AgentThreadView } from "./AgentThreadView";

function renderThread(thread: AgentThread) {
  return renderToStaticMarkup(<AgentThreadView thread={thread} />);
}

describe("AgentThreadView", () => {
  it("uses Tailwind-scanned style mapping instead of a CSS module", () => {
    const componentSource = readFileSync(resolve(import.meta.dirname, "AgentThreadView.tsx"), "utf8");
    const tailwindEntry = readFileSync(resolve(import.meta.dirname, "../design/tailwind.css"), "utf8");

    expect(componentSource).toContain('from "./AgentThreadView.styles"');
    expect(componentSource).not.toContain(".module.css");
    expect(tailwindEntry).toContain('@source "../agent-thread/**/*.{ts,tsx}";');
  });

  it("renders thread messages and parts in model order", () => {
    const html = renderThread({
      id: "thread-1",
      source: { kind: "session", id: "session-1" },
      status: "streaming",
      messages: [
        {
          id: "user-1",
          role: "user",
          createdAt: "2026-07-02T08:00:00Z",
          streaming: false,
          source: { kind: "conversation-message", id: "user-1" },
          parts: [
            {
              id: "user-1-text",
              type: "text",
              channel: "user",
              text: "请检查当前实现",
            },
          ],
        },
        {
          id: "assistant-1",
          role: "assistant",
          createdAt: "2026-07-02T08:00:01Z",
          streaming: true,
          turnId: "turn-1",
          source: { kind: "conversation-message", id: "assistant-1" },
          parts: [
            {
              id: "assistant-1-status",
              type: "runtime-event",
              kind: "status",
              name: "model_request",
              status: "running",
              summary: "正在请求模型",
            },
            {
              id: "assistant-1-tool",
              type: "tool-call",
              name: "read_file_tool",
              status: "done",
              summary: "读取 ConversationView",
              resultPreview: "export function ConversationView",
            },
            {
              id: "assistant-1-text",
              type: "text",
              channel: "answer",
              text: "已经完成第一层 adapter",
            },
          ],
        },
      ],
    });

    expect(html).toContain('data-agent-thread-id="thread-1"');
    expect(html).toContain('data-agent-thread-status="streaming"');
    expect(html).toContain('data-agent-message-role="user"');
    expect(html).toContain('data-agent-message-role="assistant"');
    expect(html.indexOf("正在请求模型")).toBeLessThan(html.indexOf("read_file_tool"));
    expect(html.indexOf("read_file_tool")).toBeLessThan(html.indexOf("已经完成第一层 adapter"));
    expect(html).toContain('data-agent-part-type="tool-call"');
    expect(html).toContain("export function ConversationView");
  });

  it("renders attachment and reference parts without flattening them into text", () => {
    const html = renderThread({
      id: "thread-attachments",
      source: { kind: "session", id: "session-2" },
      status: "idle",
      messages: [
        {
          id: "user-with-context",
          role: "user",
          createdAt: "2026-07-02T08:05:00Z",
          streaming: false,
          source: { kind: "conversation-message", id: "user-with-context" },
          parts: [
            {
              id: "attachment-1",
              type: "attachment",
              attachment: {
                artifactId: "artifact-1",
                filename: "screen.png",
                url: "/artifacts/screen.png",
                imageUrl: "/artifacts/screen.png",
                downloadUrl: "/download/screen.png",
                contentType: "image/png",
                sizeBytes: 1024,
                kind: "image",
                status: "ready",
              },
            },
            {
              id: "reference-1",
              type: "reference",
              reference: {
                kind: "session",
                sessionId: "session-ref",
                title: "历史会话",
                agentDisplayName: "分析 Agent",
              },
            },
          ],
        },
      ],
    });

    expect(html).toContain('data-agent-part-type="attachment"');
    expect(html).toContain("screen.png");
    expect(html).toContain('data-agent-part-type="reference"');
    expect(html).toContain("历史会话");
    expect(html).toContain("分析 Agent");
  });

  it("renders message parts through stable process, content, and context sections", () => {
    const html = renderThread({
      id: "thread-sections",
      source: { kind: "session", id: "session-3" },
      status: "streaming",
      messages: [
        {
          id: "assistant-sections",
          role: "assistant",
          createdAt: "2026-07-02T08:10:00Z",
          streaming: true,
          source: { kind: "conversation-message", id: "assistant-sections" },
          parts: [
            {
              id: "assistant-sections-status",
              type: "runtime-event",
              kind: "status",
              name: "model_request",
              status: "running",
              summary: "正在请求模型",
            },
            {
              id: "assistant-sections-tool",
              type: "tool-call",
              name: "read_file_tool",
              status: "done",
              summary: "读取 agent-thread",
            },
            {
              id: "assistant-sections-text",
              type: "text",
              channel: "answer",
              text: "section 渲染完成",
            },
            {
              id: "assistant-sections-reference",
              type: "reference",
              reference: {
                kind: "session",
                sessionId: "session-ref",
                title: "历史会话",
              },
            },
          ],
        },
      ],
    });

    expect(html).toContain('data-agent-section-kind="process"');
    expect(html).toContain('data-agent-section-kind="content"');
    expect(html).toContain('data-agent-section-kind="context"');
    expect(html.indexOf('data-agent-section-kind="process"')).toBeLessThan(html.indexOf("section 渲染完成"));
    expect(html.indexOf("section 渲染完成")).toBeLessThan(html.indexOf("历史会话"));
  });
});
