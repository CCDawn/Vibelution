import { describe, expect, it } from "vitest";

import apiSource from "./evolution.ts?raw";
import proposalSource from "../routes/evolution/useEvolutionProposalMutations.ts?raw";
import runSource from "../routes/evolution/useEvolutionRunMutations.ts?raw";
import routeSource from "../routes/EvolutionRoute.tsx?raw";
import reviewSource from "../routes/SupervisedReviewRoute.tsx?raw";
import controlsSource from "../routes/SupervisedWorkspaceControls.tsx?raw";

describe("evolution catalog API", () => {
  it("owns the remaining evolution JSON transports", () => {
    expect(apiSource).toContain("export function fetchEvolutionWorkspaceSnapshot");
    expect(apiSource).toContain("export function fetchEvolutionWorkbench");
    expect(apiSource).toContain("export function fetchSelfEvolutionWorkspaceSnapshot");
    expect(apiSource).toContain("export function fetchSelfObservationRun");
    expect(apiSource).toContain("export function fetchEvolutionProposalDetail");
    expect(apiSource).toContain("export function updateEvolutionProposal");
    expect(apiSource).toContain("export function deleteEvolutionProposal");
    expect(apiSource).toContain("export function bulkDeleteEvolutionProposals");
    expect(apiSource).toContain("export function createEvolutionWorktreeRun");
    expect(apiSource).toContain("export function createSelfEvolutionWorktreeRun");
    expect(apiSource).toContain("export function startSelfObservationRun");
    expect(apiSource).toContain("export function postSelfObservationRunAction");
    expect(apiSource).toContain("export function deleteSelfEvolutionHistory");
    expect(apiSource).toContain("export function postEvolutionRunAction");
    expect(apiSource).toContain("export function postEvolutionWorktreeRunAction");
    expect(apiSource).toContain("export function fetchEvolutionChatReviewQueue");
    expect(apiSource).toContain("export function fetchEvolutionChatReviewCandidate");
    expect(apiSource).toContain("export function decideEvolutionChatReview");
    expect(apiSource).toContain("export function bulkDeleteEvolutionChatReview");
    expect(apiSource).toContain("export function fetchEvolutionOverview");
    expect(apiSource).toContain('"/api/evolution/worktree-runs"');
    expect(apiSource).toContain('"/api/evolution/workspace-snapshot"');
    expect(apiSource).toContain('"/api/evolution/workbench"');
    expect(apiSource).toContain('"/api/evolution/self/workspace-snapshot"');
    expect(apiSource).toContain("/api/evolution/self/observation-runs/${encodeURIComponent(runId)}");
    expect(apiSource).toContain("export function fetchEvolutionLibrary");
    expect(apiSource).toContain("export function startEvolutionRun");
    expect(apiSource).toContain("export function fetchSelfEvolutionOverview");
  });

  it("keeps EvolutionRoute and mutations free of evolution JSON paths", () => {
    expect(routeSource).toContain("fetchEvolutionWorkspaceSnapshot<");
    expect(routeSource).toContain("fetchEvolutionWorkbench<");
    expect(routeSource).toContain("fetchSelfEvolutionWorkspaceSnapshot<");
    expect(routeSource).toContain("fetchSelfObservationRun<");
    expect(routeSource).toContain("fetchEvolutionProposalDetail<");
    expect(routeSource).toContain('new EventSource("/api/evolution/active-run/events")');
    expect(routeSource).not.toContain("/api/evolution/workspace-snapshot");
    expect(routeSource).not.toContain("/api/evolution/workbench");
    expect(proposalSource).toContain("updateEvolutionProposal<");
    expect(proposalSource).toContain("deleteEvolutionProposal<");
    expect(proposalSource).toContain("bulkDeleteEvolutionProposals<");
    expect(proposalSource).not.toContain("/api/evolution/");
    expect(runSource).toContain("createEvolutionWorktreeRun<");
    expect(runSource).toContain("createSelfEvolutionWorktreeRun<");
    expect(runSource).toContain("startSelfObservationRun<");
    expect(runSource).toContain("postSelfObservationRunAction<");
    expect(runSource).toContain("deleteSelfEvolutionHistory<");
    expect(runSource).toContain("postEvolutionRunAction<");
    expect(runSource).toContain("postEvolutionWorktreeRunAction<");
    expect(runSource).not.toContain("/api/evolution/");
  });

  it("keeps supervised review and workspace controls on named evolution transports", () => {
    expect(reviewSource).toContain("fetchEvolutionChatReviewQueue<");
    expect(reviewSource).toContain("fetchEvolutionChatReviewCandidate<");
    expect(reviewSource).toContain("decideEvolutionChatReview<");
    expect(reviewSource).toContain("bulkDeleteEvolutionChatReview<");
    expect(reviewSource).toContain("postEvolutionWorktreeRunAction<");
    expect(reviewSource).not.toContain("/api/evolution/");
    expect(controlsSource).toContain("fetchEvolutionOverview<");
    expect(controlsSource).not.toContain("/api/evolution/");
  });
});
