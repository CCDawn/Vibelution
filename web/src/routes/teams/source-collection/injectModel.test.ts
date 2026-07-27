import { describe, expect, it } from "vitest";

import {
  buildSourceCollectionManualWritebackAssignmentOptions,
  canStartSourceCollectionRun,
  canSubmitSourceCollectionManualWriteback,
  resolveSourceCollectionManualWritebackAssignmentValue,
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
});
