import { describe, expect, it } from "vitest";
import { instanceWindowTitle } from "../src/windows/instanceWindowTitle.js";

describe("Electron instance window titles", () => {
  it("uses the Launcher short name first", () => {
    expect(instanceWindowTitle("workbench", "main")).toBe("main 台");
    expect(instanceWindowTitle("launcher", "main")).toBe("main 控");
    expect(instanceWindowTitle("workbench", "supervisor")).toBe("supervisor 台");
    expect(instanceWindowTitle("launcher", "supervisor")).toBe("supervisor 控");
  });
});
