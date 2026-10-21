import { execFile } from "node:child_process";
import { statSync } from "node:fs";
import { dirname, join } from "node:path";

// Match core.infrastructure.no_console_git: Git/cmd and Git/bin contain
// console-allocating trampolines. Only use the real mingw executable on Windows.
export function resolveNoConsoleGitExecutable(input: {
  platform?: NodeJS.Platform;
  env?: NodeJS.ProcessEnv;
  fileSize?: (path: string) => number;
} = {}): string | null {
  if ((input.platform ?? process.platform) !== "win32") return "git";
  const env = input.env ?? process.env;
  const candidates: string[] = [];
  const addRoot = (root: string): void => {
    candidates.push(join(root, "mingw64", "bin", "git.exe"));
    candidates.push(join(root, "mingw64", "libexec", "git-core", "git.exe"));
  };
  for (const root of [env.ProgramFiles, env.ProgramW6432, env["ProgramFiles(x86)"], env.LOCALAPPDATA]) {
    if (!root) continue;
    addRoot(join(root, "Git"));
    addRoot(join(root, "Programs", "Git"));
    addRoot(root);
  }
  for (const entry of String(env.PATH ?? env.Path ?? "").split(";")) {
    const directory = entry.trim().replace(/^"|"$/g, "");
    if (!directory) continue;
    candidates.push(join(directory, "git.exe"));
    addRoot(dirname(directory));
    addRoot(dirname(dirname(directory)));
  }
  const fileSize = input.fileSize ?? ((path: string) => {
    const stat = statSync(path);
    return stat.isFile() ? stat.size : 0;
  });
  for (const candidate of new Set(candidates)) {
    try {
      if (fileSize(candidate) > 200_000) return candidate;
    } catch { /* missing installation candidate */ }
  }
  return null;
}

export async function readOnlyGitText(workspaceRoot: string, args: string[]): Promise<string | null> {
  const executable = resolveNoConsoleGitExecutable();
  if (!executable) return null;
  return await new Promise<string | null>((resolve) => {
    execFile(executable, args, {
      cwd: workspaceRoot,
      encoding: "utf8",
      windowsHide: true,
      shell: false,
      timeout: 10_000,
      env: { ...process.env, GIT_TERMINAL_PROMPT: "0", GCM_INTERACTIVE: "Never", GIT_OPTIONAL_LOCKS: "0" }
    }, (error, stdout) => {
      resolve(error ? null : stdout.replace(/\r\n/g, "\n").replace(/\r/g, "\n"));
    });
  });
}
