import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const hostSource = readFileSync(new URL("./TeamResearchWorkflowPanelHost.tsx", import.meta.url), "utf8");

describe("TeamResearchWorkflowPanelHost extraction contract", () => {
  it("TeamsRoute uses one host helper from both board and canvas shells", () => {
    expect(routeSource).toContain(
      'import { TeamResearchWorkflowPanelHost } from "./teams/TeamResearchWorkflowPanelHost"',
    );
    expect(routeSource).toContain("function renderResearchWorkflowPanel()");
    expect(routeSource).toContain("function renderResearchWorkflowModules()");
    expect(routeSource.match(/\{renderResearchWorkflowPanel\(\)\}/g)?.length).toBe(2);
    // Host JSX appears once inside the helper, not duplicated per shell.
    expect(routeSource.match(/<TeamResearchWorkflowPanelHost[\s\S]*?>/g)?.length).toBe(1);
    // Stage modules are composed once.
    expect(routeSource.match(/<TeamsSourceCollectionPanel[\s\S]*?\/>/g)?.length).toBe(1);
    expect(routeSource.match(/<TeamWorkflowCoordinationStatusPanel[\s\S]*?\/>/g)?.length).toBe(1);
    expect(routeSource.match(/<TeamWorkflowCandidatePreviewPanel[\s\S]*?\/>/g)?.length).toBe(1);
  });

  it("host owns workflow section chrome, loading, and empty states", () => {
    expect(hostSource).toContain('id="research-workflow-overview"');
    expect(hostSource).toContain("Research workflow");
    expect(hostSource).toContain("Loading research workflow");
    expect(hostSource).toContain("Research workflow is not initialized yet.");
    expect(hostSource).toContain("Select research-team to view the Challenge Cup workflow.");
    expect(hostSource).toContain("children");
  });
});
