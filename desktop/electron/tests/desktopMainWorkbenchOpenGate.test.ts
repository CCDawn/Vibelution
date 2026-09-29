import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

describe("Electron main workbench open backend gate", () => {
  it("proves the backend is serving before any open action navigates a window", () => {
    const entryStart = mainSource.indexOf("async function openWorkbenchAtCurrentLauncherUrl");
    const entryEnd = mainSource.indexOf("async function reportManagedWindowState", entryStart);
    const entryBody = mainSource.slice(entryStart, entryEnd);

    expect(entryBody).toContain("ensureWorkbenchBackendReady({");
    expect(entryBody).toContain('startLifecycle: () => orchestrateLauncherLifecycle("start"');
    expect(entryBody.indexOf("ensureWorkbenchBackendReady")).toBeLessThan(
      entryBody.indexOf("provider.openOrFocusWorkbench")
    );
  });

  it("routes a failed backend start into the visible error status, never a silent destroy", () => {
    const entryStart = mainSource.indexOf("async function openWorkbenchAtCurrentLauncherUrl");
    const entryEnd = mainSource.indexOf("async function reportManagedWindowState", entryStart);
    const entryBody = mainSource.slice(entryStart, entryEnd);

    expect(entryBody).toContain("presentWorkbenchErrorStatus");
    expect(entryBody).toContain("safeOrigin(workbenchUrl)");
  });

  it("keeps the gate wired to the window provider modules", () => {
    expect(mainSource).toContain('from "./windows/workbenchOpenBackendGate.js"');
    expect(mainSource).toContain('ensureWorkbenchBackendReady({');
  });
});
