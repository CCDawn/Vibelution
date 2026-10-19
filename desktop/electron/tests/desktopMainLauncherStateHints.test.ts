import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi } from "vitest";

describe("canonical Launcher state file hints", () => {
  it("watches the state owner directory and ignores its logs and unfinished writes", () => {
    const source = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
    const start = source.indexOf("function startLauncherStateFileHints(");
    const end = source.indexOf("function stopLauncherStateFileHints(", start);
    const callbacks = new Map<string, (event: string, filename: string | null) => void>();
    const hint = vi.fn();
    const canonical = resolve("C:/external/runtime/launcher/state.json");
    const sandbox: Record<string, unknown> = {
      dirname, resolve, Map,
      stopLauncherStateFileHints: vi.fn(),
      desktopEnvironment: () => ({ LOCALAPPDATA: "C:/external" }),
      launcherStatePath: () => canonical,
      launcherStateStatSignatures: new Map(),
      launcherStateStatSignature: () => "unchanged",
      launcherStateWatchers: [],
      launcherStateStatTimer: null,
      setInterval: vi.fn(() => ({ unref: vi.fn() })),
      scheduleLauncherStateFileHint: hint,
      watch: (target: string, _options: object, callback: (event: string, filename: string | null) => void) => {
        callbacks.set(target, callback);
        return { on: vi.fn() };
      },
    };
    runInNewContext(transpileModule(source.slice(start, end)
      + "\nglobalThis.startHints = startLauncherStateFileHints;", {
      compilerOptions: { target: ScriptTarget.ES2022 },
    }).outputText, sandbox);
    (sandbox.startHints as (paths: { workspaceRoot: string }) => void)({ workspaceRoot: "C:/checkout" });
    const runtimeHint = callbacks.get(dirname(canonical));
    expect(runtimeHint).toBeDefined();
    expect(callbacks.has(resolve("C:/checkout", ".runtime", "launcher"))).toBe(false);
    for (const file of ["backend.stdout.log", "backend.stderr.log", "state.json.123.tmp"]) {
      runtimeHint!("change", file);
    }
    expect(hint).not.toHaveBeenCalled();
    runtimeHint!("rename", "state.json");
    runtimeHint!("change", "ports.json");
    runtimeHint!("rename", null);
    expect(hint).toHaveBeenCalledTimes(3);
  });
});
