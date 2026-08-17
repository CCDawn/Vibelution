import { describe, expect, it } from "vitest";

import routeShellSource from "./TeamsRouteWorkbench.tsx?raw";
import routeModelSourceThin from "./useTeamsWorkbenchModel.tsx?raw";
import routeFoundationSource from "./useTeamsWorkbenchFoundation.tsx?raw";
import routeShellPhaseSource from "./useTeamsWorkbenchShellPhase.tsx?raw";
const routeModelSource = `${routeModelSourceThin}\n${routeFoundationSource}\n${routeShellPhaseSource}`;
import mutationBundleSource from "./useTeamsMutationBundle.ts?raw";
const routeSource = `${routeShellSource}\n${routeModelSource}\n${routeFoundationSource}\n${routeShellPhaseSource}\n${mutationBundleSource}`;
import modelSource from "./sourceCollectionMutationModel.ts?raw";
import mutationsSource from "./useTeamSourceCollectionMutations.ts?raw";

const mutationOwners = [
  "recordSourceCollectionOutputMutation",
  "executeSourceCollectionSearchMutation",
  "extractSourceCollectionCandidatesMutation",
  "openSourceCollectionStorageMutation",
  "assessSourceQualityMutation",
  "assessSourceQualityBatchMutation",
  "planPaperNoteChunksMutation",
  "buildCandidateGraphMutation",
  "runKnowledgeIngestionPrecheckMutation",
  "runKnowledgeCollectionCompletionMutation",
] as const;

describe("team source-collection mutations contract", () => {
  it("owns the SC write mutations", () => {
    expect(mutationsSource.match(/\buseMutation\(/g) ?? []).toHaveLength(mutationOwners.length);
    mutationOwners.forEach((owner) => {
      expect(mutationsSource).toContain(`const ${owner} = useMutation({`);
      expect(mutationsSource).toContain(`${owner},`);
    });
  });

  it("stays free of streaming, local UI state, and navigation", () => {
    expect(mutationsSource).not.toMatch(/\bnew EventSource\b/);
    expect(mutationsSource).not.toContain("useState");
    expect(mutationsSource).not.toContain("useEffect");
    expect(mutationsSource).not.toContain("useNavigate");
    expect(mutationsSource).not.toContain("react-router-dom");
  });

  it("is wired from TeamsRoute while Route no longer defines those mutations inline", () => {
    // R2-g: model → mutation bundle → SC mutations.
    expect(routeModelSource).toContain("useTeamsMutationBundle({");
    expect(mutationBundleSource).toContain("useTeamSourceCollectionMutations({");
    expect(routeSource).toContain("scrollSourceCollectionPanelIntoViewRef");
    expect(routeSource).toContain("sourceCollectionMutationModel");
    mutationOwners.forEach((owner) => {
      expect(routeSource).not.toContain(`const ${owner} = useMutation({`);
      expect(routeSource).toContain(owner);
    });
  });

  it("promotes SC payload types out of TeamsRoute into the mutation model", () => {
    expect(modelSource).toContain("export type SourceCollectionOutputDraft");
    expect(modelSource).toContain("export type TeamWorkflowSourceCollectionSearchExecutionPayload");
    expect(modelSource).toContain("export type TeamWorkflowSourceQualityAssessmentPayload");
    expect(modelSource).toContain("export type TeamWorkflowSourceQualityBatchAssessmentPayload");
    expect(modelSource).toContain("export type TeamWorkflowPaperNoteChunkPlanPayload");
    expect(modelSource).toContain("export type TeamWorkflowKnowledgeIngestionPrecheckPayload");
    expect(routeSource).not.toContain("type SourceCollectionOutputDraft =");
    expect(routeSource).not.toContain("type TeamWorkflowSourceCollectionSearchExecutionPayload =");
  });

  it("preserves key write endpoints used by SC search/quality/graph/ingestion", () => {
    expect(mutationsSource).toContain("recordDataProcessingCollectionOutput<");
    expect(mutationsSource).toContain("importDataRecordAsSourceCandidate(");
    expect(mutationsSource).toContain("executeSourceCollectionSearch<");
    expect(mutationsSource).toContain("openSourceCollectionStorage<");
    expect(mutationsSource).toContain("assessCandidateSourceQuality<");
    expect(mutationsSource).toContain("assessSourceQualityBatch<");
    expect(mutationsSource).toContain("planPaperNoteChunks<");
    expect(mutationsSource).toContain("buildCandidateGraph(");
    expect(mutationsSource).toContain("runKnowledgeIngestionPrecheck<");
    expect(mutationsSource).toContain("completeKnowledgeCollection(");
    expect(mutationsSource).toContain("extractSourceCollectionCandidates(");
  });
});
