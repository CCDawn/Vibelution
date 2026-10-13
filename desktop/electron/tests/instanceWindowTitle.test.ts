import { describe, expect, it } from "vitest";
import { instanceWindowTitle } from "../src/windows/instanceWindowTitle.js";

describe("Electron instance window titles", () => {
  it("distinguishes workbench and Launcher roles", () => {
    expect(instanceWindowTitle("workbench", "main")).toBe("Vibelution 工作台 · main");
    expect(instanceWindowTitle("launcher", "main")).toBe("Vibelution 启动管理");
    expect(instanceWindowTitle("workbench", "supervisor")).toBe("Vibelution 测试工作台 · supervisor");
    expect(instanceWindowTitle("launcher", "supervisor")).toBe("Vibelution 启动管理");
    expect(instanceWindowTitle("workbench", "branch+codex/fix")).toBe("Vibelution 测试工作台 · codex/fix");
    expect(instanceWindowTitle("workbench", "retired+old-branch")).toBe("Vibelution 测试工作台 · old-branch");
  });
});
