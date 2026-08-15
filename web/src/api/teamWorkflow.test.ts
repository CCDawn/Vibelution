import { describe, expect, it } from "vitest";

import apiSource from "./teamWorkflow.ts?raw";
import resourcesSource from "../routes/teams/useResearchWorkflowResources.ts?raw";

describe("team workflow orchestration API", () => {
  it("owns GET/PUT workflow-orchestration transports", () => {
    expect(apiSource).toContain("export function fetchTeamWorkflowOrchestration");
    expect(apiSource).toContain("export function ensureTeamWorkflowOrchestration");
    expect(apiSource).toContain("/workflow-orchestration");
    expect(apiSource).toContain('method: "PUT"');
  });

  it("keeps research workflow resources free of the orchestration path", () => {
    expect(resourcesSource).toContain("fetchTeamWorkflowOrchestration(");
    expect(resourcesSource).not.toContain("`/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration`");
  });
});
