import { describe, expect, it } from "vitest";

import apiSource from "./sourceCollection.ts?raw";
import queriesSource from "../routes/teams/useSourceCollectionRunQueries.ts?raw";
import startMutationsSource from "../routes/teams/useTeamWorkflowStartMutations.ts?raw";

describe("source-collection catalog API", () => {
  it("owns the selected-run summary transport", () => {
    expect(apiSource).toContain("export function fetchSourceCollectionSummary");
    expect(apiSource).toContain("/workflow-orchestration/source-collection/summary");
    expect(apiSource).toContain('search.set("runId", options.runId)');
  });

  it("keeps React Query orchestration free of the summary path", () => {
    expect(queriesSource).toContain("fetchSourceCollectionSummary");
    expect(queriesSource).not.toContain("/workflow-orchestration/source-collection/summary");
  });
});

describe("source-collection start/session write API", () => {
  it("owns run start, agent-session context, and stage-session task transports", () => {
    expect(apiSource).toContain("export function startSourceCollectionRun");
    expect(apiSource).toContain("export function seedSourceCollectionAgentSessionContext");
    expect(apiSource).toContain("export function startSourceCollectionStageSessionTask");
    expect(apiSource).toContain("/workflow-orchestration/source-collection-runs");
    expect(apiSource).toContain("/agent-session-context");
    expect(apiSource).toContain("/stage-session-tasks");
  });

  it("keeps start mutations free of those write paths", () => {
    expect(startMutationsSource).toContain("startSourceCollectionRun(");
    expect(startMutationsSource).toContain("seedSourceCollectionAgentSessionContext(");
    expect(startMutationsSource).toContain("startSourceCollectionStageSessionTask(");
    expect(startMutationsSource).not.toContain("/agent-session-context");
    expect(startMutationsSource).not.toContain("/stage-session-tasks");
    expect(startMutationsSource).not.toContain("/workflow-orchestration/source-collection-runs");
  });
});
