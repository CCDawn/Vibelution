import { describe, expect, it } from "vitest";

import {
  buildSourceCollectionFilterBarOptions,
  buildSourceCollectionManualWritebackAssignmentOptions,
  canStartSourceCollectionRun,
  canSubmitSourceCollectionManualWriteback,
  resolveSourceCollectionManualWritebackAssignmentValue,
  resolveSourceCollectionPaginationView,
  shouldShowLocalScanRootsField,
  sourceCollectionModeFieldsVisible,
} from "./injectModel";

describe("source-collection injectModel", () => {
  it("gates mode fields and local roots", () => {
    expect(sourceCollectionModeFieldsVisible(true)).toBe(true);
    expect(sourceCollectionModeFieldsVisible(false)).toBe(false);
    expect(shouldShowLocalScanRootsField("mixed")).toBe(true);
    expect(shouldShowLocalScanRootsField("web_search")).toBe(false);
  });

  it("builds writeback assignment options and submit guards", () => {
    const options = buildSourceCollectionManualWritebackAssignmentOptions(
      [{ assignmentId: "a1", agentRole: "source_finder", status: "open" }],
      "zh",
    );
    expect(options[0]?.id).toBe("a1");
    expect(options[0]?.label).toContain("·");
    expect(resolveSourceCollectionManualWritebackAssignmentValue("", "selected")).toBe("selected");
    expect(canSubmitSourceCollectionManualWriteback({
      teamId: "t1",
      runId: "r1",
      assignmentId: "a1",
      hasRecord: true,
    })).toBe(true);
    expect(canStartSourceCollectionRun({ teamId: "t1", canStart: true, startPending: false })).toBe(true);
    expect(canStartSourceCollectionRun({ teamId: "t1", canStart: true, startPending: true })).toBe(false);
  });

  it("builds filter-bar options and pagination view", () => {
    const options = buildSourceCollectionFilterBarOptions({
      filters: ["all", "web"] as const,
      counts: { all: 3, web: 1 },
      selected: "web",
      loading: false,
      loadingAllText: "loading",
      labelFor: (filter) => filter,
    });
    expect(options).toEqual([
      { key: "all", label: "all", count: 3, selected: false },
      { key: "web", label: "web", count: 1, selected: true },
    ]);
    expect(resolveSourceCollectionPaginationView({ total: 8, page: 1, pageSize: 8 })).toBeNull();
    expect(resolveSourceCollectionPaginationView({ total: 20, page: 2, pageSize: 8 })).toEqual({
      page: 2,
      pageCount: 3,
      pageSize: 8,
      total: 20,
    });
  });
});
