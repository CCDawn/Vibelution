import { describe, expect, it } from "vitest";
import { instanceWindowTitle } from "../src/windows/instanceWindowTitle.js";

describe("Electron instance window titles", () => {
  it("uses the Launcher short name first", () => {
    expect(instanceWindowTitle("workbench", "主")).toBe("主 台");
    expect(instanceWindowTitle("launcher", "主")).toBe("主 控");
    expect(instanceWindowTitle("workbench", "supervisor")).toBe("supervisor 台");
    expect(instanceWindowTitle("launcher", "supervisor")).toBe("supervisor 控");
  });
});
