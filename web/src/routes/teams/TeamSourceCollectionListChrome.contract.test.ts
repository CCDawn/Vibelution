import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");

describe("SC list chrome inject extraction", () => {
  it("TeamsRoute uses filter/pagination/stage-agents injects", () => {
    expect(routeSource).toContain("TeamSourceCollectionFilterBarInject");
    expect(routeSource).toContain("TeamSourceCollectionPaginationInject");
    expect(routeSource).toContain("TeamSourceCollectionStageAgentsInject");
    expect(routeSource).toContain("buildSourceCollectionControlsMetricsBag");
    expect(routeSource).toContain("buildSourceCollectionControlsFeedbackBag");
    // Inject components may appear in import names; workspace panels themselves must not mount.
    expect(routeSource).not.toMatch(/<TeamSourceCollectionFilterBar[\s>]/);
    expect(routeSource).not.toMatch(/<TeamSourceCollectionPagination[\s>]/);
    expect(routeSource).not.toMatch(/<TeamSourceCollectionStageAgentsPanel[\s>]/);
    expect(routeSource).not.toContain("source-step-${stageId}-");
  });
});
