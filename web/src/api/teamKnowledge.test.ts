import { describe, expect, it } from "vitest";

import apiSource from "./teamKnowledge.ts?raw";
import mutationsSource from "../routes/teams/useTeamSourceCollectionMutations.ts?raw";
import resourcesSource from "../routes/teams/useResearchWorkflowResources.ts?raw";

describe("team knowledge API", () => {
  it("owns knowledge status and write transports", () => {
    expect(apiSource).toContain("export function fetchKnowledgeIngestionStatus");
    expect(apiSource).toContain("export function fetchTeamWorkflowCoordinationStatus");
    expect(apiSource).toContain("export function runKnowledgeIngestionPrecheck");
    expect(apiSource).toContain("export function extractSourceCollectionCandidates");
    expect(apiSource).toContain("export function ingestKnowledgeCollection");
    expect(apiSource).toContain("export function completeKnowledgeCollection");
    expect(apiSource).toContain("export function buildCandidateGraph");
    expect(apiSource).toContain("export function extractCandidateSourcePages");
    expect(apiSource).toContain("export function draftPaperNoteFromSourceCandidate");
  });

  it("keeps SC mutations and resources free of extracted knowledge paths", () => {
    expect(resourcesSource).toContain("fetchKnowledgeIngestionStatus(");
    expect(resourcesSource).toContain("fetchTeamWorkflowCoordinationStatus(");
    expect(resourcesSource).not.toContain("/knowledge-ingestion/status");
    expect(resourcesSource).not.toContain("/coordination/status");
    expect(mutationsSource).toContain("extractSourceCollectionCandidates(");
    expect(mutationsSource).toContain("buildCandidateGraph(");
    expect(mutationsSource).toContain("runKnowledgeIngestionPrecheck<");
    expect(mutationsSource).toContain("completeKnowledgeCollection(");
    expect(mutationsSource).not.toContain("/knowledge-collection/extract");
    expect(mutationsSource).not.toContain("/candidate-graph");
    expect(mutationsSource).not.toContain("knowledge-ingestion/precheck");
    expect(mutationsSource).not.toContain("/knowledge-collection/complete");
  });
});
