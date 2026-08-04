import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const modulesSource = readFileSync(new URL("./TeamResearchWorkflowStageModules.tsx", import.meta.url), "utf8");

describe("TeamResearchWorkflowStageModules extraction contract", () => {
  it("TeamsRoute composes stage modules once via the extracted component", () => {
    expect(routeSource).toContain(
      'import { TeamResearchWorkflowStageModules } from "./teams/TeamResearchWorkflowStageModules"',
    );
    expect(routeSource).toContain("function renderResearchWorkflowModules()");
    expect(routeSource.match(/<TeamResearchWorkflowStageModules[\s\S]*?\/>/g)?.length).toBe(1);
    // Stage panel JSX no longer lives on the route.
    expect(routeSource).not.toContain("<TeamsSourceCollectionPanel");
    expect(routeSource).not.toContain("<TeamWorkflowCoordinationStatusPanel");
    expect(routeSource).not.toContain("<TeamWorkflowCandidatePreviewPanel");
    expect(routeSource).not.toContain("<TeamWorkflowSourceQualityStatusPanel");
  });

  it("modules host visibility-gated stage panels", () => {
    expect(modulesSource).toContain("visibility.sourceCollection");
    expect(modulesSource).toContain("visibility.coordination");
    expect(modulesSource).toContain("visibility.ingestion");
    expect(modulesSource).toContain("visibility.graph");
    expect(modulesSource).toContain("visibility.candidates");
    expect(modulesSource).toContain("TeamsSourceCollectionPanel");
    expect(modulesSource).toContain("TeamWorkflowCoordinationStatusPanel");
    expect(modulesSource).toContain("TeamWorkflowCandidatePreviewPanel");
    expect(modulesSource).toContain("资料搜索执行");
    expect(modulesSource).toContain("候选仓库还没有资料、笔记或机制候选");
  });
});
