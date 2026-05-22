import { describe, expect, it } from "vitest";

import {
  buildVisiblePanelRows,
  getPetAvatarPresetKey,
  getPetAvatarSymbol,
  isLowValuePanelText,
} from "./chatCompactPanel";

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

  it("derives compact pet avatar symbols from preset or pet name", () => {
    expect(getPetAvatarSymbol("cat", "Mika")).toBe("CAT");
    expect(getPetAvatarSymbol(" PENGUIN ", "Mika")).toBe("PNG");
    expect(getPetAvatarSymbol("custom", "小鱼")).toBe("小鱼");
    expect(getPetAvatarSymbol(undefined, "")).toBe("PET");
  });

  it("normalizes pet avatar preset keys for the showcase skin", () => {
    expect(getPetAvatarPresetKey(" Moose ")).toBe("moose");
    expect(getPetAvatarPresetKey("")).toBe("default");
    expect(getPetAvatarPresetKey(undefined)).toBe("default");
  });
});
