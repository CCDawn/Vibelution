import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationToolActivity } from "./ConversationToolActivity";
import styles from "./ConversationToolActivity.styles";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { createCodexTranscriptToolActivity } from "./conversationToolActivityModel";

const activityCss = readFileSync(new URL("./ConversationToolActivity.css", import.meta.url), "utf8");

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

function openingTagContaining(html: string, marker: string) {
  const markerIndex = html.indexOf(marker);
  if (markerIndex < 0) {
    return "";
  }
  const tagStart = html.lastIndexOf("<", markerIndex);
  const tagEnd = html.indexOf(">", markerIndex);
  return tagStart >= 0 && tagEnd >= 0 ? html.slice(tagStart, tagEnd + 1) : "";
}

function summaryContaining(html: string, marker: string) {
  const markerIndex = html.indexOf(marker);
  if (markerIndex < 0) {
    return "";
  }
  const summaryStart = html.lastIndexOf("<summary", markerIndex);
  const summaryEnd = html.indexOf("</summary>", markerIndex);
  return summaryStart >= 0 && summaryEnd >= 0
    ? html.slice(summaryStart, summaryEnd + "</summary>".length)
    : "";
}

describe("ConversationToolActivity", () => {
  it("keeps completed terminal output out of the collapsed command row", () => {
    const cell = toolCell("terminal-completed", "");
    cell.title = "exec_command";
    cell.toolLifecycleModel = {
      toolCalls: [
        {
          toolCallId: "terminal-completed",
          rawOperationId: "terminal-completed",
          status: "completed",
          title: "exec_command",
          rawToolName: "exec_command",
          runtimeKind: "terminal",
          summary: JSON.stringify({
            status: "running",
            terminalSessionId: "sandbox-1",
            sessionOpen: true,
          }),
          resultPreview: "# Vibelution Development Standard",
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
        renderToolDetails={() => null}
      />,
    );

    expect(html).toContain('data-codex-tool-activity="digest"');
    expect(html).toContain("运行了 1 个工具");
    expect(html).toContain(">运行命令<");
    expect(html).not.toContain("# Vibelution Development Standard");
    expect(html).not.toContain(">running<");
  });

  it("opens an activity with a meaningful nonzero terminal exit as one attention digest", () => {
    const cell = toolCell("terminal-nonzero", "command failed");
    cell.title = "exec_command";
    cell.toolLifecycleModel = {
      toolCalls: [
        {
          toolCallId: "terminal-nonzero",
          rawOperationId: "terminal-nonzero",
          status: "completed",
          title: "exec_command",
          rawToolName: "exec_command",
          runtimeKind: "terminal",
          terminalOperationId: "terminal_operation:0",
        },
      ],
      terminalOperations: [
        {
          operationId: "terminal_operation:0",
          toolCallId: "terminal-nonzero",
          terminalId: "terminal:sandbox-1",
          kind: "ExecCommand",
          status: "completed",
          request: { displayCommand: "exit 1", cwd: "" },
          result: { exitCode: 1, formattedOutput: "command failed" },
          rawOperationId: "terminal-nonzero",
        },
      ],
      terminalSessions: [
        {
          terminalId: "terminal:sandbox-1",
          createdByOperationId: "terminal_operation:0",
          operationIds: ["terminal_operation:0"],
          status: "completed",
        },
      ],
      modelObservations: [],
    };

    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([cell])}
        language="en"
        renderToolDetails={() => <pre>command failed</pre>}
      />,
    );

    expect(html).toContain("Ran 1 tool");
    expect(html).toContain("1 item needs attention");
    expect(openingTagContaining(html, 'data-codex-tool-activity="digest"')).toContain('open=""');
    expect(html).toContain("Command exited 1");
    expect(html).toContain("itemIconWarning");
    expect(html).not.toContain("itemIconFailed");
  });

  it("summarizes a search exit with no output as no matches instead of a generic failure", () => {
    const cell = toolCell("terminal-no-match", "");
    cell.title = "exec_command";
    cell.toolLifecycleModel = {
      toolCalls: [
        {
          toolCallId: "terminal-no-match",
          rawOperationId: "terminal-no-match",
          status: "completed",
          title: "exec_command",
          rawToolName: "exec_command",
          runtimeKind: "terminal",
          terminalOperationId: "terminal_operation:no-match",
        },
      ],
      terminalOperations: [
        {
          operationId: "terminal_operation:no-match",
          toolCallId: "terminal-no-match",
          terminalId: "terminal:sandbox-no-match",
          kind: "ExecCommand",
          status: "completed",
          request: { displayCommand: "findstr /n /i max-w ConversationView.tsx", cwd: "" },
          result: {
            exitCode: 1,
            formattedOutput: "[WARNING | Exit Code: 1]\n[命令执行完成，无输出]",
          },
          rawOperationId: "terminal-no-match",
        },
      ],
      terminalSessions: [],
      modelObservations: [],
    };

    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([cell])}
        language="zh"
        renderToolDetails={() => <pre>技术输出</pre>}
      />,
    );

    expect(html).toContain('data-codex-tool-activity="digest"');
    expect(html).toContain("运行了 1 个工具");
    expect(html).not.toContain("项需关注");
    expect(openingTagContaining(html, 'data-codex-tool-activity="digest"')).not.toContain('open=""');
    expect(html).toContain("未找到匹配项");
    expect(html).not.toContain("命令退出 1");
  });

  it("folds one contiguous activity behind a quiet digest while preserving its tool rows", () => {
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

    expect(html).toContain('data-codex-tool-activity="digest"');
    expect(html).toContain("运行了 3 个工具");
    expect(html).toContain("代码分析 3");
    expect(openingTagContaining(html, 'data-codex-tool-activity="digest"')).not.toContain('open=""');
    expect(html).toContain('data-codex-tool-activity-batch="true"');
    expect(html).toContain('data-codex-tool-activity-count="3"');
    expect(html.match(/data-codex-tool-activity-item="true"/g)).toHaveLength(3);
    expect(html).not.toContain('data-codex-tool-activity-group="true"');
    expect(html).toContain("代码分析");
    expect(html).not.toContain("3 次调用");
    expect(html).toContain("定位 ConversationLogger");
    expect(html).not.toContain('{&quot;status&quot;:&quot;ok&quot;,');
  });

  it("keeps a small activity behind the same digest contract", () => {
    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([toolCell("tool-1", "已完成")])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );

    expect(html).toContain('data-codex-tool-activity="digest"');
    expect(html).toContain("运行了 1 个工具");
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
    expect(activityCss).toContain("transform: rotate(-90deg)");
    expect(activityCss).toContain("details[open] > summary");
    expect(activityCss).toContain("transform: rotate(0deg)");
    expect(activityCss).toContain(".vui-components-conversation-tool-activity.activity:not([open])");
    expect(activityCss).toContain(".vui-components-conversation-tool-activity.batch:not([open])");
    expect(activityCss).toContain(".vui-components-conversation-tool-activity.itemDetails:not([open])");
    expect(activityCss).toContain("> .vui-components-conversation-tool-activity.activityDetails");
    expect(activityCss).toContain("> .vui-components-conversation-tool-activity.batchDetails");
    expect(activityCss).toContain("> .vui-components-conversation-tool-activity.itemDetailsBody");
    expect(styles.activitySummary).toContain("inline-flex");
    expect(styles.activitySummary).not.toContain("justify-between");
    expect(styles.activity).not.toContain("ml-");
    expect(styles.activityChevron).not.toContain("ml-auto");
    expect(styles.activityDetails).not.toContain("border-l");
    expect(styles.activityDetails).not.toContain("ml-");
    expect(styles.itemChevron).not.toContain("rotate-");
    expect(styles.batchDetails).not.toContain("border-l");
    expect(styles.batchDetails).not.toContain("ml-");
    expect(styles.itemDetailsBody).toContain("max-h-56");
    expect(styles.itemDetailsBody).not.toContain("ml-");
  });

  it("opens the running activity and its current tool detail by default", () => {
    const runningCell = toolCell("tool-running", "正在执行");
    runningCell.status = "running";
    runningCell.tone = "running";

    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([runningCell])}
        language="zh"
        renderToolDetails={() => <pre>实时输出</pre>}
      />,
    );

    expect(html).toContain('data-codex-transcript-cell-status="running"');
    expect(html).toContain("正在运行工具");
    expect(openingTagContaining(html, 'data-codex-tool-activity="digest"')).toContain('open=""');
    expect(openingTagContaining(html, 'data-codex-tool-detail="true"')).toContain('open=""');
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

  it("renders source collection batches with product labels and semantic icons", () => {
    const cells = [
      ...Array.from({ length: 5 }, (_, index) => {
        const cell = toolCell(`context-${index}`, "已读取");
        cell.title = "source_collection_context_tool";
        return cell;
      }),
      ...Array.from({ length: 2 }, (_, index) => {
        const cell = toolCell(`fetch-${index}`, "已读取网页");
        cell.title = "web_fetch_tool";
        return cell;
      }),
      (() => {
        const cell = toolCell("writeback", "已回写");
        cell.title = "source_collection_stage_writeback_tool";
        return cell;
      })(),
    ];

    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity(cells)}
        language="zh"
        renderToolDetails={() => null}
      />,
    );

    expect(html).toContain("运行了 8 个工具");
    expect(html).not.toContain("工具调用 8");
    expect(html).toContain("读取资料上下文");
    expect(html).toContain("网页读取");
    expect(html).toContain("资料提炼回写");
    expect(html).not.toContain("web_fetch_tool");
    expect(html).toContain("lucide-file-search");
    expect(html).toContain("lucide-pencil-line");
  });
});
