import { describe, expect, it } from "vitest";

import apiSource from "./researchProjectAgentTasks.ts?raw";
import hookSource from "../routes/teams/research-projects/useResearchProjectAgentTasks.ts?raw";

describe("research project Agent task API", () => {
  it("owns project list, task status, and task start transport", () => {
    expect(apiSource).toContain("/workflow-orchestration/research-projects");
    expect(apiSource).toContain("/agent-tasks/status");
    expect(apiSource).toContain("/agent-tasks/start");
    expect(apiSource).toContain("encodeURIComponent(projectId)");
  });

  it("keeps React Query orchestration free of direct transport calls", () => {
    expect(hookSource).not.toContain('from "../../../api/client"');
    expect(hookSource).not.toContain("fetchJson<");
    expect(hookSource).not.toContain("directSessionId");
  });
});
