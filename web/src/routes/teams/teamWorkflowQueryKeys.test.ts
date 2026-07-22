import { describe, expect, it } from "vitest";

import {
  sourceCollectionRunRecordsQueryKey,
  sourceCollectionStageTaskClickKey,
  sourceCollectionSummaryQueryKey,
  sourceCollectionSummaryQueryPrefix,
} from "./teamWorkflowQueryKeys";

describe("teamWorkflowQueryKeys", () => {
  it("builds stable source-collection summary keys", () => {
    expect(sourceCollectionSummaryQueryPrefix("team-a")).toEqual([
      "teams",
      "team-a",
      "workflow-orchestration",
      "source-collection",
      "summary",
    ]);
    expect(sourceCollectionSummaryQueryKey("team-a", "")).toEqual([
      "teams",
      "team-a",
      "workflow-orchestration",
      "source-collection",
      "summary",
      "latest",
    ]);
    expect(sourceCollectionRunRecordsQueryKey("run-1")).toEqual([
      "data-processing",
      "runs",
      "run-1",
      "records",
    ]);
  });

  it("creates unique stage-task click keys", () => {
    const left = sourceCollectionStageTaskClickKey("finding");
    const right = sourceCollectionStageTaskClickKey("finding");
    expect(left.startsWith("stage_task_click:finding:")).toBe(true);
    expect(right.startsWith("stage_task_click:finding:")).toBe(true);
    expect(left).not.toBe(right);
  });
});
