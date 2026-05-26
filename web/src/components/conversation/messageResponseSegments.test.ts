import { describe, expect, it } from "vitest";

import { parseResponseSegments } from "./messageResponseSegments";

describe("parseResponseSegments", () => {
  it("splits codex-style responses into semantic segments", () => {
    const segments = parseResponseSegments([
      "已继续完成并提交。",
      "",
      "根因已经收口：bookkeeping 工具不算完成用户目标。",
      "",
      "已提交：",
      "",
      "8697ecf fix(chat): keep bookkeeping guard resumable",
      "",
      "验证已跑：",
      "",
      "```text",
      "101 passed, 245 deselected",
      "```",
    ].join("\n"));

    expect(segments.map((segment) => segment.kind)).toEqual([
      "status",
      "answer",
      "commit",
      "verification",
    ]);
    expect(segments[2].content).toContain("8697ecf");
    expect(segments[3]).toMatchObject({
      language: "text",
      content: "101 passed, 245 deselected",
    });
  });

  it("keeps unknown prose as a normal answer segment", () => {
    const segments = parseResponseSegments("这里是一段普通回复，没有特殊结构。");

    expect(segments).toEqual([
      {
        id: "segment-0",
        kind: "answer",
        content: "这里是一段普通回复，没有特殊结构。",
      },
    ]);
  });

  it("recognizes file and log focused blocks without changing their text", () => {
    const segments = parseResponseSegments([
      "改动文件：",
      "",
      "- web/src/components/conversation/ConversationView.tsx",
      "- web/src/components/conversation/messageResponseSegments.ts",
      "",
      "日志方面增强了 agent.tool_loop_guard.triggered。",
    ].join("\n"));

    expect(segments.map((segment) => segment.kind)).toEqual(["files", "logs"]);
    expect(segments[0].content).toContain("ConversationView.tsx");
    expect(segments[1].content).toContain("agent.tool_loop_guard.triggered");
  });
});
