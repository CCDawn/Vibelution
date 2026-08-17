import { describe, expect, it } from "vitest";

import apiSource from "./teamResearchOps.ts?raw";
import mutationsSource from "../routes/teams/useTeamSourceCollectionMutations.ts?raw";
import resourcesSource from "../routes/teams/useResearchWorkflowResources.ts?raw";

describe("team research-ops API", () => {
  it("owns remaining research-ops status and write transports", () => {
    expect(apiSource).toContain("export function fetchPaperNoteChunkStatus");
    expect(apiSource).toContain("export function fetchSourceQualityStatus");
    expect(apiSource).toContain("export function fetchOfficialModelEvidenceStatus");
    expect(apiSource).toContain("export function assessCandidateSourceQuality");
    expect(apiSource).toContain("export function assessSourceQualityBatch");
    expect(apiSource).toContain("export function planPaperNoteChunks");
    expect(apiSource).toContain("/workflow-orchestration/paper-note-chunks/status");
    expect(apiSource).toContain("/workflow-orchestration/source-quality/status");
    expect(apiSource).toContain("/workflow-orchestration/official-model-evidence/status");
    expect(apiSource).toContain("/source-quality/assess");
    expect(apiSource).toContain("/source-quality/assess-batch");
    expect(apiSource).toContain("/paper-note-chunks/plan");
  });

  it("keeps unused typed research-ops routes behind named transports", () => {
    expect(apiSource).toContain("export function extractResearchMechanisms");
    expect(apiSource).toContain("export function mapResearchMechanisms");
    expect(apiSource).toContain("export function generateResearchHypotheses");
    expect(apiSource).toContain("export function proposeResearchIteration");
    expect(apiSource).toContain("export function exportResearchDeliverables");
    expect(apiSource).toContain("export function validateResearchPrd");
    expect(apiSource).toContain("export function syncOfficialKnowledgeGraph");
    expect(apiSource).toContain("export function rollbackOfficialKnowledgeGraph");
    expect(apiSource).toContain("export function submitStewardPackKnowledgeIngestion");
    expect(apiSource).toContain("export function reviewStewardPackKnowledgeIngestion");
    expect(apiSource).toContain("export function createWorkflowTransfer");
    expect(apiSource).toContain("export function decideWorkflowTransfer");
    expect(apiSource).toContain("export function createLocalResearchModelTask");
    expect(apiSource).toContain("export function recordLocalResearchModelOutput");
    expect(apiSource).toContain("export function invokeLocalResearchModel");
    expect(apiSource).toContain("export function registerOfficialModelEvidence");
    expect(apiSource).not.toContain("/research/review/decide");
  });

  it("keeps resources and SC mutations free of extracted research-ops paths", () => {
    expect(resourcesSource).toContain("fetchOfficialModelEvidenceStatus<");
    expect(resourcesSource).toContain("fetchSourceQualityStatus<");
    expect(resourcesSource).toContain("fetchPaperNoteChunkStatus<");
    expect(resourcesSource).not.toContain("/official-model-evidence/status");
    expect(resourcesSource).not.toContain("/source-quality/status");
    expect(resourcesSource).not.toContain("/paper-note-chunks/status");
    expect(mutationsSource).toContain("assessCandidateSourceQuality<");
    expect(mutationsSource).toContain("assessSourceQualityBatch<");
    expect(mutationsSource).toContain("planPaperNoteChunks<");
    expect(mutationsSource).not.toContain("/source-quality/assess-batch");
    expect(mutationsSource).not.toContain("/paper-note-chunks/plan");
  });
});
