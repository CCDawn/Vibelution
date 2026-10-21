import { describe, expect, it } from "vitest";
import { currentInstanceWindowTitle, instanceWindowTitle } from "./instanceWindowTitle";
import shellSource from "./AppShell?raw";

describe("instance window titles", () => {
  it("keeps the workbench title off the full Launcher inventory path", () => {
    expect(shellSource).toContain("queryKeys.launcherCurrentInstance()");
    expect(shellSource).toContain("getCurrentInstanceIdentity({ signal })");
    expect(shellSource).not.toContain("getLocalBranchInstances");
    expect(shellSource).not.toContain("queryKeys.launcherBranchInstances()");
  });
  it("distinguishes workbench and Launcher roles", () => {
    expect(instanceWindowTitle("workbench", "main")).toBe("Vibelution 工作台 · main");
    expect(instanceWindowTitle("launcher", "main")).toBe("Vibelution 启动管理");
    expect(instanceWindowTitle("workbench", "supervisor")).toBe("Vibelution 测试工作台 · supervisor");
    expect(instanceWindowTitle("launcher", "supervisor")).toBe("Vibelution 启动管理");
    expect(instanceWindowTitle("workbench", "branch+codex/fix")).toBe("Vibelution 测试工作台 · codex/fix");
    expect(instanceWindowTitle("workbench", "retired+old-branch")).toBe("Vibelution 测试工作台 · old-branch");
  });

  it("prefers the Launcher-assigned current titles", () => {
    expect(
      currentInstanceWindowTitle("workbench", {
        currentWorkbenchTitle: "supervisor 台",
        currentLauncherTitle: "supervisor 控",
      }),
    ).toBe("supervisor 台");
    expect(
      currentInstanceWindowTitle("launcher", {
        currentWorkbenchTitle: "supervisor 台",
        currentLauncherTitle: "supervisor 控",
      }),
    ).toBe("supervisor 控");
  });
});
