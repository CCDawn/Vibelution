import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createFinancialResearchSchedule, fetchFinancialResearchBatches, fetchFinancialResearchSchedules,
  retryFinancialResearchBatch, stopFinancialResearchBatch, updateFinancialResearchSchedule,
  type FinancialResearchBatch, type FinancialResearchBatchList, type FinancialResearchSchedule,
  type FinancialResearchScheduleCreateRequest, type FinancialResearchScheduleList,
} from "../../api/financialJobs";
import { financialTeamKeys } from "../../api/financialTeam";
import { queryKeys } from "../../api/queryKeys";
import { ACTIVE_FINANCIAL_BATCH_STATUSES } from "./financialJobModel";

export function useFinanceResearchJobs(assistantAgentId: string, zh: boolean) {
  const client = useQueryClient();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [pendingAction, setPendingAction] = useState("");
  const clearFeedback = useCallback(() => { setError(""); setNotice(""); }, []);
  const mounted = useRef(false), owner = useRef(assistantAgentId);
  const generation = useRef(0);
  if (owner.current !== assistantAgentId) generation.current += 1;
  owner.current = assistantAgentId;
  const createGate = useRef(false), actionGate = useRef(false);
  const request = useRef<{ fingerprint: string; key: string } | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    setError(""); setNotice(""); request.current = null;
    setCreating(false); setPendingAction(""); createGate.current = false; actionGate.current = false;
  }, [assistantAgentId]);
  const schedulesKey = queryKeys.financialResearchSchedules(assistantAgentId);
  const batchesKey = queryKeys.financialResearchBatches(assistantAgentId);
  const schedules = useQuery({ queryKey: schedulesKey, queryFn: async ({ signal }) => {
    const result = await fetchFinancialResearchSchedules(assistantAgentId, { signal });
    if (result.assistantAgentId !== assistantAgentId || result.schedules.some((row) => row.assistantAgentId !== assistantAgentId)) throw new Error(zh ? "计划归属不匹配，请刷新" : "Schedule owner mismatch; refresh");
    return result;
  }, retry: false, staleTime: 5_000, refetchInterval: 20_000 });
  const batches = useQuery({ queryKey: batchesKey, queryFn: async ({ signal }) => {
    const result = await fetchFinancialResearchBatches(assistantAgentId, { signal });
    if (result.assistantAgentId !== assistantAgentId || result.batches.some((row) => row.assistantAgentId !== assistantAgentId)) throw new Error(zh ? "批次归属不匹配，请刷新" : "Batch owner mismatch; refresh");
    return result;
  }, retry: false, staleTime: 3_000, refetchInterval: (query) => query.state.data?.batches.some((batch) => ACTIVE_FINANCIAL_BATCH_STATUSES.has(batch.status)) ? 3_000 : 20_000 });

  function updateBatch(row: FinancialResearchBatch, agentId: string) {
    if (row.assistantAgentId !== agentId) throw new Error(zh ? "批次归属已变化，请刷新" : "Batch ownership changed; refresh");
    client.setQueryData<FinancialResearchBatchList>(queryKeys.financialResearchBatches(agentId), (old) => ({ assistantAgentId: agentId, batches: [row, ...(old?.batches ?? []).filter((batch) => batch.batchId !== row.batchId)].sort((a, b) => b.triggeredAt.localeCompare(a.triggeredAt)) }));
  }
  function updateSchedule(row: FinancialResearchSchedule, agentId: string) {
    if (row.assistantAgentId !== agentId) throw new Error(zh ? "计划归属已变化，请刷新" : "Schedule ownership changed; refresh");
    client.setQueryData<FinancialResearchScheduleList>(queryKeys.financialResearchSchedules(agentId), (old) => ({ assistantAgentId: agentId, schedules: [row, ...(old?.schedules ?? []).filter((schedule) => schedule.scheduleId !== row.scheduleId)] }));
  }
  function visible(agentId: string, operation: number) { return mounted.current && owner.current === agentId && generation.current === operation; }
  async function refresh() { await Promise.allSettled([schedules.refetch(), batches.refetch()]); }
  async function create(payload: FinancialResearchScheduleCreateRequest) {
    if (createGate.current) return;
    const agentId = assistantAgentId, operation = generation.current, fingerprint = JSON.stringify([agentId, payload]);
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, key: `financial-job-${crypto.randomUUID()}` };
    const key = request.current.key;
    createGate.current = true; setCreating(true); setError(""); setNotice("");
    try {
      const result = await createFinancialResearchSchedule(agentId, payload, key);
      updateSchedule(result.schedule, agentId);
      if (result.batch) updateBatch(result.batch, agentId);
      if (visible(agentId, operation) && request.current?.key === key) request.current = null;
      if (visible(agentId, operation)) setNotice(result.batch ? (zh ? "批次已创建，后台逐股研究" : "Batch created; research runs in the background") : (zh ? "计划已保存" : "Schedule saved"));
      await Promise.allSettled([
        client.invalidateQueries({ queryKey: queryKeys.financialResearchSchedules(agentId) }),
        client.invalidateQueries({ queryKey: queryKeys.financialResearchBatches(agentId) }),
        client.invalidateQueries({ queryKey: financialTeamKeys.detail(agentId) }),
        client.invalidateQueries({ queryKey: financialTeamKeys.runs(agentId) }),
      ]);
    } catch (caught) {
      if (visible(agentId, operation)) setError(caught instanceof Error ? caught.message : (zh ? "提交失败，重试将核对同一请求" : "Submission failed; retry verifies this request"));
    } finally { if (visible(agentId, operation)) { createGate.current = false; setCreating(false); } }
  }
  async function action(id: string, execute: () => Promise<FinancialResearchBatch | FinancialResearchSchedule>, kind: "batch" | "schedule") {
    if (actionGate.current) return;
    const agentId = assistantAgentId, operation = generation.current;
    actionGate.current = true; setPendingAction(id); setError(""); setNotice("");
    try {
      const result = await execute();
      if (kind === "batch") updateBatch(result as FinancialResearchBatch, agentId); else updateSchedule(result as FinancialResearchSchedule, agentId);
      await Promise.allSettled([
        client.invalidateQueries({ queryKey: queryKeys.financialResearchBatches(agentId) }),
        client.invalidateQueries({ queryKey: queryKeys.financialResearchSchedules(agentId) }),
        client.invalidateQueries({ queryKey: financialTeamKeys.runs(agentId) }),
      ]);
    } catch (caught) { if (visible(agentId, operation)) setError(caught instanceof Error ? caught.message : (zh ? "操作失败，请刷新后重试" : "Operation failed; refresh and retry")); }
    finally { if (visible(agentId, operation)) { actionGate.current = false; setPendingAction(""); } }
  }
  return { schedules, batches, error, notice, creating, pendingAction, create, refresh, clearFeedback,
    stop: (batchId: string) => action(batchId, () => stopFinancialResearchBatch(assistantAgentId, batchId), "batch"),
    retry: (batchId: string) => action(batchId, () => retryFinancialResearchBatch(assistantAgentId, batchId), "batch"),
    setEnabled: (scheduleId: string, enabled: boolean) => action(scheduleId, () => updateFinancialResearchSchedule(assistantAgentId, scheduleId, enabled), "schedule"),
  };
}
