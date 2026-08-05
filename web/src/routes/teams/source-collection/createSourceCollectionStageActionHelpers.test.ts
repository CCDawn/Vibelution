import { describe, expect, it } from "vitest";

import { createSourceCollectionStageActionHelpers } from "./createSourceCollectionStageActionHelpers";

describe("createSourceCollectionStageActionHelpers", () => {
  it("marks launch-active stages as waiting for writeback", () => {
    const helpers = createSourceCollectionStageActionHelpers({
      lang: "zh",
      sourceCollectionStageSessionTaskPendingStageId: null,
      sourceCollectionStageLaunchActive: (stageId) => stageId === "finding",
      sourceCollectionActionReadiness: (disabled, reason, loading) => ({
        disabled,
        reason,
        loading: Boolean(loading),
        actionLabel: reason,
      }),
      selectedTeamStartSourceCollectionStageTaskPending: false,
      sourceCollectionActionBusyReason: "busy",
      sourceCollectionStageCardById: new Map(),
      sourceCollectionCollectionActionReadiness: {
        disabled: false,
        reason: "",
        loading: false,
        actionLabel: "collect",
      },
      sourceCollectionActionNoInputReason: "no input",
      sourceCollectionCandidateExtractionActionReadiness: {
        disabled: true,
        reason: "need extract",
        loading: false,
        actionLabel: "extract",
      },
      sourceCollectionScreeningActionReadiness: {
        disabled: true,
        reason: "need screen",
        loading: false,
        actionLabel: "screen",
      },
      sourceCollectionGraphActionReadiness: {
        disabled: false,
        reason: "",
        loading: false,
        actionLabel: "graph",
      },
      sourceCollectionMemoryActionReadiness: {
        disabled: false,
        reason: "",
        loading: false,
        actionLabel: "memory",
      },
    });
    const readiness = helpers.sourceCollectionStageActionReadinessFor("finding");
    expect(readiness.disabled).toBe(true);
    expect(readiness.reason).toContain("等待 Agent 回写");
    expect(helpers.sourceCollectionStageActionLabelFor("finding", "fallback")).toContain("等待 Agent 回写");
  });
});
