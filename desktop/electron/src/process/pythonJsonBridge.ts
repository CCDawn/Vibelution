import { spawn } from "node:child_process";

import { pythonBridgeEnv } from "./pythonBridgeEnv.js";

export const DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES = 64_000;
export const LAUNCHER_API_JSON_BRIDGE_MAX_BYTES = 2_000_000;

export type PythonJsonBridgeChild = Pick<ReturnType<typeof spawn>, "kill" | "once" | "stdout" | "stderr">;
export type PythonJsonBridgeSpawn = (
  command: string,
  args: string[],
  options: {
    cwd: string;
    windowsHide: boolean;
    stdio: ["ignore", "pipe", "pipe"];
    env: NodeJS.ProcessEnv;
  }
) => PythonJsonBridgeChild;

export async function runPythonJsonBridge(input: {
  pythonPath: string;
  args: string[];
  cwd: string;
  spawnImpl?: PythonJsonBridgeSpawn;
  failureLabel: string;
  maxBytes?: number;
}): Promise<string> {
  const spawnImpl = input.spawnImpl ?? spawn;
  const maxBytes = Math.max(1_000, Math.round(input.maxBytes ?? DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES));
  const child = spawnImpl(input.pythonPath, input.args, {
    cwd: input.cwd,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: pythonBridgeEnv()
  });
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
        rejectOnce(new Error(`${input.failureLabel} output exceeded limit`));
        return;
      }
      chunks.push(chunk);
    });
    child.stderr?.on("data", () => {
      // Drain stderr so stdio pipes cannot deadlock; detailed logs stay in Python log files.
    });
    child.once("error", rejectOnce);
    child.once("exit", (code) => {
      if (settled) {
        return;
      }
      if (code !== 0) {
        rejectOnce(new Error(`${input.failureLabel} exited with code ${code ?? "unknown"}`));
        return;
      }
      settled = true;
      resolveOutput(Buffer.concat(chunks).toString("utf8"));
    });
  });
}
