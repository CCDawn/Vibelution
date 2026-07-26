import { describe, expect, it } from "vitest";

import {
  sourceCollectionPageSlice,
  sourceCollectionStageAgentBindingsForStage,
  sourceCollectionStageChatReturnLabel,
  sourceCollectionStageDisplayState,
  sourceCollectionStageLaunchActive,
  sourceCollectionStageLaunchSummary,
} from "./teamSourceCollectionShellModel";

describe("teamSourceCollectionShellModel", () => {
  it("slices pages and filters stage agent bindings", () => {
    const items = Array.from({ length: 10 }, (_, index) => index + 1);
    const page = sourceCollectionPageSlice(items, 2, 4);
    expect(page.items).toEqual([5, 6, 7, 8]);
    expect(page.page).toBe(2);
    expect(page.pageCount).toBe(3);

    const bindings = sourceCollectionStageAgentBindingsForStage("finding", [
      { key: "source_ingestor" },
      { key: "source_finder" },
      { key: "other" },
    ]);
    expect(bindings.map((item) => item.key)).toEqual(["source_finder"]);
  });

  it("computes launch active/summary and display state", () => {
    expect(sourceCollectionStageLaunchActive("finding", {
      pendingStageId: "finding",
      pendingTaskIds: [],
      writebackSyncActive: false,
      latestTaskId: "",
      latestTaskStatus: "",
      projectionStatus: "",
    })).toBe(true);
    expect(sourceCollectionStageLaunchSummary("finding", "finding", "zh")).toContain("已启动");
    expect(sourceCollectionStageDisplayState(true, "idle")).toBe("active");
    expect(sourceCollectionStageChatReturnLabel(
      "finding",
      "zh",
      {
        finding: { zh: "资料寻找 Agent 私聊", en: "finder" },
        extraction: { zh: "x", en: "x" },
        relations: { zh: "x", en: "x" },
        ingestion: { zh: "x", en: "x" },
      },
    )).toContain("资料寻找");
  });
});
