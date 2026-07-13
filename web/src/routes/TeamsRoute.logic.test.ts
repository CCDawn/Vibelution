import { describe, expect, it } from "vitest";

import {
  deriveSourceCollectionExcludedRecoveryState,
  linkedRoomRefetchInterval,
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
