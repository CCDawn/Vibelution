import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { parseLauncherBootstrap, type LauncherBootstrapResult } from "./launcherBootstrap.js";

type LauncherServiceChild = Pick<ReturnType<typeof spawn>, "kill" | "once" | "stdout" | "stderr">;
type LauncherServiceSpawn = (
  command: string,
  args: string[],
  options: {
    cwd: string;
    windowsHide: boolean;
    stdio: ["ignore", "pipe", "pipe"];
  }
) => LauncherServiceChild;

export type LauncherServiceStartInput = {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
};

export type LauncherServiceStopInput = LauncherServiceStartInput & {
  launcherBackendPid: number;
  spawnImpl?: LauncherServiceSpawn;
};

export type LauncherServiceStopResult = {
  schemaVersion: 1;
  status: "stopped" | "skipped";
  reason: string;
  expectedBackendPid: number;
  launcherBackendPid: number;
  terminatedPids: number[];
};

export async function bootstrapPythonLauncherService(input: LauncherServiceStartInput): Promise<LauncherBootstrapResult> {
  const child = spawn(
    input.pythonPath,
    [
      resolve(input.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
      "--action",
      "bootstrap",
      "--output",
      "json",
      "--workspace",
      input.workspaceRoot,
      "--config",
      input.operatorConfigPath,
      "--no-browser"
    ],
    {
      cwd: input.workspaceRoot,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"]
    }
  );
  const stdout = await readBoundedStdout(child, 64_000);
  return parseLauncherBootstrap(stdout);
}

export async function stopPythonLauncherService(input: LauncherServiceStopInput): Promise<LauncherServiceStopResult> {
  const spawnImpl = input.spawnImpl ?? spawn;
  const child = spawnImpl(
    input.pythonPath,
    [
      resolve(input.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
      "--action",
      "stop-launcher",
      "--output",
      "json",
      "--workspace",
      input.workspaceRoot,
      "--config",
      input.operatorConfigPath,
      "--owned-backend-pid",
      String(input.launcherBackendPid),
      "--no-browser"
    ],
    {
      cwd: input.workspaceRoot,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"]
    }
  );
  const stdout = await readBoundedStdout(child, 64_000);
  return parseLauncherStop(stdout);
}

function parseLauncherStop(raw: string): LauncherServiceStopResult {
  const parsed = JSON.parse(raw) as LauncherServiceStopResult;
  if (parsed.schemaVersion !== 1 || !["stopped", "skipped"].includes(parsed.status)) {
    throw new Error("invalid launcher stop result");
  }
  if (!Array.isArray(parsed.terminatedPids)) {
    throw new Error("invalid launcher stop result");
  }
  return {
    schemaVersion: 1,
    status: parsed.status,
    reason: String(parsed.reason || ""),
    expectedBackendPid: Number(parsed.expectedBackendPid || 0),
    launcherBackendPid: Number(parsed.launcherBackendPid || 0),
    terminatedPids: parsed.terminatedPids.map((pid) => Number(pid)).filter((pid) => Number.isFinite(pid) && pid > 0)
  };
}

async function readBoundedStdout(child: LauncherServiceChild, maxBytes: number): Promise<string> {
  return await new Promise((resolveOutput, reject) => {
    const chunks: Buffer[] = [];
    let total = 0;
    let settled = false;

    const rejectOnce = (error: Error): void => {
      if (settled) {
        return;
      }
      settled = true;
      reject(error);
    };

    child.stdout?.on("data", (chunk: Buffer) => {
      total += chunk.length;
      if (total > maxBytes) {
        child.kill();
        rejectOnce(new Error("launcher bootstrap output exceeded limit"));
        return;
      }
      chunks.push(chunk);
    });
    child.stderr?.on("data", () => {
      // Drain stderr so stdio pipes cannot deadlock; detailed logs stay in Python launcher log files.
    });
    child.once("error", rejectOnce);
    child.once("exit", (code) => {
      if (settled) {
        return;
      }
      if (code !== 0) {
        rejectOnce(new Error(`launcher bootstrap exited with code ${code ?? "unknown"}`));
        return;
      }
      settled = true;
      resolveOutput(Buffer.concat(chunks).toString("utf8"));
    });
  });
}
