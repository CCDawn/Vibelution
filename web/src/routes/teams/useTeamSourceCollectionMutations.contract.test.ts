import { describe, expect, it } from "vitest";

import routeSource from "../TeamsRoute.tsx?raw";
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
    expect(routeSource).toContain("useTeamSourceCollectionMutations({");
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
    expect(mutationsSource).toContain("/collection-assignments/${encodeURIComponent(payload.draft.assignmentId)}/outputs");
    expect(mutationsSource).toContain("/source-candidate");
    expect(mutationsSource).toContain("/search/execute");
    expect(mutationsSource).toContain("/storage/open");
    expect(mutationsSource).toContain("/source-quality/assess");
    expect(mutationsSource).toContain("source-quality/assess-batch");
    expect(mutationsSource).toContain("/paper-note-chunks/plan");
    expect(mutationsSource).toContain("/workflow-orchestration/candidate-graph");
    expect(mutationsSource).toContain("knowledge-ingestion/precheck");
    expect(mutationsSource).toContain("/workflow-orchestration/knowledge-collection/complete");
    expect(mutationsSource).toContain("/knowledge-collection/extract");
  });
});
