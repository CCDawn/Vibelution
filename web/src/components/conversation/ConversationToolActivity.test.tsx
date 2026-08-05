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
      terminalOperations: [
        {
          operationId: "terminal_operation:done",
          toolCallId: "terminal-completed",
          terminalId: "terminal:sandbox-1",
          kind: "ExecCommand",
          status: "completed",
          request: { displayCommand: "type README.md", cwd: "" },
          result: { exitCode: 0, formattedOutput: "# Vibelution Development Standard" },
          durationSeconds: 1.2,
          rawOperationId: "terminal-completed",
        },
      ],
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

    expect(html).toContain('data-codex-tool-activity="items"');
    expect(html).not.toContain("运行了 1 个工具");
    // Codex quiet row: plain action + muted subject/duration; completed status is icon-only.
    expect(html).toContain('data-codex-tool-action-pill="true"');
    expect(html).toContain("执行命令");
    expect(html).toContain('data-codex-tool-status-kind="completed"');
    expect(html).not.toContain('data-codex-tool-status-pill="true"');
    expect(html).not.toContain("执行完成");
    expect(html).not.toContain("rounded-full");
    // completed shell row keeps command as subject, not a prose "已在 … 内运行" line
    expect(html).toContain("type README.md");
    expect(html).toContain("1.2s");
    expect(html).not.toContain("已在 1.2s 内运行 type README.md");
    expect(html).not.toContain("# Vibelution Development Standard");
    expect(html).not.toContain(">running<");
  });

  it("shows a meaningful nonzero terminal exit inline without an extra digest row", () => {
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

    expect(html).toContain('data-codex-tool-activity="items"');
    expect(html).toContain('data-codex-tool-activity-state="attention"');
    expect(html).not.toContain("Ran 1 tool");
    expect(html).not.toContain("1 item needs attention");
    // Nonzero exit uses attention status pill (Codex: no spinner).
    expect(html).toContain("Run command");
    expect(html).toContain("Non-zero exit");
    expect(html).toContain('data-codex-tool-status-kind="attention"');
    expect(html).toContain("itemIcon");
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

    expect(html).toContain('data-codex-tool-activity="items"');
    expect(html).not.toContain("运行了 1 个工具");
    expect(html).not.toContain("项需关注");
    expect(html).toContain("执行命令");
    expect(html).toContain("无匹配");
    expect(html).toContain('data-codex-tool-status-kind="attention"');
    expect(html).not.toContain("命令退出 1");
  });

  it("renders one contiguous activity as direct compact rows", () => {
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

    expect(html).toContain('data-codex-tool-activity="items"');
    expect(html).toContain('data-codex-tool-activity-rail="true"');
    // 3+ completed tools collapse under a Codex-style group summary.
    expect(html).toContain('data-codex-tool-activity-group="true"');
    expect(html).toContain("运行了 3 个工具");
    expect(html).toContain('data-codex-tool-activity-batch="true"');
    expect(html).toContain('data-codex-tool-activity-count="3"');
    expect(html.match(/data-codex-tool-activity-item="true"/g)).toHaveLength(3);
    expect(html).toContain("代码分析");
    expect(html).toContain("定位 ConversationLogger");
    // Raw JSON protocol noise must not become the human subject line.
    expect(html).not.toMatch(/代码图谱 · \{&quot;status&quot;/);
  });

  it("keeps Codex-style tool rail without horizontal frame lines, capped height, and plain-text chrome", () => {
    expect(styles.activity).toContain("border-0");
    expect(styles.activity).not.toContain("border-y");
    expect(styles.activity).toContain("max-h-[min(18rem,42vh)]");
    expect(styles.activity).toContain("overflow-y-auto");
    expect(styles.itemBody).toContain("text-[var(--fg-tertiary)]");
    expect(styles.itemBody).toContain("[font-size:var(--vui-font-xs)]");
    expect(styles.itemBody).toContain("items-center");
    expect(styles.actionLabel).toContain("font-medium");
    expect(styles.actionLabel).not.toContain("rounded-full");
    expect(styles.actionPill).not.toContain("rounded-full");
    expect(styles.statusPill).not.toContain("rounded-full");
    expect(styles.itemPreview).toContain("text-[color-mix(in_srgb,var(--fg-tertiary)");
  });

  it("keeps a small activity on the same direct-row contract", () => {
    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([toolCell("tool-1", "已完成")])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );

    expect(html).toContain('data-codex-tool-activity="items"');
    expect(html).not.toContain("运行了 1 个工具");
    expect(html).not.toContain('data-codex-tool-activity-group="true"');
    expect(html).toContain("代码图谱");
    expect(html).not.toContain("执行完成");
    expect(html).toContain('data-codex-tool-status-kind="completed"');
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

  it("keeps tool details expandable without a far-edge disclosure chevron", () => {
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
    expect(html).not.toContain("执行完成");
    expect(html).not.toContain("itemChevron");
    expect(styles.itemSummary).toContain("w-full");
    expect(styles.itemSummary).toContain("max-w-full");
    expect(styles.itemSummary).toContain("items-center");
    expect(styles.itemSummary).toContain("list-none");
    expect(styles.itemSummary).toContain("[&::marker]:content-none");
    expect(styles.itemSummary).not.toContain("grid-cols-[17px_minmax(0,1fr)_16px]");
    expect(styles.batchSummary).toContain("items-center");
    expect(styles.batchSummary).toContain("list-none");
    expect(activityCss).toContain(".vui-components-conversation-tool-activity.batch:not([open])");
    expect(activityCss).toContain(".vui-components-conversation-tool-activity.itemDetails:not([open])");
    expect(activityCss).toContain("> .vui-components-conversation-tool-activity.batchDetails");
    expect(activityCss).toContain("> .vui-components-conversation-tool-activity.itemDetailsBody");
    expect(activityCss).toContain("::-webkit-details-marker");
    expect(activityCss).toContain("::marker");
    expect(styles.activity).toContain("w-full");
    expect(styles.activity).toContain("max-w-full");
    expect(styles.activity).toContain("max-h-[min(18rem,42vh)]");
    expect(styles.activity).not.toContain("ml-");
    expect(styles.batchDetails).not.toContain("border-l");
    expect(styles.batchDetails).not.toContain("ml-");
    expect(styles.itemDetailsBody).toContain("max-h-48");
    expect(styles.itemDetailsBody).not.toContain("ml-");
  });

  it("opens the current running tool detail directly by default", () => {
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
    expect(html).toContain('data-codex-tool-activity-state="running"');
    expect(html).not.toContain("正在运行工具");
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

    // Plain action keeps the tool family; semantic search lands in muted subject.
    expect(html).toContain("代码图谱");
    expect(html).not.toContain("执行完成");
    expect(html).toContain("搜索 savedDraft · 4 个结果");
    expect(html).toContain('data-codex-tool-subject="true"');
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

    // Multi-tool completed trails use a Codex group summary, but product labels stay inside.
    expect(html).toContain('data-codex-tool-activity-group="true"');
    expect(html).toContain("运行了 8 个工具");
    expect(html).not.toContain("工具调用 8");
    expect(html).toContain("读取资料上下文");
    expect(html).toContain("网页读取");
    expect(html).toContain("资料阶段写回");
    expect(html).not.toContain("web_fetch_tool");
    expect(html).toContain("lucide-file-search");
    expect(html).toContain("lucide-pencil-line");
  });
});
