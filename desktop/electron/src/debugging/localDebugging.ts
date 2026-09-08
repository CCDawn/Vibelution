import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { setTimeout } from "node:timers/promises";
import { desktopShellOwnerPath, type DesktopShellOwnerIdentity } from "../tray/desktopShellOwner.js";

type DebugApp = {
  isPackaged: boolean;
  getPath(name: "userData"): string;
  commandLine: { appendSwitch(name: string, value: string): void; removeSwitch(name: string): void };
};

export function identifyDebugWindow(
  rendererProcessId: number,
  windows: {
    launcher: { rendererProcessId: number };
    workbench: { rendererProcessId: number };
    pet?: { rendererProcessId: number };
  } | null,
  instances: Array<{ rendererProcessId: number; instanceId: string }>
): { role: string; instanceId?: string } {
  const instance = instances.find(item => item.rendererProcessId === rendererProcessId);
  if (instance) return { role: "branch-workbench", instanceId: instance.instanceId };
  if (windows?.launcher.rendererProcessId === rendererProcessId) return { role: "launcher" };
  if (windows?.workbench.rendererProcessId === rendererProcessId) return { role: "main-workbench" };
  if (windows?.pet?.rendererProcessId === rendererProcessId) return { role: "desktop-pet" };
  return { role: "unknown" };
}

/** Call after acquiring the single-instance lock, before Chromium starts. */
export function configureLocalDebugging(app: DebugApp, argv: string[], primary: boolean): boolean {
  if (!primary) return false;
  const enabled = !app.isPackaged || argv.includes("--local-debugging");
  app.commandLine.removeSwitch("remote-debugging-port");
  app.commandLine.removeSwitch("remote-debugging-address");
  app.commandLine.removeSwitch("remote-debugging-pipe");
  // Chromium leaves this file behind on exit. Never publish a previous startup's endpoint.
  rmSync(join(app.getPath("userData"), "DevToolsActivePort"), { force: true });
  if (enabled) {
    app.commandLine.appendSwitch("remote-debugging-address", "127.0.0.1");
    app.commandLine.appendSwitch("remote-debugging-port", "0");
  }
  return enabled;
}

/** Read-only discovery projection; Chromium and the existing shell owner remain authoritative. */
export async function publishLocalDebugging(
  userDataRoot: string,
  workspaceRoot: string,
  identity: DesktopShellOwnerIdentity,
  recordPath = join(dirname(desktopShellOwnerPath(workspaceRoot)), "desktop_debug.json")
): Promise<() => void> {
  const deadline = Date.now() + 5000;
  let lines: string[] = [];
  while (Date.now() < deadline) {
    try {
      lines = readFileSync(join(userDataRoot, "DevToolsActivePort"), "utf8").trim().split(/\r?\n/);
      if (lines.length >= 2) break;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    await setTimeout(50);
  }
  const port = Number(lines[0]);
  if (!Number.isInteger(port) || port <= 0 || port > 65535 || !/^\/devtools\/browser\/[\w-]+$/.test(lines[1] || "")) {
    throw new Error("Local desktop debugging endpoint was not published by Chromium.");
  }
  const record = {
    schemaVersion: 1, ...identity, workspaceRoot,
    httpEndpoint: `http://127.0.0.1:${port}`,
    webSocketDebuggerUrl: `ws://127.0.0.1:${port}${lines[1]}`
  };
  mkdirSync(dirname(recordPath), { recursive: true });
  const temporary = `${recordPath}.${identity.pid}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(record, null, 2)}\n`, "utf8");
  renameSync(temporary, recordPath);
  return () => {
    try {
      const current = JSON.parse(readFileSync(recordPath, "utf8"));
      if (current.webSocketDebuggerUrl === record.webSocketDebuggerUrl) rmSync(recordPath, { force: true });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") console.warn("Unable to retire desktop debug discovery", error);
    }
  };
}
