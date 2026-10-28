import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi } from "vitest";
import { isWorkbenchStartBlockedByClose } from "../src/lifecycle/workbenchCloseTransactionStore.js";
import { ProjectAdmission } from "../src/lifecycle/projectAdmission.js";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

describe("Electron main workbench open backend gate", () => {
  it("proves the backend is serving before any open action navigates a window", () => {
    const entryStart = mainSource.indexOf("async function openWorkbenchAtCurrentLauncherUrl");
    const entryEnd = mainSource.indexOf("async function reportManagedWindowState", entryStart);
    const entryBody = mainSource.slice(entryStart, entryEnd);

    expect(entryBody).toContain("ensureWorkbenchBackendReady({");
    expect(entryBody).toContain('await orchestrateLauncherLifecycle("start"');
    expect(entryBody.indexOf("ensureWorkbenchBackendReady")).toBeLessThan(
      entryBody.indexOf("provider.openOrFocusWorkbench")
    );
  });

  it("never restarts or shows an error window when an old open crosses a complete close", async () => {
    const entryStart = mainSource.indexOf("async function openWorkbenchAtCurrentLauncherUrl");
    const entryEnd = mainSource.indexOf("async function reportManagedWindowState", entryStart);
    let resume!: () => void;
    const paused = new Promise<void>((resolve) => { resume = resolve; });
    const start = vi.fn(async () => ({ accepted: true }));
    const presentError = vi.fn(async () => undefined);
    const navigate = vi.fn(async () => ({ windowId: 1, rendererProcessId: 1 }));
    const admission = new ProjectAdmission();
    const context = {
      withProjectAdmission: (root: () => string, work: Parameters<ProjectAdmission["observe"]>[1]) => admission.observe(root, work),
      registeredAdmissionRoot: (root: string) => root,
      workbenchCloseGeneration: 0, workbenchFailedCloseHandling: false, pendingWorkbenchCloseAck: null,
      AbortController, workbenchOpenControllers: new Set<AbortController>(),
      currentWorkbenchUrl: "", electronStartupStage: "", desktopEnvironment: () => ({}),
      mainWorkbenchCloseStore: { currentTransaction: () => null }, hasBackgroundWorkbenchRetirement: () => false,
      isWorkbenchStartBlockedByClose, markWorkbenchOpenRequested: () => 0,
      resolveWorkbenchUrl: () => "http://127.0.0.1:8000/", safeOrigin: (url: string) => url,
      ensureWorkbenchBackendReady: async (options: { startLifecycle: () => Promise<unknown> }) => {
        await paused;
        await options.startLifecycle();
      },
      orchestrateLauncherLifecycle: start, recordElectronSupervisorEvent: async () => undefined,
      electronStartupFields: () => ({}), electronStageElapsedMs: () => 0,
    };
    const entry = mainSource.slice(entryStart, entryEnd);
    runInNewContext(transpileModule(entry + "\nglobalThis.open = openWorkbenchAtCurrentLauncherUrl;", {
      compilerOptions: { target: ScriptTarget.ES2022 }
    }).outputText, context);
    const open = (context as typeof context & { open: (...args: unknown[]) => Promise<unknown> }).open;
    const pending = open({ workspaceRoot: "C:/isolated" }, { workbenchUrl: "" },
      { presentWorkbenchErrorStatus: presentError, openOrFocusWorkbench: navigate });
    context.workbenchCloseGeneration += 1;
    resume();
    await expect(pending).rejects.toThrow("superseded by close");
    expect(start).not.toHaveBeenCalled();
    expect(presentError).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
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
