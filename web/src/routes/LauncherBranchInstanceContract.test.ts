import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { CLIENT_START_BLOCK_REFRESH_REQUIRED, type LauncherBranchInstance } from "../api/launcher";
import {
  ADMISSION_BLOCK_REASONS,
  IN_FLIGHT_LIFECYCLE_STATES,
  instanceHasLiveRuntime,
  instanceRuntimeState,
  LIVE_LIFECYCLE_STATES,
} from "./LauncherBranchInstancesPanel.model";

type ContractFixture = {
  schemaVersion: number;
  lifecycleStates: {
    payload: string[];
    terminal: string[];
    inFlight: string[];
    live: string[];
    webRuntimeStates: string[];
    webStateMapping: Record<string, string>;
  };
  liveRuntimeSignals: {
    python: string[];
    typescript: string[];
    note: string;
  };
  admissionBlockReasons: {
    electron: string[];
    web: string[];
  };
  clientOnlyCodes: {
    startBlockReasons: { code: string; producer: string; note: string }[];
  };
};

// Same cross-port fixture directory the Python and Electron lifecycle tests
// read from; the web contract test joins them here.
const fixturePath = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "..",
  "desktop",
  "electron",
  "src",
  "lifecycle",
  "__fixtures__",
  "launcherInstanceContract.cases.json",
);

const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as ContractFixture;

function instanceWithRuntime(overrides: {
  lifecycleState?: string;
  backendAlive?: boolean;
  backendListening?: boolean;
  windowOpen?: boolean;
  flatAlive?: boolean;
}): LauncherBranchInstance {
  const lifecycleState = overrides.lifecycleState ?? "closed";
  return {
    id: "contract-fixture",
    kind: "worktree",
    branch: "codex/contract-fixture",
    path: "/tmp/contract-fixture",
    displayPath: "/tmp/contract-fixture",
    head: "0000000",
    current: false,
    legacy: false,
    dirty: false,
    checkedOut: true,
    alive: Boolean(overrides.flatAlive),
    observedState: "",
    port: 0,
    runtime: {
      lifecycleState,
      desiredState: "open",
      observedState: "",
      phase: "steady",
      backend: {
        alive: Boolean(overrides.backendAlive),
        healthy: false,
        listening: Boolean(overrides.backendListening),
        port: 0,
        portReserved: false,
        portConflict: false,
        pid: 0,
      },
      frontend: { mode: "bundled_static_dist", ready: false },
      window: { open: Boolean(overrides.windowOpen), pid: 0, title: "", titleObserved: false },
    },
  } as unknown as LauncherBranchInstance;
}

describe("launcher instance cross-port contract", () => {
  it("covers every payload lifecycle state with the pinned web mapping and no ghost value", () => {
    const payload = fixture.lifecycleStates.payload;
    expect(new Set(payload).size).toBe(payload.length);
    expect(Object.keys(fixture.lifecycleStates.webStateMapping).sort()).toEqual([...payload].sort());
    for (const state of payload) {
      const runtimeState = instanceRuntimeState(instanceWithRuntime({ lifecycleState: state }));
      expect(runtimeState, `payload state ${state}`).toBe(fixture.lifecycleStates.webStateMapping[state]);
      expect(fixture.lifecycleStates.webRuntimeStates).toContain(runtimeState);
    }
  });

  it("pins the in-flight lifecycle state set", () => {
    const inFlight = fixture.lifecycleStates.inFlight;
    expect(IN_FLIGHT_LIFECYCLE_STATES.size).toBe(inFlight.length);
    for (const state of inFlight) {
      expect(IN_FLIGHT_LIFECYCLE_STATES.has(state)).toBe(true);
    }
    for (const state of inFlight) {
      expect(fixture.lifecycleStates.payload).toContain(state);
      expect(fixture.lifecycleStates.terminal).not.toContain(state);
    }
  });

  it("pins the live lifecycle state set and keeps it disjoint from the terminals", () => {
    const live = fixture.lifecycleStates.live;
    expect(LIVE_LIFECYCLE_STATES.size).toBe(live.length);
    for (const state of live) {
      expect(LIVE_LIFECYCLE_STATES.has(state)).toBe(true);
      expect(fixture.lifecycleStates.payload).toContain(state);
      expect(fixture.lifecycleStates.terminal).not.toContain(state);
    }
  });

  it("locks the TypeScript 3-signal live-runtime rule, including the Python 5-signal divergence", () => {
    expect(fixture.liveRuntimeSignals.typescript).toEqual([
      "runtime.backend.alive",
      "runtime.backend.listening",
      "runtime.window.open",
    ]);
    const base = { backendAlive: false, backendListening: false, windowOpen: false };
    expect(instanceHasLiveRuntime(instanceWithRuntime(base))).toBe(false);
    expect(instanceHasLiveRuntime(instanceWithRuntime({ ...base, backendAlive: true }))).toBe(true);
    expect(instanceHasLiveRuntime(instanceWithRuntime({ ...base, backendListening: true }))).toBe(true);
    expect(instanceHasLiveRuntime(instanceWithRuntime({ ...base, windowOpen: true }))).toBe(true);
    // Divergence pinned: Python's _item_has_live_runtime also honors the flat
    // item.alive flag (and the isolated backend probe); web does not.
    expect(fixture.liveRuntimeSignals.python).toContain("item.alive");
    expect(instanceHasLiveRuntime(instanceWithRuntime({ flatAlive: true }))).toBe(false);
  });

  it("pins the admission block reason vocabulary against the Electron producer", () => {
    const webReasons = fixture.admissionBlockReasons.web;
    expect(ADMISSION_BLOCK_REASONS.size).toBe(webReasons.length);
    for (const reason of webReasons) {
      expect(ADMISSION_BLOCK_REASONS.has(reason)).toBe(true);
      expect(fixture.admissionBlockReasons.electron).toContain(reason);
    }
  });

  it("pins launcher_refresh_required as a client-only code outside the backend vocabulary", () => {
    const clientOnly = fixture.clientOnlyCodes.startBlockReasons;
    expect(clientOnly).toHaveLength(1);
    expect(clientOnly[0].code).toBe(CLIENT_START_BLOCK_REFRESH_REQUIRED);
    expect(fixture.admissionBlockReasons.electron).not.toContain(CLIENT_START_BLOCK_REFRESH_REQUIRED);
    expect(fixture.lifecycleStates.payload).not.toContain(CLIENT_START_BLOCK_REFRESH_REQUIRED);
  });
});
