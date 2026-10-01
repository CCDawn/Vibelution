import { useQuery } from "@tanstack/react-query";

import { listFinancialAssistants } from "../../api/financialAssistant";
import { queryKeys } from "../../api/queryKeys";

export function useFinancialAssistants(enabled = true) {
  return useQuery({
    queryKey: queryKeys.financialAssistants(),
    queryFn: ({ signal }) => listFinancialAssistants({ signal }),
    staleTime: 15_000,
    retry: false,
    enabled,
  });
}
