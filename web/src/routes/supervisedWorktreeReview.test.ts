import { describe, expect, it } from "vitest";

import type { SupervisedWorktreeRun } from "../api/types";
import {
  isSelfEvolutionWorktreeRun,
  readRecentSupervisedWorktreeRunId,
  rememberRecentSupervisedWorktreeRunId,
  selectRecentSupervisedWorktreeRun,
} from "./supervisedWorktreeReview";

function runWith(
  overrides: Partial<SupervisedWorktreeRun>,
): SupervisedWorktreeRun {
  return overrides as SupervisedWorktreeRun;
}

describe("isSelfEvolutionWorktreeRun", () => {
  it("does not misclassify a normal supervised run with an empty origin object", () => {
    expect(isSelfEvolutionWorktreeRun(runWith({
      runId: "swte-supervised",
      selfEvolutionOrigin: {},
      reviewGate: { required: false },
    }))).toBe(false);
  });

  it("recognizes explicit self-evolution provenance and review gates", () => {
    expect(isSelfEvolutionWorktreeRun(runWith({
      runId: "swte-self-origin",
      selfEvolutionOrigin: { sourceTrack: "self_evolution" },
    }))).toBe(true);
    expect(isSelfEvolutionWorktreeRun(runWith({
      runId: "swte-self-review",
      selfEvolutionOrigin: {},
      reviewGate: { required: true },
    }))).toBe(true);
  });
});

describe("selectRecentSupervisedWorktreeRun", () => {
  it("keeps the terminal record for the supervised run seen by the current page", () => {
    const previousRun = runWith({ runId: "swte-previous", status: "done" });
    const currentRun = runWith({ runId: "swte-current", status: "failed" });

    expect(selectRecentSupervisedWorktreeRun(
      [previousRun, currentRun],
      "swte-current",
    )).toBe(currentRun);
  });

  it("does not select stale history or a self-evolution review run", () => {
    const selfRun = runWith({
      runId: "swte-self",
      status: "done",
      selfEvolutionOrigin: { sourceTrack: "self_evolution" },
    });

    expect(selectRecentSupervisedWorktreeRun([selfRun], null)).toBeNull();
    expect(selectRecentSupervisedWorktreeRun([selfRun], "swte-missing")).toBeNull();
    expect(selectRecentSupervisedWorktreeRun([selfRun], "swte-self")).toBeNull();
  });
});

describe("recent supervised worktree run storage", () => {
  it("survives a route remount in the current browser tab", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };

    rememberRecentSupervisedWorktreeRunId(storage, " swte-current ");

    expect(readRecentSupervisedWorktreeRunId(storage)).toBe("swte-current");
  });

  it("degrades safely when browser storage is unavailable", () => {
    const storage = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };

    expect(readRecentSupervisedWorktreeRunId(storage)).toBeNull();
    expect(() => rememberRecentSupervisedWorktreeRunId(storage, "swte-current")).not.toThrow();
  });
});
