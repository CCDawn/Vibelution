import { describe, expect, it } from "vitest";

import { buildVisiblePanelRows, isLowValuePanelText } from "./chatCompactPanel";

describe("chatCompactPanel", () => {
  it("hides empty and workspace-only rows", () => {
    expect(isLowValuePanelText("")).toBe(true);
    expect(isLowValuePanelText("workspace")).toBe(true);
    expect(isLowValuePanelText("收到")).toBe(false);
  });

  it("filters configured low-value placeholder labels", () => {
    const rows = buildVisiblePanelRows(
      [
        { label: "文件上下文", value: "workspace" },
        { label: "当前任务", value: "正在准备 shell" },
        { label: "当前任务", value: "审查最新日志" },
      ],
      ["正在准备 shell"],
    );

    expect(rows).toEqual([{ label: "当前任务", value: "审查最新日志", title: undefined }]);
  });
});
