import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { describe, expect, it, vi, type Mock } from "vitest";

type FakeGate = {
  observedPaths: readonly string[];
  consumeNullFilenameEvent: Mock;
  markRefreshStarted: Mock;
  consumeStatPoll: Mock;
};

describe("canonical Launcher state file hints", () => {
  it("gates every watch target on named evidence and ignores the refresh's own side effects", () => {
    const source = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
    const start = source.indexOf("function startLauncherStateFileHints(");
    const end = source.indexOf("function stopLauncherStateFileHints(", start);
    const callbacks = new Map<string, (event: string, filename: string | null) => void>();
    const hint = vi.fn();
    const gates: FakeGate[] = [];
    const createGate = vi.fn((input: { observedPaths: readonly string[] }): FakeGate => {
      const gate: FakeGate = {
        observedPaths: input.observedPaths,
        consumeNullFilenameEvent: vi.fn(() => false),
        markRefreshStarted: vi.fn(),
        consumeStatPoll: vi.fn(() => false),
      };
      gates.push(gate);
      return gate;
    });
    const canonical = resolve("C:/external/runtime/launcher/state.json");
    const runtimeDir = dirname(canonical);
    const gitDir = resolve("C:/checkout", ".git");
    const localRoot = resolve("C:/external", "Vibelution");
    const sandbox: Record<string, unknown> = {
      dirname, resolve, Map, Set,
      stopLauncherStateFileHints: vi.fn(),
      desktopEnvironment: () => ({ LOCALAPPDATA: "C:/external" }),
      launcherStatePath: () => canonical,
      createLauncherStateFileHintGate: createGate,
      launcherStateFileHintGates: [] as FakeGate[],
      launcherStateHintBackoff: { currentDelayMs: () => 200, recordFire: vi.fn(), isEscalated: () => false },
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

    // Three watched targets, each with its own evidence gate; the checkout's
    // own .runtime/launcher is not a watch target.
    expect([...callbacks.keys()].sort()).toEqual([gitDir, localRoot, runtimeDir].sort());
    expect(gates).toHaveLength(3);
    expect(gates[0].observedPaths).toEqual([resolve(runtimeDir, "state.json"), resolve(runtimeDir, "ports.json")]);
    expect(gates[1].observedPaths).toEqual([resolve(gitDir, "HEAD"), resolve(gitDir, "packed-refs")]);
    expect(gates[2].observedPaths).toEqual([resolve(localRoot, "instances.json")]);
    expect(sandbox.launcherStateFileHintGates).toEqual(gates);

    const runtimeHint = callbacks.get(runtimeDir)!;
    const gitHint = callbacks.get(gitDir)!;
    const instancesHint = callbacks.get(localRoot)!;

    // Runtime dir: named state/port evidence triggers; logs and temp writes don't.
    runtimeHint("rename", "state.json");
    runtimeHint("change", "ports.json");
    for (const file of ["backend.stdout.log", "backend.stderr.log", "state.json.123.tmp", "desktop-entry-python.log"]) {
      runtimeHint("change", file);
    }
    expect(hint).toHaveBeenCalledTimes(2);

    // LOCALAPPDATA: the instance registry lockdir lifecycle is the refresh's
    // own side effect — zero hints, and not even a gate consultation.
    for (const [event, name] of [
      ["rename", "instances.json.lockdir"],
      ["change", "instances.json.lockdir"],
      ["rename", "instances.json.lockdir.release-4242-0f3a9c"],
      ["change", "instances.json.lockdir.release-4242-0f3a9c"],
      ["change", "instances.json.tmp-9182"],
    ] as const) {
      instancesHint(event, name);
    }
    expect(hint).toHaveBeenCalledTimes(2);
    expect(gates[2].consumeNullFilenameEvent).not.toHaveBeenCalled();
    instancesHint("rename", "instances.json");
    expect(hint).toHaveBeenCalledTimes(3);

    // .git: HEAD/ORIG_HEAD/packed-refs prove branch/commit movement; index
    // churn is produced by git status inside the refresh itself.
    gitHint("change", "index");
    gitHint("rename", "index.lock");
    gitHint("rename", "refs-heads-codex.lock");
    expect(hint).toHaveBeenCalledTimes(3);
    expect(gates[1].consumeNullFilenameEvent).not.toHaveBeenCalled();
    gitHint("change", "HEAD");
    gitHint("rename", "ORIG_HEAD");
    gitHint("change", "packed-refs");
    expect(hint).toHaveBeenCalledTimes(6);

    // Null events on every target consult only that target's gate, and never
    // schedule on their own.
    runtimeHint("rename", null);
    gitHint("change", null);
    instancesHint("rename", null);
    expect(hint).toHaveBeenCalledTimes(6);
    expect(gates[0].consumeNullFilenameEvent).toHaveBeenCalledTimes(1);
    expect(gates[1].consumeNullFilenameEvent).toHaveBeenCalledTimes(1);
    expect(gates[2].consumeNullFilenameEvent).toHaveBeenCalledTimes(1);
    (gates[1].consumeNullFilenameEvent as Mock).mockReturnValue(true);
    gitHint("change", null);
    expect(hint).toHaveBeenCalledTimes(7);
  });
});
