import { describe, expect, it } from "vitest";

import type { EvolutionActiveRun } from "../api/types";
import {
  parseRunStreamSnapshot,
  requireEvolutionRunSnapshot,
  selectRunSnapshotWithRunId,
  selectSupervisedRunStreamTarget,
  shouldIgnoreActiveRunSnapshot,
} from "./evolutionLiveRun";

function run(runId: string, status: string) {
  return { runId, status } as EvolutionActiveRun;
}

describe("evolutionLiveRun", () => {
  it("uses the active run snapshot while it is still live", () => {
    expect(selectSupervisedRunStreamTarget(run("run-1", "running"), null)?.runId).toBe("run-1");
  });

  it("ignores a stale active snapshot when the same local run is already terminal", () => {
    const activeRun = run("run-1", "running");
    const localTerminal = run("run-1", "cancelled");

    expect(shouldIgnoreActiveRunSnapshot(activeRun, localTerminal)).toBe(true);
    expect(selectSupervisedRunStreamTarget(activeRun, localTerminal)).toBeNull();
  });

  it("keeps monitoring a newer active run after an older local run finished", () => {
    expect(selectSupervisedRunStreamTarget(run("run-2", "queued"), run("run-1", "cancelled"))?.runId).toBe("run-2");
  });

  it("falls back to the local live run while active-run query is empty", () => {
    expect(selectSupervisedRunStreamTarget(null, run("run-1", "paused"))?.runId).toBe("run-1");
  });

  it("rejects mutation success payloads without a run id", () => {
    expect(requireEvolutionRunSnapshot(run("run-1", "queued"), "self-evolution").runId).toBe("run-1");

    expect(() => requireEvolutionRunSnapshot(null, "self-evolution")).toThrow("self-evolution");
    expect(() => requireEvolutionRunSnapshot({} as EvolutionActiveRun, "self-evolution")).toThrow("runId");
    expect(() => requireEvolutionRunSnapshot({ runId: "   " } as EvolutionActiveRun, "supervised")).toThrow("runId");
  });

  it("uses the action label when rejecting control action payloads", () => {
    expect(() => requireEvolutionRunSnapshot({} as EvolutionActiveRun, "self-evolution pause")).toThrow(
      "self-evolution pause response did not include a runId.",
    );
    expect(() => requireEvolutionRunSnapshot({} as EvolutionActiveRun, "supervised terminate")).toThrow(
      "supervised terminate response did not include a runId.",
    );
  });

  it("ignores query snapshots without a run id before updating live state", () => {
    expect(selectRunSnapshotWithRunId(run("run-1", "running"))?.runId).toBe("run-1");
    expect(selectRunSnapshotWithRunId(null)).toBeNull();
    expect(selectRunSnapshotWithRunId({} as EvolutionActiveRun)).toBeNull();
    expect(selectRunSnapshotWithRunId({ runId: "   " } as EvolutionActiveRun)).toBeNull();
  });

  it("parses only SSE snapshot payloads whose run id matches the event envelope", () => {
    expect(
      parseRunStreamSnapshot<EvolutionActiveRun>(
        JSON.stringify({
          runId: "run-1",
          snapshot: run("run-1", "running"),
        }),
        "supervised SSE",
      )?.runId,
    ).toBe("run-1");

    expect(parseRunStreamSnapshot<EvolutionActiveRun>("not-json", "supervised SSE")).toBeNull();
    expect(
      parseRunStreamSnapshot<EvolutionActiveRun>(
        JSON.stringify({
          snapshot: run("run-1", "running"),
        }),
        "supervised SSE",
      ),
    ).toBeNull();
    expect(parseRunStreamSnapshot<EvolutionActiveRun>(JSON.stringify({ runId: "run-1", snapshot: {} }), "supervised SSE")).toBeNull();
    expect(
      parseRunStreamSnapshot<EvolutionActiveRun>(
        JSON.stringify({
          runId: "run-1",
          snapshot: run("run-2", "running"),
        }),
        "supervised SSE",
      ),
    ).toBeNull();
  });
});
