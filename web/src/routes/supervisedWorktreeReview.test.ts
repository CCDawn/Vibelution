import { describe, expect, it } from "vitest";

import type { SupervisedWorktreeRun } from "../api/types";
import { isSelfEvolutionWorktreeRun } from "./supervisedWorktreeReview";

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
