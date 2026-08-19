import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));

describe("Electron main startup sequence", () => {
  it("does not register whenReady reap on a secondary product instance", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const gateIndex = source.indexOf("const runPrimaryWhenReady = shouldRunDesktopWhenReadyHandlers(");
    const quitIndex = source.indexOf("if (!runPrimaryWhenReady)");
    const approveIndex = source.indexOf("shutdownApproved = true", quitIndex);
    const whenReadyGuardIndex = source.indexOf("if (runPrimaryWhenReady)");
    const reapIndex = source.indexOf("await reapManagedRuntimeOnDesktopStart");

    expect(gateIndex).toBeGreaterThan(0);
    expect(quitIndex).toBeGreaterThan(gateIndex);
    expect(approveIndex).toBeGreaterThan(quitIndex);
    expect(whenReadyGuardIndex).toBeGreaterThan(approveIndex);
    expect(reapIndex).toBeGreaterThan(whenReadyGuardIndex);
    expect(source).toContain("shouldRunDesktopWhenReadyHandlers({");
  });

  it("starts the workbench lifecycle before loading a possibly-dead workbench URL", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const deferIndex = source.indexOf("shouldDeferWorkbenchOpenUntilLifecycleStart(firstLifecycle)");
    const openIfIndex = source.indexOf(
      "if (pendingOpenWorkbenchRequest && !desktopCliArgs.workbenchCloseCanary && !deferWorkbenchOpen)"
    );
    const lifecycleIndex = source.indexOf("void handleSecondInstanceLifecycleCommand(firstLifecycle)");

    expect(deferIndex).toBeGreaterThan(0);
    expect(openIfIndex).toBeGreaterThan(deferIndex);
    expect(source).toContain("await applyPendingProjectSlot(pendingProjectRoot, firstLifecycle)");
    expect(lifecycleIndex).toBeGreaterThan(source.indexOf("await applyPendingProjectSlot(pendingProjectRoot, firstLifecycle)"));
  });
});
