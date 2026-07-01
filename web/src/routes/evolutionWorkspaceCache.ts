import type { QueryKey } from "@tanstack/react-query";

import { queryKeys } from "../api/queryKeys";

type QueryClientLike = {
  invalidateQueries: (options: { queryKey: QueryKey }) => Promise<unknown> | unknown;
};

function uniqueQueryKeys(keys: QueryKey[]): QueryKey[] {
  const seen = new Set<string>();
  return keys.filter((key) => {
    const fingerprint = JSON.stringify(key);
    if (seen.has(fingerprint)) {
      return false;
    }
    seen.add(fingerprint);
    return true;
  });
}

function invalidateAll(queryClient: QueryClientLike, keys: QueryKey[]) {
  return Promise.all(
    uniqueQueryKeys(keys).map((queryKey) => queryClient.invalidateQueries({ queryKey })),
  );
}

export function createEvolutionWorkspaceCache(queryClient: QueryClientLike) {
  return {
    afterSupervisedWorkspaceChanged() {
      return invalidateAll(queryClient, [
        queryKeys.evolutionWorkspaceSnapshot(),
        queryKeys.evolutionWorkbench(),
        queryKeys.evolutionActiveRun(),
        queryKeys.evolutionLatestRun(),
        queryKeys.evolutionOverview(),
        queryKeys.evolutionRuns(),
        queryKeys.evolutionLibrary(),
      ]);
    },
    afterSupervisedRunTerminal() {
      return invalidateAll(queryClient, [
        queryKeys.evolutionWorkspaceSnapshot(),
        queryKeys.evolutionActiveRun(),
        queryKeys.evolutionLatestRun(),
        queryKeys.evolutionOverview(),
        queryKeys.evolutionRuns(),
        queryKeys.evolutionLibrary(),
        queryKeys.evolutionWorkbench(),
      ]);
    },
    refreshSupervisedActiveRun() {
      return invalidateAll(queryClient, [
        queryKeys.evolutionWorkspaceSnapshot(),
        queryKeys.evolutionActiveRun(),
        queryKeys.evolutionLatestRun(),
      ]);
    },
    afterWorktreeRunChanged() {
      return invalidateAll(queryClient, [
        queryKeys.evolutionWorkspaceSnapshot(),
        queryKeys.evolutionWorktreeActiveRun(),
        queryKeys.evolutionWorktreeRuns(),
        queryKeys.runtimeSummary(),
      ]);
    },
    afterSelfEvolutionChanged() {
      return invalidateAll(queryClient, [
        queryKeys.evolutionWorkspaceSnapshot(),
        queryKeys.evolutionSelfOverview(),
        queryKeys.evolutionWorktreeActiveRun(),
        queryKeys.evolutionWorktreeRuns(),
        queryKeys.evolutionSelfTransactions(),
        queryKeys.evolutionSelfAudit(),
        queryKeys.runtimeSummary(),
      ]);
    },
    afterProposalChanged(sessionId: string) {
      return invalidateAll(queryClient, [
        queryKeys.evolutionWorkspaceSnapshot(),
        queryKeys.evolutionOverview(),
        queryKeys.evolutionRuns(),
        queryKeys.evolutionLibrary(),
        queryKeys.evolutionProposal(sessionId),
      ]);
    },
  };
}
