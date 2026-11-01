import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi } from "vitest";

describe("canonical Launcher state file hints", () => {
  it("watches the state owner directory and gates its logs and unfinished writes", () => {
    const source = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
    const start = source.indexOf("function startLauncherStateFileHints(");
    const end = source.indexOf("function stopLauncherStateFileHints(", start);
    const callbacks = new Map<string, (event: string, filename: string | null) => void>();
    const hint = vi.fn();
    const consumeNullFilenameEvent = vi.fn(() => false);
    const canonical = resolve("C:/external/runtime/launcher/state.json");
    const sandbox: Record<string, unknown> = {
      dirname, resolve, Map,
      stopLauncherStateFileHints: vi.fn(),
      desktopEnvironment: () => ({ LOCALAPPDATA: "C:/external" }),
      launcherStatePath: () => canonical,
      createLauncherStateFileHintGate: vi.fn(() => ({ consumeNullFilenameEvent, markRefreshStarted: vi.fn(), consumeStatPoll: vi.fn(() => false) })),
      launcherStateFileHintGate: null,
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
    // A real gate must be installed for null-filename decisions.
    expect(sandbox.createLauncherStateFileHintGate).toHaveBeenCalledWith({
      observedPaths: [resolve(dirname(canonical), "state.json"), resolve(dirname(canonical), "ports.json")],
      statSignature: expect.any(Function),
    });
    for (const file of ["backend.stdout.log", "backend.stderr.log", "state.json.123.tmp"]) {
      runtimeHint!("change", file);
    }
    expect(hint).not.toHaveBeenCalled();
    runtimeHint!("rename", "state.json");
    runtimeHint!("change", "ports.json");
    expect(hint).toHaveBeenCalledTimes(2);
    // A null-filename event never schedules on its own: only the gate may
    // promote it after a real state/port signature change outside the
    // post-refresh quiet window.
    expect(hint).not.toHaveBeenCalledTimes(3);
    runtimeHint!("rename", null);
    runtimeHint!("change", null);
    expect(consumeNullFilenameEvent).toHaveBeenCalledTimes(2);
    expect(hint).toHaveBeenCalledTimes(2);
    // When the gate observes a genuine signature change, the hint fires.
    consumeNullFilenameEvent.mockReturnValue(true);
    runtimeHint!("change", null);
    expect(hint).toHaveBeenCalledTimes(3);
    // Non-runtime watch targets keep their pass-through behavior.
    const gitHint = callbacks.get(resolve("C:/checkout", ".git"));
    expect(gitHint).toBeDefined();
    gitHint!("change", null);
    expect(hint).toHaveBeenCalledTimes(4);
  });
});
