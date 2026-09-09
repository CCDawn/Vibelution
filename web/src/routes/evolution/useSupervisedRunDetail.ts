import { useQuery } from "@tanstack/react-query";
import { fetchEvolutionWorktreeRun } from "../../api/evolution";
import { queryKeys } from "../../api/queryKeys";
import type { SupervisedWorktreeRun } from "../../api/types";

export function useSupervisedRunDetail(run: SupervisedWorktreeRun | null) {
  const query = useQuery({
    queryKey: [...queryKeys.evolutionWorktreeRun(run?.runId ?? ""), run?.updatedAt],
    queryFn: () => fetchEvolutionWorktreeRun<SupervisedWorktreeRun>(run!.runId),
    enabled: run?.detailLevel === "summary",
    staleTime: 10_000,
  });
  return {
    run: run?.detailLevel === "summary" ? query.data ?? null : run,
    loading: run?.detailLevel === "summary" && query.isPending,
    error: run?.detailLevel === "summary" ? query.error : null,
    retry: query.refetch,
  };
}
