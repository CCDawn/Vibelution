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
    const pendingProjectIndex = source.indexOf("if (pendingProjectRoot)");
    const applySlotIndex = source.indexOf(
      "await applyPendingProjectSlot(pendingProjectRoot, firstLifecycle, desktopLifecycleProvenance, {"
    );
    const noProjectLifecycleIndex = source.indexOf(
      'else if (firstLifecycle && firstLifecycle !== "status" && windowProvider !== null)'
    );
    const noProjectHandleIndex = source.indexOf(
      "await handleSecondInstanceLifecycleCommand(firstLifecycle, desktopLifecycleProvenance)"
    );

    expect(deferIndex).toBeGreaterThan(0);
    expect(openIfIndex).toBeGreaterThan(deferIndex);
    expect(pendingProjectIndex).toBeGreaterThan(openIfIndex);
    expect(applySlotIndex).toBeGreaterThan(pendingProjectIndex);
    expect(noProjectLifecycleIndex).toBeGreaterThan(applySlotIndex);
    expect(noProjectHandleIndex).toBeGreaterThan(noProjectLifecycleIndex);
    expect(source.slice(pendingProjectIndex, noProjectHandleIndex)).toContain(
      "await applyPendingProjectSlot(pendingProjectRoot, firstLifecycle, desktopLifecycleProvenance, {"
    );
    expect(source.slice(pendingProjectIndex, noProjectHandleIndex)).toContain(
      "} else if (firstLifecycle && firstLifecycle !== \"status\" && windowProvider !== null)"
    );
    expect(source.slice(noProjectLifecycleIndex, noProjectHandleIndex)).toContain(
      "startOrFocusWorkbenchFromProductEntryOnShell()"
    );
    expect(source).toContain("if (deferWorkbenchOpen)");
    expect(source).toContain('else if (!desktopCliArgs.workbenchCloseCanary && !desktopCliArgs.projectRoot)');
  });
});

describe("hidden presentation forwarding", () => {
  const readMainSource = () => readFileSync(mainSourcePath, "utf8");

  it("forwards the CLI hidden flag into the first-launch project slot apply", () => {
    const source = readMainSource();
    const pendingProjectIndex = source.indexOf("if (pendingProjectRoot)");
    const applyCallIndex = source.indexOf(
      "await applyPendingProjectSlot(pendingProjectRoot, firstLifecycle, desktopLifecycleProvenance, {"
    );
    expect(pendingProjectIndex).toBeGreaterThan(0);
    expect(applyCallIndex).toBeGreaterThan(pendingProjectIndex);
    expect(source.slice(applyCallIndex, applyCallIndex + 200)).toContain(
      "hiddenPresentation: desktopCliArgs.hiddenPresentation"
    );
  });

  it("carries hidden presentation on second-instance apply_project intents", () => {
    const source = readMainSource();
    expect(source).toContain("hiddenPresentation: secondCli.hiddenPresentation");
    expect(source).toContain("hiddenPresentation: intent.hiddenPresentation");
  });

  it("marks the branch-instance isolated start request and instance window as hidden on demand", () => {
    const source = readMainSource();
    const parseIndex = source.indexOf("const hiddenPresentation = bodyRecord?.hiddenPresentation === true;");
    const providerCallIndex = source.indexOf(
      "await provider.openOrFocusInstanceWorkbench({"
    );
    expect(parseIndex).toBeGreaterThan(0);
    expect(providerCallIndex).toBeGreaterThan(parseIndex);
    expect(source.slice(providerCallIndex, providerCallIndex + 200)).toContain(
      "...(hiddenPresentation ? { present: false } : {})"
    );
  });

  it("gates every provider present:false call site behind the hidden intent", () => {
    const source = readMainSource();
    const occurrences = source.split("present: false").length - 1;
    const gated = source.split("...(hiddenPresentation ? { present: false } : {})").length - 1;
    expect(occurrences).toBeGreaterThan(0);
    expect(gated).toBe(occurrences);
  });
});
