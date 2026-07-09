import { describe, expect, it } from "vitest";

import type { DataProcessingRunListPayload } from "../../api/types";
import {
  selectDefaultSourceCollectionRun,
  sourceCollectionRunCandidateMetric,
  sourceCollectionRunRecordCount,
} from "./teamsRouteViewModel";

describe("teams route source collection view model", () => {
  function runFixture(
    runId: string,
    summary: Partial<DataProcessingRunListPayload["runs"][number]["summary"]> = {},
    extra: Partial<DataProcessingRunListPayload["runs"][number]> = {},
  ): DataProcessingRunListPayload["runs"][number] {
    return {
      schemaVersion: 1,
      runId,
      profileId: "source-collection",
      title: runId,
      status: "completed",
      scope: {},
      metadata: {
        startedFrom: "team_workflow_source_collection",
        teamId: "research-team",
      },
      summary: {
        recordCount: 0,
        assignmentCount: 0,
        openAssignmentCount: 0,
        searchOpenAssignmentCount: 0,
        downstreamOpenAssignmentCount: 0,
        ...summary,
      },
      storage: {
        runPath: "",
        recordsPath: "",
        collectionAssignmentsPath: "",
        collectionOutputsPath: "",
        eventsPath: "",
      },
      createdAt: "2026-07-02T00:00:00Z",
      updatedAt: "2026-07-02T00:00:00Z",
      ...extra,
    };
  }

  it("defaults from an empty latest run to the first historical run with records", () => {
    const latestEmpty = runFixture("latest-empty");
    const historicalWithRecords = runFixture("historical-records", { recordCount: 7 });

    expect(selectDefaultSourceCollectionRun([latestEmpty, historicalWithRecords], "")?.runId).toBe("historical-records");
  });

  it("keeps an explicitly selected empty run visible", () => {
    const latestEmpty = runFixture("latest-empty");
    const historicalWithRecords = runFixture("historical-records", { recordCount: 7 });

    expect(selectDefaultSourceCollectionRun([latestEmpty, historicalWithRecords], "latest-empty")?.runId).toBe("latest-empty");
  });

  it("reads fallback record and candidate counts from source collection summaries", () => {
    const run = runFixture("nested-counts", {}, {
      scope: { sourceCollectionSummary: { rawRecordCount: 5 } },
      metadata: { sourceCollectionSummary: { importedCount: 3 } },
    });

    expect(sourceCollectionRunRecordCount(run)).toBe(5);
    expect(sourceCollectionRunCandidateMetric(run)).toBe(3);
  });
});
