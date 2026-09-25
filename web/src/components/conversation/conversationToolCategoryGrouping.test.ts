import { describe, expect, it } from "vitest";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  buildConversationToolCategoryGroups,
  conversationToolPersistKey,
  type ConversationToolCategorizedItem,
} from "./conversationToolCategoryGrouping";
import {
  buildConversationToolActivityPresentation,
} from "./conversationToolActivityPresentation";

function toolCell(
  id: string,
  rawToolName: string,
  overrides?: Partial<Pick<CodexTranscriptCell, "status" | "tone" | "title">>,
): CodexTranscriptCell {
  return {
    id,
    kind: "tool_call",
    messageId: "message-1",
    status: "completed",
    tone: "neutral",
    title: rawToolName,
    summary: "已完成",
    toolLifecycleModel: {
      toolCalls: [
        {
          toolCallId: `call-${id}`,
          rawOperationId: id,
          status: "completed",
          title: rawToolName,
          rawToolName,
          runtimeKind: "tool",
        },
      ],
      terminalOperations: [],
      terminalSessions: [],
      modelObservations: [],
    },
    ...overrides,
  };
}

function groupIds(items: readonly ConversationToolCategorizedItem[]) {
  return items.map((item) => (item.kind === "categoryGroup" ? "group" : item.kind));
}

describe("buildConversationToolCategoryGroups", () => {
  it("keeps a lone category item on its plain row (first item renders as-is)", () => {
    const items = buildConversationToolActivityPresentation(
      [toolCell("read-1", "read_file_tool")],
      "zh",
    );
    expect(buildConversationToolCategoryGroups(items, "zh")).toEqual(items);
  });

  it("keeps a single same-name batch un-wrapped (name-level run stays intact)", () => {
    const items = buildConversationToolActivityPresentation(
      [toolCell("read-1", "read_file_tool"), toolCell("read-2", "read_file_tool"), toolCell("read-3", "read_file_tool")],
      "zh",
    );
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "batch" });
    expect(buildConversationToolCategoryGroups(items, "zh")).toEqual(items);
  });

  it("escalates two distinct same-category runs into one anchored parent group", () => {
    const items = buildConversationToolActivityPresentation(
      [
        toolCell("read-1", "read_file_tool"),
        toolCell("read-2", "read_file_tool"),
        toolCell("grep-1", "grep_search_tool"),
      ],
      "zh",
    );
    expect(items.map((item) => item.kind)).toEqual(["batch", "single"]);
    const grouped = buildConversationToolCategoryGroups(items, "zh");
    expect(grouped).toHaveLength(1);
    const group = grouped[0];
    expect(group).toMatchObject({
      kind: "categoryGroup",
      category: "explore",
      title: "探索",
      count: 3,
      running: false,
      attentionCount: 0,
    });
    if (group.kind !== "categoryGroup") {
      return;
    }
    // Identity anchors to the FIRST child's persist key, with no tail/count suffix.
    const firstCell = group.items[0];
    expect(firstCell.kind).toBe("batch");
    const anchorCell = firstCell.kind === "batch" ? firstCell.cells[0] : firstCell.cell;
    expect(group.id).toBe(`tool-category-group:${conversationToolPersistKey(anchorCell)}`);
    expect(group.id).toBe("tool-category-group:call-read-1");
    expect(group.id.endsWith("grep-1")).toBe(false);
  });

  it("keeps the anchored id stable while later same-category items stream in", () => {
    const twoItems = buildConversationToolCategoryGroups(
      buildConversationToolActivityPresentation(
        [toolCell("read-1", "read_file_tool"), toolCell("grep-1", "grep_search_tool")],
        "zh",
      ),
      "zh",
    );
    const threeItems = buildConversationToolCategoryGroups(
      buildConversationToolActivityPresentation(
        [
          toolCell("read-1", "read_file_tool"),
          toolCell("grep-1", "grep_search_tool"),
          toolCell("glob-1", "glob_tool"),
        ],
        "zh",
      ),
      "zh",
    );
    if (threeItems[0]?.kind !== "categoryGroup" || twoItems[0]?.kind !== "categoryGroup") {
      return;
    }
    expect(twoItems[0].id).toBe(threeItems[0].id);
    expect(threeItems[0].count).toBe(3);
    expect(threeItems[0].items).toHaveLength(3);
  });

  it("breaks runs at category boundaries and barriers", () => {
    const items = buildConversationToolActivityPresentation(
      [
        toolCell("read-1", "read_file_tool"),
        toolCell("grep-1", "grep_search_tool"),
        toolCell("exec-1", "exec_command"),
        toolCell("glob-1", "glob_tool"),
      ],
      "zh",
    );
    const grouped = buildConversationToolCategoryGroups(items, "zh");
    expect(grouped.map((item) => item.kind)).toEqual(["categoryGroup", "single", "single"]);
    if (grouped[1]?.kind !== "single" || grouped[2]?.kind !== "single") {
      return;
    }
    expect(grouped[1].cell.id).toBe("exec-1");
    expect(grouped[2].cell.id).toBe("glob-1");
  });

  it("never groups agent rows and treats them as barriers", () => {
    const items = buildConversationToolActivityPresentation(
      [
        toolCell("spawn-1", "spawn_agent_tool"),
        toolCell("read-1", "read_file_tool"),
        toolCell("grep-1", "grep_search_tool"),
      ],
      "zh",
    );
    const grouped = buildConversationToolCategoryGroups(items, "zh");
    expect(groupIds(grouped)).toEqual(["single", "group"]);
    if (grouped[0]?.kind !== "single") {
      return;
    }
    expect(grouped[0].cell.id).toBe("spawn-1");
  });

  it("honors the ZCode switch defaults: changes grouping off, cua on", () => {
    // write_file folds at name level with apply_patch (same family); pair two
    // distinct-family changes tools so the category pass sees two items.
    const changesItems = buildConversationToolActivityPresentation(
      [
        toolCell("write-1", "write_file_tool"),
        toolCell("writeback-1", "source_collection_stage_writeback_tool"),
      ],
      "zh",
    );
    expect(changesItems.map((item) => item.kind)).toEqual(["single", "single"]);
    expect(groupIds(buildConversationToolCategoryGroups(changesItems, "zh")))
      .toEqual(["single", "single"]);
    expect(groupIds(buildConversationToolCategoryGroups(changesItems, "zh", { enableChangesGrouping: true })))
      .toEqual(["group"]);

    // Two settled computer_use calls fold at name level first; pair a settled
    // one with a running one so the category pass sees two items.
    const cuaItems = buildConversationToolActivityPresentation(
      [
        toolCell("cua-1", "computer_use"),
        toolCell("cua-2", "computer_use", { status: "running", tone: "running" }),
      ],
      "zh",
    );
    const groupedCua = buildConversationToolCategoryGroups(cuaItems, "zh");
    expect(groupedCua[0]).toMatchObject({
      kind: "categoryGroup",
      category: "cua",
      title: "浏览器操作",
      running: true,
    });
  });

  it("groups execute and changes runs when enabled, with language-specific titles", () => {
    const executeItems = buildConversationToolActivityPresentation(
      [toolCell("exec-1", "exec_command"), toolCell("lint-1", "python_lint_tool")],
      "en",
    );
    expect(buildConversationToolCategoryGroups(executeItems, "en")[0])
      .toMatchObject({ kind: "categoryGroup", category: "execute", title: "Execute" });
  });

  it("aggregates child states: running children make the group run, failures surface as attention", () => {
    const items = buildConversationToolActivityPresentation(
      [
        toolCell("read-1", "read_file_tool"),
        toolCell("grep-run", "grep_search_tool", { status: "running", tone: "running" }),
      ],
      "zh",
    );
    const grouped = buildConversationToolCategoryGroups(items, "zh");
    expect(grouped[0]).toMatchObject({ kind: "categoryGroup", running: true, attentionCount: 0 });

    const failedItems = buildConversationToolCategoryGroups(
      buildConversationToolActivityPresentation(
        [
          toolCell("grep-fail", "grep_search_tool", { status: "failed", tone: "error" }),
          toolCell("read-1", "read_file_tool"),
        ],
        "zh",
      ),
      "zh",
    );
    expect(failedItems[0]).toMatchObject({
      kind: "categoryGroup",
      running: false,
      attentionCount: 1,
      failedCount: 1,
    });
    if (failedItems[0]?.kind !== "categoryGroup") {
      return;
    }
    expect(failedItems[0].firstAttentionCell?.id).toBe("grep-fail");
  });

  it("does not count no-match terminal exits as attention", () => {
    const noMatchCell = toolCell("exec-nomatch", "exec_command");
    noMatchCell.toolLifecycleModel = {
      toolCalls: [
        {
          toolCallId: "call-exec-nomatch",
          rawOperationId: "exec-nomatch",
          status: "completed",
          title: "exec_command",
          rawToolName: "exec_command",
          runtimeKind: "terminal",
        },
      ],
      terminalOperations: [
        {
          operationId: "terminal_operation:nomatch",
          toolCallId: "call-exec-nomatch",
          terminalId: "terminal:sandbox-nomatch",
          kind: "ExecCommand",
          status: "completed",
          request: { displayCommand: "findstr /n /i missing src/x.ts", cwd: "" },
          result: { exitCode: 1, formattedOutput: "[命令执行完成，无输出]" },
          rawOperationId: "exec-nomatch",
        },
      ],
      terminalSessions: [],
      modelObservations: [],
    };
    // A same-family pair would fold into one name batch first; pair the no-match
    // command with a verification run so the category pass sees two items.
    const grouped = buildConversationToolCategoryGroups(
      buildConversationToolActivityPresentation(
        [noMatchCell, toolCell("lint-2", "python_lint_tool")],
        "zh",
      ),
      "zh",
    );
    expect(grouped[0]).toMatchObject({
      kind: "categoryGroup",
      category: "execute",
      attentionCount: 0,
      failedCount: 0,
      count: 2,
    });
  });
});
