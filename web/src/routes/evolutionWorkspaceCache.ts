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
        queryKeys.evolutionWorkbench(),
        queryKeys.evolutionActiveRun(),
        queryKeys.evolutionOverview(),
        queryKeys.evolutionRuns(),
        queryKeys.evolutionLibrary(),
      ]);
    },
    afterSupervisedRunTerminal() {
      return invalidateAll(queryClient, [
        queryKeys.evolutionActiveRun(),
        queryKeys.evolutionOverview(),
        queryKeys.evolutionRuns(),
        queryKeys.evolutionLibrary(),
        queryKeys.evolutionWorkbench(),
      ]);
    },
    refreshSupervisedActiveRun() {
      return invalidateAll(queryClient, [queryKeys.evolutionActiveRun()]);
    },
    afterWorktreeRunChanged() {
      return invalidateAll(queryClient, [
        queryKeys.evolutionWorktreeActiveRun(),
        queryKeys.evolutionWorktreeRuns(),
        queryKeys.runtimeSummary(),
      ]);
    },
    afterSelfEvolutionChanged() {
      return invalidateAll(queryClient, [
        queryKeys.evolutionSelfOverview(),
        queryKeys.evolutionSelfActiveRun(),
        queryKeys.evolutionSelfLatestRun(),
        queryKeys.evolutionSelfTransactions(),
        queryKeys.evolutionSelfAudit(),
        queryKeys.runtimeSummary(),
      ]);
    },
    refreshSelfLatestRun() {
      return invalidateAll(queryClient, [queryKeys.evolutionSelfLatestRun()]);
    },
    afterSelfHandoff() {
      return invalidateAll(queryClient, [
        queryKeys.evolutionSelfOverview(),
        queryKeys.evolutionSelfActiveRun(),
        queryKeys.evolutionSelfLatestRun(),
        queryKeys.evolutionSelfTransactions(),
        queryKeys.evolutionSelfAudit(),
        queryKeys.runtimeSummary(),
        queryKeys.sessions(),
      ]);
    },
    afterProposalChanged(sessionId: string) {
      return invalidateAll(queryClient, [
        queryKeys.evolutionOverview(),
        queryKeys.evolutionRuns(),
        queryKeys.evolutionLibrary(),
        queryKeys.evolutionProposal(sessionId),
      ]);
    },
  };
}
