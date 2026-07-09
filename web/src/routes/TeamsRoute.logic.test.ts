import { describe, expect, it } from "vitest";

import {
  deriveSourceCollectionExcludedRecoveryState,
  deriveSourceCollectionDisplayState,
  linkedRoomRefetchInterval,
  sourceCollectionActiveWorkRunFromRuntime,
  sourceCollectionStableCountText,
} from "./TeamsRoute";

describe("TeamsRoute polling policy", () => {
  it("polls linked rooms quickly only while an active round is settling", () => {
    expect(linkedRoomRefetchInterval(true, "running")).toBe(5_000);
    expect(linkedRoomRefetchInterval(true, "stopping")).toBe(5_000);
    expect(linkedRoomRefetchInterval(true, "ready")).toBe(30_000);
  });

  it("stops linked room polling while the page is hidden", () => {
    expect(linkedRoomRefetchInterval(false, "running")).toBe(false);
    expect(linkedRoomRefetchInterval(false, "ready")).toBe(false);
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

describe("source collection extraction recovery", () => {
  it("classifies all remaining extraction gaps as excluded instead of recoverable import work", () => {
    const state = deriveSourceCollectionExcludedRecoveryState({
      lang: "zh",
      excludedCount: 10,
      missingCount: 10,
      importFailedCount: 10,
      importPendingRecordCount: 10,
    });

    expect(state.blockedByExcludedSources).toBe(true);
    expect(state.recoverText).toBe("已排除 10");
    expect(state.summary).toContain("剩余 10 条资料已被排除");
    expect(state.primaryActionText).toBe("查看排除原因");
    expect(state.panelTitle).toBe("提炼排除项确认");
    expect(state.statusLabel).toBe("可继续推进");
    expect(state.failedLabel).toBe("缺口处理");
    expect(state.recoverLabel).toBe("已排除");
  });

  it("does not block normal recovery when excluded records are only part of the remaining gaps", () => {
    const state = deriveSourceCollectionExcludedRecoveryState({
      lang: "zh",
      excludedCount: 2,
      missingCount: 10,
      importFailedCount: 2,
      importPendingRecordCount: 10,
    });

    expect(state.blockedByExcludedSources).toBe(false);
    expect(state.recoverText).toBe("");
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
