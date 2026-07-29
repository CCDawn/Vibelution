import { describe, expect, it } from "vitest";

import {
  sourceCollectionSummaryQuerySeedText,
  type SourceCollectionSummaryPayload,
} from "./sourceCollectionRunQueryModel";

describe("sourceCollectionSummaryQuerySeedText", () => {
  it("returns the selected run search-plan seeds", () => {
    const payload: SourceCollectionSummaryPayload = {
      schemaVersion: 1,
      teamId: "research-team",
      runId: "run-sci-098",
      status: "ready",
      searchPlan: {
        planId: "searchplan-sci-098",
        querySeeds: [
          "sleep synaptic homeostasis",
          "sleep glymphatic clearance",
        ],
        queryCount: 8,
      },
    };

    expect(sourceCollectionSummaryQuerySeedText(payload, "run-sci-098")).toBe(
      "sleep synaptic homeostasis\nsleep glymphatic clearance",
    );
  });

  it("does not project seeds from a stale run response", () => {
    expect(sourceCollectionSummaryQuerySeedText({
      schemaVersion: 1,
      teamId: "research-team",
      runId: "run-old",
      status: "ready",
      searchPlan: {
        querySeeds: ["stale query"],
      },
    }, "run-current")).toBe("");
  });
});
