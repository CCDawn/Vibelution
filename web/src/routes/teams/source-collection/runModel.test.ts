import { describe, expect, it } from "vitest";

import type { DataProcessingRunListPayload } from "../../../api/types";
import {
  deriveSourceCollectionDisplayState,
  selectDefaultSourceCollectionRun,
  sourceCollectionActiveWorkRunFromRuntime,
  sourceCollectionRunCandidateMetric,
  sourceCollectionRunRecordCount,
  sourceCollectionStableCountText,
} from "./runModel";

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

describe("source collection run selection", () => {
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

describe("source collection display state", () => {
  const baseInput = {
    lang: "zh" as const,
    hasRun: true,
    startPending: false,
    searchPending: false,
    backgroundActive: false,
    recordOutputPending: false,
    extractionPending: false,
    sourceQualityPending: false,
    graphPending: false,
    knowledgeIngestionPending: false,
    failed: false,
    searchOpenAssignmentCount: 0,
    downstreamOpenAssignmentCount: 0,
    pendingScreeningCount: 0,
    rawRecordCount: 0,
    candidateCount: 0,
  };

  it("keeps starting separate from a real background search", () => {
    expect(deriveSourceCollectionDisplayState({ ...baseInput, startPending: true }).phase).toBe("starting");
    expect(deriveSourceCollectionDisplayState({ ...baseInput, backgroundActive: true }).phase).toBe("running");
  });

  it("shows a returned batch as continuable instead of still running", () => {
    const state = deriveSourceCollectionDisplayState({
      ...baseInput,
      searchOpenAssignmentCount: 3,
      rawRecordCount: 15,
      candidateCount: 15,
    });

    expect(state.phase).toBe("needs_continue");
    expect(state.active).toBe(false);
    expect(state.statusText).toBe("已返回一批");
    expect(state.decisionText).toContain("还有 3 个搜索任务可继续");
  });
});

describe("source collection loading labels", () => {
  it("keeps known counts visible while the selected batch is syncing", () => {
    expect(sourceCollectionStableCountText({
      loading: true,
      value: 44,
      lang: "zh",
      zhUnit: "条",
      enUnit: "records",
      loadingText: "加载中",
      syncingText: "同步中",
    })).toBe("44 条 · 同步中");
  });

  it("uses the loading label only when no stable count is known yet", () => {
    expect(sourceCollectionStableCountText({
      loading: true,
      value: 0,
      lang: "zh",
      zhUnit: "条",
      enUnit: "records",
      loadingText: "加载中",
      syncingText: "同步中",
    })).toBe("加载中");
  });
});

describe("source collection runtime active work", () => {
  it("uses runtime activeItems instead of stale accepted mutation snapshots", () => {
    const runtime = {
      workRuns: {
        active: {},
        activeItems: {
          source_collection_run: [
            { runId: "run-live", runKind: "source_collection_run", status: "running", leases: [] },
            { runId: "run-old", runKind: "source_collection_run", status: "completed", leases: [] },
          ],
        },
        latest: {},
      },
    };

    expect(sourceCollectionActiveWorkRunFromRuntime(runtime as never, "run-live")?.runId).toBe("run-live");
    expect(sourceCollectionActiveWorkRunFromRuntime(runtime as never, "run-old")).toBeNull();
  });
});
