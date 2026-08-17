import { describe, expect, it } from "vitest";

import apiSource from "./researchLoop.ts?raw";
import mutationsSource from "../routes/teams/useTeamExperimentLoopMutations.ts?raw";
import secondarySource from "../routes/teams/useTeamResearchSecondaryQueries.ts?raw";

describe("research-loop API", () => {
  it("owns research-loop status and write transports", () => {
    expect(apiSource).toContain("export function fetchResearchLoopTemplates");
    expect(apiSource).toContain("export function fetchResearchLoopStatus");
    expect(apiSource).toContain("export function createResearchLoop");
    expect(apiSource).toContain("export function recordResearchLoopEvidence");
    expect(apiSource).toContain("export function recordResearchLoopDecision");
    expect(apiSource).toContain("export function materializeResearchLoopIterationDesign");
    expect(apiSource).toContain("/workflow-orchestration/research-loop/templates");
    expect(apiSource).toContain("/workflow-orchestration/research-loop/status");
    expect(apiSource).toContain("/workflow-orchestration/research-loop/loops");
    expect(apiSource).toContain("/evidence");
    expect(apiSource).toContain("/decision");
    expect(apiSource).toContain("/design-draft");
  });

  it("keeps hooks free of extracted research-loop paths", () => {
    expect(secondarySource).toContain("fetchResearchLoopTemplates<");
    expect(secondarySource).toContain("fetchResearchLoopStatus<");
    expect(secondarySource).not.toContain("/workflow-orchestration/research-loop/templates");
    expect(secondarySource).not.toContain("/workflow-orchestration/research-loop/status");
    expect(mutationsSource).toContain("createResearchLoop<");
    expect(mutationsSource).toContain("recordResearchLoopEvidence<");
    expect(mutationsSource).toContain("recordResearchLoopDecision<");
    expect(mutationsSource).toContain("materializeResearchLoopIterationDesign<");
    expect(mutationsSource).not.toContain("/workflow-orchestration/research-loop/loops");
    expect(mutationsSource).not.toContain("/design-draft");
  });
});
