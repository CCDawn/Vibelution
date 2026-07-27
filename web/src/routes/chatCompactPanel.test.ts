import { describe, expect, it } from "vitest";

import {
  buildVisiblePanelRows,
  getPetAvatarPresetKey,
  getPetAvatarSymbol,
  isLowValuePanelText,
  resolveChatResponsiveLayout,
  resolveChatUserDisplayName,
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

  it.each([
    [1440, "wide", true, true],
    [1024, "compact", true, false],
    [768, "overlay", false, false],
    [390, "mobile", false, false],
  ] as const)("resolves %ipx to %s without forcing persistent pane preferences", (width, mode, leftVisible, rightVisible) => {
    expect(resolveChatResponsiveLayout(width)).toEqual({ mode, leftVisible, rightVisible });
  });

  it("does not expose an empty or numeric internal user id as the author name", () => {
    expect(resolveChatUserDisplayName("")).toBe("操作者");
    expect(resolveChatUserDisplayName("17533")).toBe("操作者");
    expect(resolveChatUserDisplayName(" 闻望舒 ")).toBe("闻望舒");
  });
});
