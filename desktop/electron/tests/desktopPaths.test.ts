import { describe, expect, it } from "vitest";
import {
  createDesktopPaths,
  resolveDesktopEntryCatalogPath,
  resolvePreloadPath,
  resolveWorkspaceIconPath,
  resolveWorkspaceRuntimeDir
} from "../src/paths.js";

describe("Electron desktop paths", () => {
  it("keeps packaged bundle path separate from external workspace", () => {
    const paths = createDesktopPaths({
      importMetaUrl: "file:///C:/Program%20Files/Vibelution/resources/app.asar/dist/main.js",
      resourcesRoot: "C:/Program Files/Vibelution/resources",
      userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution",
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution"
    });

    expect(resolvePreloadPath(paths).replace(/\\/g, "/")).toBe(
      "C:/Program Files/Vibelution/resources/app.asar/dist/preload.cjs"
    );
    expect(resolveWorkspaceRuntimeDir(paths).replace(/\\/g, "/")).toBe(
      "C:/Users/17533/Desktop/Vibelution/.runtime/launcher"
    );
  });

  it("resolves the shared Vibelution icon from the external workspace", () => {
    const paths = createDesktopPaths({
      importMetaUrl: "file:///C:/Program%20Files/Vibelution/resources/app.asar/dist/main.js",
      resourcesRoot: "C:/Program Files/Vibelution/resources",
      userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution",
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution"
    });

    expect(resolveWorkspaceIconPath(paths).replace(/\\/g, "/")).toBe(
      "C:/Users/17533/Desktop/Vibelution/assets/icons/vibelution.ico"
    );
  });

  it("resolves the desktop entry catalog from the packaged app bundle", () => {
    const paths = createDesktopPaths({
      importMetaUrl: "file:///C:/Program%20Files/Vibelution/resources/app.asar/dist/main.js",
      resourcesRoot: "C:/Program Files/Vibelution/resources",
      userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution",
      workspaceRoot: "C:/Users/17533/Desktop/Vibelution"
    });

    expect(resolveDesktopEntryCatalogPath(paths).replace(/\\/g, "/")).toBe(
      "C:/Program Files/Vibelution/resources/app.asar/desktop-entry-catalog.json"
    );
  });
});
