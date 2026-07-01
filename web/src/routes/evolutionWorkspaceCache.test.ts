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

    expect(invalidateQueries).toHaveBeenCalledTimes(7);
    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionWorkspaceSnapshot(),
      queryKeys.evolutionWorkbench(),
      queryKeys.evolutionActiveRun(),
      queryKeys.evolutionLatestRun(),
      queryKeys.evolutionOverview(),
      queryKeys.evolutionRuns(),
      queryKeys.evolutionLibrary(),
    ]);
  });

  it("keeps worktree run refresh scoped to worktree and runtime state", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterWorktreeRunChanged();

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionWorkspaceSnapshot(),
      queryKeys.evolutionWorktreeActiveRun(),
      queryKeys.evolutionWorktreeRuns(),
      queryKeys.runtimeSummary(),
    ]);
  });

  it("refreshes active and latest supervised run snapshots together", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.refreshSupervisedActiveRun();

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionWorkspaceSnapshot(),
      queryKeys.evolutionActiveRun(),
      queryKeys.evolutionLatestRun(),
    ]);
  });

  it("refreshes latest supervised result when a live run reaches a terminal state", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterSupervisedRunTerminal();

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionWorkspaceSnapshot(),
      queryKeys.evolutionActiveRun(),
      queryKeys.evolutionLatestRun(),
      queryKeys.evolutionOverview(),
      queryKeys.evolutionRuns(),
      queryKeys.evolutionLibrary(),
      queryKeys.evolutionWorkbench(),
    ]);
  });

  it("refreshes the self-evolution worktree workspace after a self run change", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterSelfEvolutionChanged();

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionWorkspaceSnapshot(),
      queryKeys.evolutionSelfOverview(),
      queryKeys.evolutionWorktreeActiveRun(),
      queryKeys.evolutionWorktreeRuns(),
      queryKeys.evolutionSelfTransactions(),
      queryKeys.evolutionSelfAudit(),
      queryKeys.runtimeSummary(),
    ]);
  });

  it("refreshes proposal detail with the supervised indexes", async () => {
    const { cache, queryKeysFromCalls } = makeCache();

    await cache.afterProposalChanged("run-a");

    expect(queryKeysFromCalls()).toEqual([
      queryKeys.evolutionWorkspaceSnapshot(),
      queryKeys.evolutionOverview(),
      queryKeys.evolutionRuns(),
      queryKeys.evolutionLibrary(),
      queryKeys.evolutionProposal("run-a"),
    ]);
  });
});
