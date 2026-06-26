import { describe, expect, it } from "vitest";
import { createDesktopPaths, resolveWorkspaceRuntimeDir } from "../src/paths.js";

describe("Electron desktop paths", () => {
  it("keeps launcher runtime state under the external workspace", () => {
    const paths = createDesktopPaths({
      importMetaUrl: "file:///C:/Program%20Files/Vibelution/resources/app.asar/dist/main.js",
      resourcesRoot: "C:/Program Files/Vibelution/resources",
      userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution",
      workspaceRoot: "C:/repo"
    });
    expect(resolveWorkspaceRuntimeDir(paths).replace(/\\/g, "/")).toBe("C:/repo/.runtime/launcher");
  });
});
