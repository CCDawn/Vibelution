import { describe, expect, it } from "vitest";
import { join } from "node:path";
import { resolveNoConsoleGitExecutable } from "../src/process/gitProcess.js";

describe("Windows background Git executable", () => {
  it("skips console trampolines and resolves their real mingw executable", () => {
    const root = "C:/portable-git";
    const real = join(root, "mingw64", "bin", "git.exe");
    const wrapper = join(root, "cmd", "git.exe");
    expect(resolveNoConsoleGitExecutable({
      platform: "win32", env: { PATH: join(root, "cmd") },
      fileSize: (path) => path === wrapper ? 45_000 : path === real ? 4_000_000 : 0
    })).toBe(real);
  });

  it("fails closed when only a Windows console trampoline is installed", () => {
    expect(resolveNoConsoleGitExecutable({
      platform: "win32", env: { PATH: "C:/git/cmd" }, fileSize: () => 45_000
    })).toBeNull();
  });
});
