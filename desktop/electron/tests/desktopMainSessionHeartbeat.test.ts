import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));

describe("Electron main desktop session heartbeat", () => {
  it("reuses the shared desktopSessionClient heartbeat without a second session protocol", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("heartbeatDesktopSession,");
    expect(source).toContain('from "./windows/desktopSessionClient.js"');
    expect(source).toContain('desktopSessionMutations.enqueue("heartbeat", async () => {');
    expect(source).toContain("...(await resolveDesktopActionLoopContext(currentBootstrap))");
    expect(source).toContain("revision: desktopSessionRevision");
  });

  it("starts the heartbeat only after registration when the launcher declares the capability", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const registrationIndex = source.indexOf("desktopSessionRegistered = true;");
    const startCallIndex = source.indexOf("startDesktopSessionHeartbeatIfNeeded(paths, bootstrap)");

    expect(source).toContain('DESKTOP_SESSIONS_HEARTBEAT_CAPABILITY = "desktop_sessions.heartbeat"');
    expect(registrationIndex).toBeGreaterThan(-1);
    expect(startCallIndex).toBeGreaterThan(registrationIndex);
    expect(source).toContain("!desktopSessionHeartbeatSupported(bootstrap)");
    expect(source).toContain("desktopSessionHeartbeatTimer !== null");
    expect(source).toContain("!desktopSessionRegistered");
  });

  it("swallows heartbeat failures instead of quitting Electron", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const heartbeatStart = source.indexOf("await heartbeatDesktopSession(");
    const heartbeatEnd = source.indexOf("desktopSessionHeartbeatRunning = false;", heartbeatStart);
    const heartbeatBlock = source.slice(heartbeatStart, heartbeatEnd);

    expect(heartbeatStart).toBeGreaterThan(-1);
    expect(heartbeatEnd).toBeGreaterThan(heartbeatStart);
    expect(heartbeatBlock).toContain("catch (error: unknown)");
    expect(heartbeatBlock).toContain("console.warn");
    expect(heartbeatBlock).not.toContain("app.quit");
    expect(source).toContain('from "./runtime/brokenPipeGuard.js"');
    expect(source).toContain("installBrokenPipeGuards()");
  });

  it("refreshes a rejected control context and preserves the desktop session identity", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const recoveryStart = source.indexOf("async function recoverDesktopControlContext(");
    const recoveryEnd = source.indexOf("async function recoverWorkbenchCloseControlContext(", recoveryStart);
    const recoveryBlock = source.slice(recoveryStart, recoveryEnd);
    const heartbeatStart = source.indexOf("const heartbeatOnce = async () => {");
    const heartbeatEnd = source.indexOf("function stopDesktopSessionHeartbeat()", heartbeatStart);
    const heartbeatBlock = source.slice(heartbeatStart, heartbeatEnd);
    const actionStart = source.indexOf("function startDesktopActionLoop(");
    const actionEnd = source.indexOf("async function openWorkbenchAtCurrentLauncherUrl(", actionStart);
    const actionBlock = source.slice(actionStart, actionEnd);

    expect(recoveryStart).toBeGreaterThan(-1);
    expect(recoveryEnd).toBeGreaterThan(recoveryStart);
    expect(recoveryBlock).toContain("forceControlTokenRefresh: true");
    expect(recoveryBlock).toContain("refreshedContext.desktopSessionId !== previousContext.desktopSessionId");
    expect(recoveryBlock).toContain("await persistManagedWindowState(paths, bootstrap, provider.snapshot().workbench)");
    expect(recoveryBlock).not.toContain("app.quit");
    expect(heartbeatBlock).toContain("isRecoverableDesktopControlError(error)");
    expect(heartbeatBlock).toContain("await recoverDesktopControlContext(");
    expect(actionBlock).toContain("isRecoverableDesktopControlError(error)");
    expect(actionBlock).toContain("await recoverDesktopControlContext(");
  });

  it("clears the heartbeat timer on lifecycle stop and session close", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const stopActionLoopIndex = source.indexOf("function stopDesktopActionLoop()");
    const stopActionLoopBody = source.slice(
      stopActionLoopIndex,
      source.indexOf("async function closeDesktopSessionIfRegistered()", stopActionLoopIndex)
    );
    const closeSessionBody = source.slice(
      source.indexOf("async function closeDesktopSessionIfRegistered()"),
      source.indexOf("async function stopOwnedPythonLauncherService()")
    );

    expect(source).toContain("function stopDesktopSessionHeartbeat()");
    expect(source).toContain("clearInterval(desktopSessionHeartbeatTimer)");
    expect(stopActionLoopBody).toContain("stopDesktopSessionHeartbeat()");
    expect(closeSessionBody).toContain("desktopSessionRegistered = false;");
    expect(closeSessionBody).toContain("stopDesktopSessionHeartbeat()");
  });
});
