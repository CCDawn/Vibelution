import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import { createEvolutionWorkspaceCache } from "./evolutionWorkspaceCache";

function makeCache() {
  const invalidateQueries = vi.fn();
  const cache = createEvolutionWorkspaceCache({ invalidateQueries });
  const queryKeysFromCalls = () => invalidateQueries.mock.calls.map(([options]) => options.queryKey);
  return { cache, invalidateQueries, queryKeysFromCalls };
}

describe("createEvolutionWorkspaceCache", () => {
  it("refreshes supervised workspace state through one semantic recipe", async () => {
    const { cache, invalidateQueries, queryKeysFromCalls } = makeCache();

    await cache.afterSupervisedWorkspaceChanged();

    expect(invalidateQueries).toHaveBeenCalledTimes(5);
    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionWorkbench(),
      queryKeys.evolutionActiveRun(),
      queryKeys.evolutionOverview(),
      queryKeys.evolutionRuns(),
      queryKeys.evolutionLibrary(),
    ]);
  });

  it("keeps worktree run refresh scoped to worktree and runtime state", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterWorktreeRunChanged();

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionWorktreeActiveRun(),
      queryKeys.evolutionWorktreeRuns(),
      queryKeys.runtimeSummary(),
    ]);
  });

  it("refreshes the full self-evolution workspace after a self run change", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterSelfEvolutionChanged();

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionSelfOverview(),
      queryKeys.evolutionSelfActiveRun(),
      queryKeys.evolutionSelfLatestRun(),
      queryKeys.evolutionSelfTransactions(),
      queryKeys.evolutionSelfAudit(),
      queryKeys.runtimeSummary(),
    ]);
  });

  it("extends self-evolution refresh to sessions after handoff", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterSelfHandoff();

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionSelfOverview(),
      queryKeys.evolutionSelfActiveRun(),
      queryKeys.evolutionSelfLatestRun(),
      queryKeys.evolutionSelfTransactions(),
      queryKeys.evolutionSelfAudit(),
      queryKeys.runtimeSummary(),
      queryKeys.sessions(),
    ]);
  });

  it("refreshes proposal detail with the supervised indexes", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterProposalChanged("run-a");

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionOverview(),
      queryKeys.evolutionRuns(),
      queryKeys.evolutionLibrary(),
      queryKeys.evolutionProposal("run-a"),
    ]);
  });
});
