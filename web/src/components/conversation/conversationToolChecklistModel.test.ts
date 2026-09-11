import { describe, expect, it } from "vitest";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { conversationToolChecklistModel } from "./conversationToolChecklistModel";

function toolCell(overrides: Partial<CodexTranscriptCell> = {}): CodexTranscriptCell {
  return {
    id: "cell-1",
    kind: "tool_call",
    messageId: "message-1",
    status: "completed",
    tone: "neutral",
    title: "plan_update_tool",
    ...overrides,
  };
}

describe("conversationToolChecklistModel", () => {
  it("projects plan_update_tool input onto a step checklist", () => {
    const model = conversationToolChecklistModel(toolCell({
      toolArguments: {
        plan: [
          { step: "审查工具契约", status: "completed" },
          { step: "补齐回归测试", status: "in_progress" },
          { step: "运行完整验证", status: "pending" },
        ],
        explanation: "同步当前对齐进度",
      },
    }), "zh");

    expect(model).not.toBeNull();
    expect(model?.toolName).toBe("plan_update_tool");
    expect(model?.title).toBe("计划");
    expect(model?.explanation).toBe("同步当前对齐进度");
    expect(model?.completedCount).toBe(1);
    expect(model?.items.map((item) => [item.label, item.status])).toEqual([
      ["审查工具契约", "completed"],
      ["补齐回归测试", "in_progress"],
      ["运行完整验证", "pending"],
    ]);
  });

  it("tolerates plan status aliases and a JSON-string plan", () => {
    const model = conversationToolChecklistModel(toolCell({
      toolArguments: {
        plan: JSON.stringify([
          { step: "已完成项", status: "done" },
          { step: "进行项", status: "running" },
          { step: "未知项", status: "waiting" },
        ]),
      },
    }), "en");

    expect(model?.title).toBe("Plan");
    expect(model?.items.map((item) => item.status)).toEqual([
      "completed",
      "in_progress",
      "pending",
    ]);
  });

  it("projects task_create_tool input onto a pending task checklist", () => {
    const model = conversationToolChecklistModel(toolCell({
      title: "task_create_tool",
      toolArguments: {
        task_list: [
          { description: "复现缺陷" },
          { description: "修复持久化判定" },
        ],
        goal: "修复错误卡常驻",
      },
    }), "zh");

    expect(model?.toolName).toBe("task_create_tool");
    expect(model?.title).toBe("修复错误卡常驻");
    expect(model?.completedCount).toBe(0);
    expect(model?.items.map((item) => [item.label, item.status])).toEqual([
      ["复现缺陷", "pending"],
      ["修复持久化判定", "pending"],
    ]);
  });

  it("falls back to the language default task title when no goal is present", () => {
    const model = conversationToolChecklistModel(toolCell({
      title: "task_create_tool",
      toolArguments: { task_list: ["复现缺陷"] },
    }), "zh");

    expect(model?.title).toBe("任务清单");
    expect(model?.items).toEqual([
      { id: "checklist-item-0", label: "复现缺陷", status: "pending" },
    ]);
  });

  it("recognizes the human-facing semantic alias already projected on the cell", () => {
    const model = conversationToolChecklistModel(toolCell({
      title: "创建任务",
      toolArguments: { task_list: [{ description: "复现缺陷" }] },
    }), "zh");

    expect(model?.toolName).toBe("task_create_tool");
    expect(model?.items.map((item) => item.label)).toEqual(["复现缺陷"]);
  });

  it("keeps generic rendering for other tools, failures and unparseable input", () => {
    expect(conversationToolChecklistModel(toolCell({
      title: "read_file_tool",
      toolArguments: { path: "web/src/app.ts" },
    }), "zh")).toBeNull();

    expect(conversationToolChecklistModel(toolCell({
      status: "failed",
      tone: "error",
      toolArguments: { plan: [{ step: "步骤", status: "pending" }] },
    }), "zh")).toBeNull();

    expect(conversationToolChecklistModel(toolCell({
      toolArguments: { plan: [] },
    }), "zh")).toBeNull();

    expect(conversationToolChecklistModel(toolCell({
      toolArguments: {},
    }), "zh")).toBeNull();
  });
});
