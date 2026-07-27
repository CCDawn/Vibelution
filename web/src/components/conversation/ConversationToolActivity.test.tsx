import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationToolActivity } from "./ConversationToolActivity";
import styles from "./ConversationToolActivity.styles";
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

  it("folds a long same-tool run into one in-place batch while preserving its details", () => {
    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([
          toolCell("tool-1", "已完成"),
          toolCell("tool-2", "已完成"),
          toolCell("tool-3", "已完成"),
          toolCell("tool-4", "已完成"),
        ])}
        language="zh"
        renderToolDetails={(cell) => <pre>{`详情 ${cell.id}`}</pre>}
      />,
    );

    expect(html).toContain('data-codex-tool-activity-batch="true"');
    expect(html.match(/data-codex-tool-activity-item="true"/g)).toHaveLength(4);
    expect(html).toContain('data-codex-tool-activity-count="4"');
    expect(html).toContain(">· 4 次</span>");
    expect(html).toContain("详情 tool-1");
    expect(html).toContain("详情 tool-4");
  });

  it("keeps tool details expandable with one compact disclosure chevron", () => {
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
    expect(html).toContain("itemChevron");
    expect(html.indexOf("itemChevron")).toBeGreaterThan(html.indexOf("itemTitle"));
    expect(styles.itemSummary).toContain("grid-cols-[17px_minmax(0,1fr)]");
    expect(styles.itemSummary).not.toContain("grid-cols-[17px_minmax(0,1fr)_16px]");
    expect(styles.batchSummary).toContain("grid-cols-[17px_minmax(0,1fr)]");
  });

  it("uses a semantic code result as the row title without repeating the generic tool name", () => {
    const cell = toolCell("tool-code-search", "");
    cell.toolLifecycleModel = {
      toolCalls: [
        {
          toolCallId: "tool-call-code-search",
          rawOperationId: "tool-code-search",
          status: "completed",
          title: "code_symbol_tool",
          rawToolName: "code_symbol_tool",
          runtimeKind: "tool",
          resultPreview: JSON.stringify({
            status: "ok",
            mode: "search",
            query: "savedDraft",
            count: 4,
            results: [],
          }),
        },
      ],
      terminalOperations: [],
      terminalSessions: [],
      modelObservations: [],
    };

    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([cell])}
        language="zh"
        renderToolDetails={() => <pre>183 savedDraft</pre>}
      />,
    );

    expect(html).toContain("搜索 savedDraft · 4 个结果");
    expect(html).not.toContain(">代码图谱<");
  });
});
