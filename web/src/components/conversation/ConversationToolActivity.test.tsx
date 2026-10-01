import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationToolActivity } from "./ConversationToolActivity";
import styles from "./ConversationToolActivity.styles";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { createCodexTranscriptToolActivity } from "./conversationToolActivityModel";
import { conversationSubagentColorBucket } from "./conversationSubagentColor";

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

function namedToolCell(id: string, rawToolName: string, summary = "已完成"): CodexTranscriptCell {
  const cell = toolCell(id, summary);
  cell.title = rawToolName;
  return cell;
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
    // 3+ completed tools can use a Codex-style group summary, but stay open by default
    // so the chrono tool trail remains visible after the turn settles/stops.
    expect(html).toContain('data-codex-tool-activity-group="true"');
    expect(html).toContain("运行了 3 个工具");
    expect(html).toMatch(/open(?:="")?/);
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
    expect(styles.itemBody).toContain("text-vui-xs");
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

  it("keeps tool details expandable with a small inline disclosure chevron", () => {
    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([toolCell("tool-1", "定位 ConversationLogger")])}
        language="zh"
        renderToolDetails={() => <pre>工具原始结果</pre>}
      />,
    );

    expect(html).toContain('data-codex-tool-detail="true"');
    expect(html).toContain("工具原始结果");
    expect(html).toContain('data-codex-tool-detail-toggle="inline-symbol"');
    expect(html).toContain("itemChevron");
    expect(html).not.toContain("执行完成");
    expect(styles.itemSummary).toContain("cursor-pointer");
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

  it("makes a failed web-fetch row expandable even when the renderer returns no extra body", () => {
    const cell = toolCell("web-failed", "HTTP 406: https://elifesciences.org/articles/13810");
    cell.kind = "error_notice";
    cell.status = "failed";
    cell.tone = "error";
    cell.title = "web_fetch_tool";
    cell.operationIds = ["op-1"];

    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([cell])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );

    expect(html).toContain('data-codex-tool-detail="true"');
    expect(html).toContain('data-codex-tool-detail-toggle="inline-symbol"');
    expect(html).toContain("无更多详情");
    expect(html).not.toContain("itemStatic");
  });

  it("renders no detail toggle when the cell has nothing to expand", () => {
    const cell = toolCell("tool-empty-detail", "运行测试");

    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([cell])}
        language="zh"
        renderToolDetails={() => null}
        toolDetailIsEmpty={() => true}
      />,
    );

    expect(html).toContain('data-codex-tool-detail="none"');
    expect(html).not.toContain("无更多详情");
    expect(html).not.toContain('data-codex-tool-detail-toggle="inline-symbol"');
    // The static wrapper must stay a single flex line: Tailwind preflight
    // renders the leading lucide <svg> as display:block, so a plain block
    // wrapper pushes the icon onto its own line above the action/subject.
    const staticRow = openingTagContaining(html, 'data-codex-tool-detail="none"');
    expect(staticRow).toContain("flex");
    expect(staticRow).toContain("items-center");
    expect(staticRow).not.toContain("cursor-pointer");
    expect(styles.itemStatic).toContain("flex");
    expect(styles.itemStatic).toContain("items-center");
  });

  it("keeps the running tool row collapsed with a shimmering action word and a static icon", () => {
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
    // Default collapsed: running rows no longer open themselves.
    expect(openingTagContaining(html, 'data-codex-tool-detail="true"')).not.toContain("open");
    // Running lives in the action word's shimmer, not a spinning icon.
    expect(html).toContain('data-codex-tool-action-running="true"');
    expect(html).toContain("actionLabelRunning");
    expect(html).not.toContain("animate-spin");
  });

  it("carries failure semantics via a dashed status word with a hover tooltip, not a red blast", () => {
    const failedCell = toolCell("tool-failed", "HTTP 406: https://elifesciences.org/articles/13810");
    failedCell.status = "failed";
    failedCell.tone = "error";

    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([failedCell])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );

    // Status word keeps its color + dashed underline and reveals the error on
    // hover via VTooltip (idle trigger slot markers replace the native title).
    expect(html).toContain('data-codex-tool-status-pill="true"');
    expect(html).toContain('data-codex-tool-status-kind="failed"');
    expect(html).toContain('data-codex-tool-status-kind="failed" data-slot="tooltip-trigger"');
    // The expanded body (SSR keeps it mounted) keeps the full error + a copy affordance.
    expect(html).toContain('data-codex-tool-failure-copy="true"');
    expect(html).toContain("复制错误详情");
    // Leading icon stays muted (no red).
    expect(html).toContain("itemIconFailed");
    expect(styles.statusLabel).toContain("underline");
    expect(styles.statusLabel).toContain("decoration-dashed");
  });

  it("encodes the running shimmer in CSS with a reduced-motion static fallback", () => {
    expect(styles.actionLabelRunning).toContain("inline-block");
    expect(activityCss).toContain("@keyframes vui-tool-activity-shimmer");
    expect(activityCss).toContain(".vui-components-conversation-tool-activity.actionLabelRunning");
    expect(activityCss).toContain("background-clip: text");
    // Reduced motion: no sweep, static tinted word instead.
    const shimmerIndex = activityCss.indexOf(".vui-components-conversation-tool-activity.actionLabelRunning");
    const reducedBlock = activityCss.slice(activityCss.indexOf("prefers-reduced-motion", shimmerIndex));
    expect(reducedBlock).toContain(".vui-components-conversation-tool-activity.actionLabelRunning");
    expect(reducedBlock).toContain("animation: none");
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

  it("wraps two distinct explore runs in one anchored category group (ZCode Explore)", () => {
    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([
          namedToolCell("read-cat-1", "read_file_tool"),
          namedToolCell("grep-cat-1", "grep_search_tool"),
        ])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );

    expect(html).toContain('data-codex-tool-activity-category-group="true"');
    expect(html).toContain('data-codex-tool-category="explore"');
    expect(html).toContain('data-conversation-part-key="tool-category-group:read-cat-1"');
    expect(summaryContaining(html, "探索")).toContain("· 2 次");
    // Both children stay visible (name-level rows/batches inside the category pass).
    expect(html.match(/data-codex-tool-activity-item="true"/g)).toHaveLength(2);
    // A single explore tool never gains a parent wrapper.
    const single = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([namedToolCell("read-solo", "read_file_tool")])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );
    expect(single).not.toContain('data-codex-tool-activity-category-group="true"');
  });

  it("keeps the category group anchored while more same-category children stream in", () => {
    const render = (ids: string[]) => renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity(ids.map((id) => namedToolCell(
          id,
          id.startsWith("grep") ? "grep_search_tool" : "read_file_tool",
        )))}
        language="zh"
        renderToolDetails={() => null}
      />,
    );
    const two = render(["read-grow-1", "grep-grow-1"]);
    const three = render(["read-grow-1", "grep-grow-1", "read-grow-2"]);
    const key = 'data-conversation-part-key="tool-category-group:read-grow-1"';
    expect(two).toContain(key);
    expect(three).toContain(key);
    expect(three).toContain('data-codex-tool-activity-count="3"');
  });

  it("aggregates child states on the category row: running shimmers, failure summarizes", () => {
    const runningChild = namedToolCell("grep-run-1", "grep_search_tool", "正在搜索");
    runningChild.status = "running";
    runningChild.tone = "running";
    const runningHtml = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([
          namedToolCell("read-run-1", "read_file_tool"),
          runningChild,
        ])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );
    const groupSummary = summaryContaining(runningHtml, "探索");
    expect(groupSummary).toContain('data-codex-tool-action-running="true"');
    expect(groupSummary).toContain("actionLabelRunning");
    expect(runningHtml).toContain('aria-live="polite"');

    const failedCell = namedToolCell("grep-fail-1", "grep_search_tool", "HTTP 406: https://example.com/a");
    failedCell.status = "failed";
    failedCell.tone = "error";
    const failedHtml = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([
          namedToolCell("read-fail-1", "read_file_tool"),
          failedCell,
        ])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );
    const failedSummary = summaryContaining(failedHtml, "探索");
    expect(failedSummary).toContain("1 项需关注");
    expect(failedSummary).toContain('data-codex-tool-status-kind="failed"');
    expect(failedSummary).toContain('data-codex-tool-status-kind="failed" data-slot="tooltip-trigger"');
  });

  it("renders the subagent spawn row with a stable token-derived colored name", () => {
    const cell = namedToolCell("spawn-color-1", "spawn_agent_tool", "");
    cell.toolArguments = { task_type: "research" };
    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([cell])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );

    expect(html).toContain("派生代理");
    expect(html).toContain('data-codex-tool-agent-name="true"');
    // The agent name replaces the generic subject and carries its bucket accent.
    expect(html).toContain(">research</span>");
    const bucket = conversationSubagentColorBucket("research");
    expect(html).toContain(
      `--subagent-accent:hsl(from var(--accent-cool) calc(h + ${bucket * 45}deg) s l)`,
    );
    // Colors never become literals; the chip derives from the theme token.
    expect(html).not.toMatch(/#[0-9a-fA-F]{3,8}[";]/);
    expect(styles.agentNameChip).toContain("inline-flex");
    expect(activityCss).toContain(".vui-components-conversation-tool-activity.agentNameChip");
    expect(activityCss).toContain("var(--subagent-accent, var(--fg-tertiary))");
    expect(activityCss).toContain("color-mix(in srgb, var(--subagent-accent, var(--fg-tertiary)) 14%, transparent)");
  });

  it("tags agent spawn rows with the neutral 子代理 source badge without touching the name bucket", () => {
    const cell = namedToolCell("spawn-badge-1", "spawn_agent_tool", "");
    cell.toolArguments = { task_type: "research" };
    const html = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([cell])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );

    expect(html).toContain('data-codex-tool-agent-badge="true"');
    expect(html).toContain(">子代理</span>");
    // The badge is a quiet grey tag: it must not absorb the name's accent variable.
    expect(styles.agentSourceBadge).toContain("text-[var(--fg-tertiary)]");
    expect(styles.agentSourceBadge).not.toContain("--subagent-accent");

    const enHtml = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([cell])}
        language="en"
        renderToolDetails={() => null}
      />,
    );
    expect(enHtml).toContain(">Agent</span>");

    // Non-agent rows stay badge-free.
    const plainHtml = renderToStaticMarkup(
      <ConversationToolActivity
        activity={createCodexTranscriptToolActivity([namedToolCell("read-badge-1", "read_file_tool")])}
        language="zh"
        renderToolDetails={() => null}
      />,
    );
    expect(plainHtml).not.toContain('data-codex-tool-agent-badge="true"');
  });

  it("keeps category group chrome on the shared quiet-row contract", () => {
    expect(styles.categoryGroupSummary).toContain("list-none");
    expect(styles.categoryGroupSummary).toContain("[&::marker]:content-none");
    expect(styles.categoryGroupSummary).toContain("items-center");
    expect(styles.categoryGroupDetailsInner).toContain("pl-1");
    expect(styles.categoryGroupDetails).not.toContain("border-l");
    expect(styles.agentNameChip).not.toContain("rounded-full");
    expect(activityCss).toContain(".vui-components-conversation-tool-activity.categoryGroup:not([open])");
    expect(activityCss).toContain("> .vui-components-conversation-tool-activity.categoryGroupDetails");
    expect(activityCss).toContain(".vui-components-conversation-tool-activity.categoryGroup[open]");
    const groupAnimIndex = activityCss.indexOf(".vui-components-conversation-tool-activity.categoryGroup[open]");
    const reducedBlock = activityCss.indexOf("prefers-reduced-motion", groupAnimIndex);
    expect(reducedBlock).toBeGreaterThan(-1);
  });
});
