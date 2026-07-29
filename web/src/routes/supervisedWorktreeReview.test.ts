import { describe, expect, it } from "vitest";

import type { SupervisedWorktreeRun } from "../api/types";
import {
  isSelfEvolutionWorktreeRun,
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
