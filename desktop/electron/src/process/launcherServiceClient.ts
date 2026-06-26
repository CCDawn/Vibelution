import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { parseLauncherBootstrap, type LauncherBootstrapResult } from "./launcherBootstrap.js";

export type LauncherServiceStartInput = {
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
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

async function readBoundedStdout(child: ReturnType<typeof spawn>, maxBytes: number): Promise<string> {
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
