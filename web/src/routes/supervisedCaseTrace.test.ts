import { describe, expect, it } from "vitest";

import { buildSupervisedCaseTraceItems } from "./supervisedCaseTrace";

const labels = {
  input: "当前 case 输入",
  thought: "思考过程",
  tool: "工具调用",
  assistant: "回答",
  error: "错误 / 恢复",
  raw: "内容",
  state: "状态",
};

describe("supervised case trace formatting", () => {
  it("formats state blocks as structured rows", () => {
    const items = buildSupervisedCaseTraceItems(
      [
        {
          timestamp: "2026-06-01T11:56:04",
          kind: "assistant",
          label: "assistant",
          content: '<state>{"mood":"专注","feeling":"正在分析","whisper":"先读测试"}</state>',
        },
      ],
      labels,
    );

    expect(items[0].tone).toBe("assistant");
    expect(items[0].defaultOpen).toBe(true);
    expect(items[0].sections[0]).toMatchObject({
      kind: "state",
      rows: [
        { label: "mood", value: "专注" },
        { label: "feeling", value: "正在分析" },
        { label: "whisper", value: "先读测试" },
      ],
    });
  });

  it("formats tool json as pretty json and keeps tools collapsed by default", () => {
    const items = buildSupervisedCaseTraceItems(
      [
        {
          timestamp: "2026-06-01T11:56:17",
          kind: "tool",
          label: "cli_tool",
          content: '{"ok":true,"path":"C:/repo/app.py"}',
          status: "success",
        },
      ],
      labels,
    );

    expect(items[0]).toMatchObject({
      tone: "tool",
      title: "cli_tool",
      defaultOpen: false,
      status: "success",
    });
    expect(items[0].sections[0]).toMatchObject({
      kind: "json",
      content: '{\n  "ok": true,\n  "path": "C:/repo/app.py"\n}',
    });
  });

  it("preserves chronological order so the timeline can keep newest items at the bottom", () => {
    const items = buildSupervisedCaseTraceItems(
      [
        {
          timestamp: "2026-06-01T11:56:04",
          kind: "input",
          label: "prompt",
          content: "先读取任务。",
        },
        {
          timestamp: "2026-06-01T11:56:17",
          kind: "tool",
          label: "cli_tool",
          content: '{"cmd":"pytest"}',
          status: "success",
        },
        {
          timestamp: "2026-06-01T11:56:31",
          kind: "assistant",
          label: "assistant",
          content: "完成这一轮 case。",
        },
      ],
      labels,
    );

    expect(items.map((item) => item.timestamp)).toEqual([
      "2026-06-01T11:56:04",
      "2026-06-01T11:56:17",
      "2026-06-01T11:56:31",
    ]);
    expect(items.at(-1)?.preview).toBe("完成这一轮 case。");
  });
});
