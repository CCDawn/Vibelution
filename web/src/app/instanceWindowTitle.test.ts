import { describe, expect, it } from "vitest";
import { currentInstanceWindowTitle, instanceWindowTitle } from "./instanceWindowTitle";

describe("instance window titles", () => {
  it("puts the short name first so the taskbar still distinguishes branches", () => {
    expect(instanceWindowTitle("workbench", "主")).toBe("主 台");
    expect(instanceWindowTitle("launcher", "主")).toBe("主 控");
    expect(instanceWindowTitle("workbench", "supervisor")).toBe("supervisor 台");
    expect(instanceWindowTitle("launcher", "supervisor")).toBe("supervisor 控");
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
