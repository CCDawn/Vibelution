import { describe, expect, it } from "vitest";

import routeSource from "../TeamsRoute.tsx?raw";
import resourcesSource from "./useResearchWorkflowResources.ts?raw";
import {
  officialModelEvidenceStatusQueryKey,
  paperNoteChunkStatusQueryKey,
  researchStageRoundStatusQueryKey,
  sourceQualityStatusQueryKey,
} from "./useResearchWorkflowResources";

const queryOwners = [
  "workflow",
  "stageRound",
  "candidates",
  "candidateGraph",
  "coordination",
  "knowledgeIngestion",
  "modelEvidence",
  "sourceQuality",
  "paperNoteChunks",
] as const;

describe("research workflow shared read-query contract", () => {
  it("owns exactly nine named read queries and returns their typed query objects", () => {
    expect(resourcesSource.match(/\buseQuery\(/g) ?? []).toHaveLength(9);
    queryOwners.forEach((owner) => {
      expect(resourcesSource).toContain(`const ${owner} = useQuery({`);
      expect(resourcesSource).toContain(`${owner},`);
    });
  });

  it("preserves custom query keys used by Route mutation invalidation", () => {
    expect(researchStageRoundStatusQueryKey("team-1")).toEqual([
      "teams", "team-1", "workflow-orchestration", "stage-rounds", "status",
    ]);
    expect(officialModelEvidenceStatusQueryKey("team-1")).toEqual([
      "teams", "team-1", "workflow-orchestration", "official-model-evidence", "status",
    ]);
    expect(paperNoteChunkStatusQueryKey("team-1")).toEqual([
      "teams", "team-1", "workflow-orchestration", "paper-note-chunks", "status",
    ]);
    expect(sourceQualityStatusQueryKey("team-1")).toEqual([
      "teams", "team-1", "workflow-orchestration", "source-quality", "status",
    ]);
  });

  it("passes React Query cancellation signals through every fetch", () => {
    expect(resourcesSource.match(/queryFn: \(\{ signal \}\)/g) ?? []).toHaveLength(9);
    expect(resourcesSource.match(/\{ signal \}/g)?.length ?? 0).toBeGreaterThanOrEqual(18);
  });

  it("keeps each resource behind its own demand flag", () => {
    queryOwners.forEach((owner) => {
      expect(resourcesSource).toContain(`enabled: Boolean(teamId && demand.${owner})`);
    });
  });

  it("preserves writeback and active-ingestion polling policies", () => {
    expect(resourcesSource.match(/sourceCollectionStageWritebackRefetchInterval\(/g)?.length ?? 0).toBeGreaterThanOrEqual(4);
    expect(resourcesSource).toContain("stageRound.data");
    expect(resourcesSource).toContain("stageWritebackSync.active");
    expect(resourcesSource).toContain("stageWritebackSync.pendingTaskIds");
    expect(resourcesSource).toContain("resolvePollingInterval(pageVisible, data?.activeWorkRun ? 2000 : false)");
  });

  it("does not own mutations, local state, navigation, drafts, or panels", () => {
    [
      "useMutation",
      "useState",
      "useEffect",
      "useNavigate",
      "react-router-dom",
      "Draft",
      "Panel",
    ].forEach((forbidden) => {
      expect(resourcesSource).not.toContain(forbidden);
    });
  });

  it("is the only read owner while Route remains the demand composition boundary", () => {
    expect(routeSource).toContain("useResearchWorkflowResources({");
    [
      "teamWorkflowQuery",
      "researchStageRoundStatusQuery",
      "teamWorkflowCandidatesQuery",
      "teamWorkflowCandidateGraphQuery",
      "teamWorkflowCoordinationStatusQuery",
      "teamWorkflowKnowledgeIngestionStatusQuery",
      "teamWorkflowOfficialModelEvidenceStatusQuery",
      "teamWorkflowSourceQualityStatusQuery",
      "teamWorkflowPaperNoteChunkStatusQuery",
    ].forEach((queryName) => {
      expect(routeSource).not.toContain(`const ${queryName} = useQuery({`);
    });
    [
      "useTeamShellMutations",
      "useTeamWorkflowStartMutations",
      "useTeamExperimentLoopMutations",
      "useTeamSourceCollectionMutations",
    ].forEach((mutationOwner) => {
      expect(routeSource).toContain(`${mutationOwner}({`);
    });
    expect(routeSource).not.toContain("useMutation");
  });
});
