import { spawn } from "node:child_process";
import { resolve } from "node:path";

export type WorkbenchLifecycleOperation = "start" | "stop" | "force-stop" | "restart" | "rebuild-and-start";

export type WorkbenchLifecycleResult = {
  schemaVersion: 1;
  accepted: boolean;
  operation: string;
  commandId?: string;
  message?: string;
  code?: string;
  activeWorkRuns?: unknown[];
};

type LifecycleChild = Pick<ReturnType<typeof spawn>, "kill" | "once" | "stdout" | "stderr">;
type LifecycleSpawn = (
  command: string,
  args: string[],
  options: {
    cwd: string;
    windowsHide: boolean;
    stdio: ["ignore", "pipe", "pipe"];
  }
) => LifecycleChild;

export function parseWorkbenchLifecycleResult(raw: string): WorkbenchLifecycleResult {
  const parsed = JSON.parse(raw) as WorkbenchLifecycleResult;
  if (!parsed || parsed.schemaVersion !== 1 || typeof parsed.accepted !== "boolean") {
    throw new Error("invalid workbench lifecycle bridge result");
  }
  return {
    schemaVersion: 1,
    accepted: Boolean(parsed.accepted),
    operation: String(parsed.operation || ""),
    ...(typeof parsed.commandId === "string" && parsed.commandId ? { commandId: parsed.commandId } : {}),
    ...(typeof parsed.message === "string" && parsed.message ? { message: parsed.message } : {}),
    ...(typeof parsed.code === "string" && parsed.code ? { code: parsed.code } : {}),
    ...(Array.isArray(parsed.activeWorkRuns) ? { activeWorkRuns: parsed.activeWorkRuns } : {})
  };
}

export async function runWorkbenchLifecycle(input: {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  operation: WorkbenchLifecycleOperation;
  spawnImpl?: LifecycleSpawn;
}): Promise<WorkbenchLifecycleResult> {
  const spawnImpl = input.spawnImpl ?? spawn;
  const args = [
    resolve(input.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
    "--action",
    "lifecycle",
    "--lifecycle-operation",
    input.operation,
    "--output",
    "json",
    "--workspace",
    input.workspaceRoot,
    "--config",
    input.operatorConfigPath,
    "--no-browser"
  ];
  const child = spawnImpl(input.pythonPath, args, {
    cwd: input.workspaceRoot,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"]
  });
  const stdout = await readBoundedLifecycleStdout(child, 64_000);
  return parseWorkbenchLifecycleResult(stdout);
}

async function readBoundedLifecycleStdout(child: LifecycleChild, maxBytes: number): Promise<string> {
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
        rejectOnce(new Error("workbench lifecycle bridge output exceeded limit"));
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
        rejectOnce(new Error(`workbench lifecycle bridge exited with code ${code ?? "unknown"}`));
        return;
      }
      settled = true;
      resolveOutput(Buffer.concat(chunks).toString("utf8"));
    });
  });
}
