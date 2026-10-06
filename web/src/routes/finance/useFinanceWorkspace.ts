import { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchFinancialWorkspace, financialWorkspaceKey, updateFinancialWorkspace, type FinancialWorkspacePatch, type FinancialWorkspaceSettings } from "../../api/financialPreferences";

const queues = new Map<string, Promise<unknown>>();
type WorkspaceChange = FinancialWorkspacePatch | ((current: FinancialWorkspaceSettings) => FinancialWorkspacePatch | null);
function revisionConflict(error: unknown) { return typeof error === "object" && error !== null && "status" in error && error.status === 409; }

/** Serialize local intents; rebase one revision conflict onto the server state. */
export function useFinanceWorkspace(agentId: string) {
  const client = useQueryClient();
  const [pending, setPending] = useState(0), [error, setError] = useState("");
  const query = useQuery({ queryKey: financialWorkspaceKey(agentId), queryFn: ({ signal }) => fetchFinancialWorkspace(agentId, { signal }), staleTime: 15_000, retry: false });
  const update = useCallback((change: WorkspaceChange): Promise<FinancialWorkspaceSettings> => {
    setPending((count) => count + 1); setError("");
    const operation = (queues.get(agentId) ?? Promise.resolve()).catch(() => undefined).then(async () => {
      let current = client.getQueryData<FinancialWorkspaceSettings>(financialWorkspaceKey(agentId)) ?? await fetchFinancialWorkspace(agentId);
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          const patch = typeof change === "function" ? change(current) : change;
          if (!patch) { client.setQueryData(financialWorkspaceKey(agentId), current); return current; }
          const result = await updateFinancialWorkspace(agentId, current.revision, patch);
          if (result.agentId !== agentId || result.revision <= current.revision) throw new Error("设置保存身份不匹配");
          client.setQueryData(financialWorkspaceKey(agentId), result);
          return result;
        } catch (cause) {
          if (attempt === 0 && revisionConflict(cause)) { current = await fetchFinancialWorkspace(agentId); continue; }
          throw cause;
        }
      }
      throw new Error("设置保存失败");
    });
    queues.set(agentId, operation);
    return operation.catch((cause: unknown) => { setError(cause instanceof Error ? cause.message : "设置保存失败，请重试"); throw cause; }).finally(() => {
      setPending((count) => Math.max(0, count - 1));
      if (queues.get(agentId) === operation) queues.delete(agentId);
    });
  }, [agentId, client]);
  return { query, update, pending: pending > 0, error };
}
