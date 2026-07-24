import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationToolActivity } from "./ConversationToolActivity";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { createCodexTranscriptToolActivity } from "./conversationToolActivityModel";

function toolCell(id: string, summary: string): CodexTranscriptCell {
  return {
    id,
    kind: "tool_call",
    messageId: "message-1",
    status: "completed",
    tone: "neutral",
    title: "code_symbol_tool",
    summary,
  };
}

describe("ConversationToolActivity", () => {
  it("keeps a long sequence as flat Codex-style tool rows", () => {
    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([
          toolCell("tool-1", '{"status":"ok",'),
          toolCell("tool-2", '{"status":"ok",'),
          toolCell("tool-3", "定位 ConversationLogger"),
        ])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );

    expect(html).toContain('data-codex-tool-activity="inline"');
    expect(html.match(/data-codex-tool-activity-item="true"/g)).toHaveLength(3);
    expect(html).not.toContain('data-codex-tool-activity-group="true"');
    expect(html).toContain("代码图谱");
    expect(html).not.toContain("3 次调用");
    expect(html).toContain("定位 ConversationLogger");
    expect(html).not.toContain('{&quot;status&quot;:&quot;ok&quot;,');
  });

  it("keeps a small activity as compact rows instead of a nested group", () => {
    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([toolCell("tool-1", "已完成")])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );

    expect(html).toContain('data-codex-tool-activity="inline"');
    expect(html).not.toContain('data-codex-tool-activity-group="true"');
    expect(html).toContain("代码图谱");
  });

  it("keeps tool details expandable without a right-side status or chevron", () => {
    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([toolCell("tool-1", "定位 ConversationLogger")])}
        language="zh"
        renderToolDetails={() => <pre>工具原始结果</pre>}
      />,
    );

    expect(html).toContain('data-codex-tool-detail="true"');
    expect(html).toContain("工具原始结果");
    expect(html).not.toContain('data-codex-tool-detail-toggle="inline-symbol"');
    expect(html).not.toContain("完成");
  });
});
