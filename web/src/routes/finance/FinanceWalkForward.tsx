import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ChevronDown, ChevronRight, Download, Play, Square } from "lucide-react";
import { actWalkForward, exportWalkForward, listWalkForward, previewWalkForward, type WalkForwardWorkflow } from "../../api/financialWalkForward";
import { VButton, VDenseTable, VInput, VSelect, VStateSurface, VSurface } from "../../components/vui";
import styles from "./FinanceAIBacktest.styles";

const active = new Set(["queued", "running", "stop_requested"]);
const labels: Record<WalkForwardWorkflow["status"], string> = { preview: "待启动", queued: "排队中", running: "运行中", stop_requested: "正在停止", stopped: "已停止", paused_unknown: "调用待确认", completed: "已完成", failed: "失败", blocked: "条件不满足" };
const pct = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(2)}%` : "—";

export function FinanceWalkForward({ agentId, sourceRunId, zh, onSelectRun }: { agentId: string; sourceRunId?: string; zh: boolean; onSelectRun: (id: string) => void }) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false), [selectedId, setSelectedId] = useState("");
  const [train, setTrain] = useState(126), [test, setTest] = useState(63), [budget, setBudget] = useState(2_000_000);
  const [pending, setPending] = useState(false), [error, setError] = useState("");
  const gate = useRef(false);
  const key = ["finance", "walk-forward", agentId] as const;
  const workflows = useQuery({ queryKey: key, queryFn: ({ signal }) => listWalkForward(agentId, signal), enabled: open, retry: false, refetchInterval: query => query.state.data?.items.some(item => active.has(item.status)) ? 2500 : false });
  const items = workflows.data?.items.filter(item => item.agentId === agentId) ?? [];
  const shown = items.find(item => item.workflowId === selectedId) ?? items[0];
  const valid = Number.isInteger(train) && train >= 2 && train <= 2500 && Number.isInteger(test) && test >= 2 && test <= 1250 && Number.isInteger(budget) && budget >= 512 && budget <= 2_000_000;
  async function perform(work: () => Promise<void>) {
    if (gate.current) return;
    gate.current = true; setPending(true); setError("");
    try { await work(); } catch (cause) { setError(cause instanceof Error ? cause.message : "操作失败"); }
    finally { gate.current = false; setPending(false); }
  }
  async function accept(result: WalkForwardWorkflow) {
    if (result.agentId !== agentId) throw new Error("滚动验证智能体身份不匹配");
    client.setQueryData<{ items: WalkForwardWorkflow[] }>(key, old => ({ items: [result, ...(old?.items ?? []).filter(item => item.workflowId !== result.workflowId)] }));
    setSelectedId(result.workflowId);
    await client.invalidateQueries({ queryKey: key });
  }
  return <section className={styles.panel}>
    <VButton variant="ghost" className="justify-start" aria-expanded={open} icon={open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} onPress={() => setOpen(value => !value)}>{zh ? "滚动样本外验证" : "Walk-forward validation"}</VButton>
    {open ? <VSurface tone="panel" padding="normal" className={styles.panel}>
      <p className={styles.note}>{zh ? "每轮先用训练区间比较 40% / 60% / 80% 仓位上限，再独立测试胜出参数。复用已选记录的冻结行情，每段重新调用模型。" : "Each fold selects a 40% / 60% / 80% position cap on training data, then tests the winner independently. Uses the selected run’s frozen prices with new model calls."}</p>
      <div className={styles.row}>
        <label className={styles.field}>{zh ? "训练交易日" : "Train sessions"}<VInput type="number" aria-label="滚动训练交易日" min={2} max={2500} value={String(train)} disabled={pending} onChange={event => setTrain(Number(event.target.value))} /></label>
        <label className={styles.field}>{zh ? "测试交易日" : "Test sessions"}<VInput type="number" aria-label="滚动测试交易日" min={2} max={1250} value={String(test)} disabled={pending} onChange={event => setTest(Number(event.target.value))} /></label>
        <label className={styles.field}>{zh ? "总 Token 上限" : "Total token cap"}<VInput type="number" aria-label="滚动验证Token上限" min={512} max={2_000_000} value={String(budget)} disabled={pending} onChange={event => setBudget(Number(event.target.value))} /></label>
        <VButton isDisabled={pending || !sourceRunId || !valid} onPress={() => void perform(async () => { if (!sourceRunId) return; await accept(await previewWalkForward(agentId, sourceRunId, { trainSessions: train, testSessions: test, stepSessions: test, maxTokens: budget, candidates: [40, 60, 80].map(value => ({ candidateId: `cap-${value}`, maxPositionPct: value })) })); })}>{zh ? "预检滚动计划" : "Preview plan"}</VButton>
      </div>
      {!sourceRunId ? <p className={styles.note}>{zh ? "先选择一条已有回测，使用其冻结行情。" : "Select an existing run to reuse its frozen prices."}</p> : null}
      {error || workflows.isError ? <VStateSurface tone="error" density="compact" title={error || workflows.error?.message || "读取失败"} actions={<VButton onPress={() => void workflows.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : null}
      {workflows.isPending ? <VStateSurface tone="loading" busy density="compact" title={zh ? "读取滚动计划" : "Loading workflows"} /> : null}
      {items.length > 1 ? <VSelect aria-label="滚动验证记录" selectedKey={shown?.workflowId} options={items.map(item => ({ id: item.workflowId, label: `${zh ? labels[item.status] : item.status} · ${new Date(item.createdAt).toLocaleString()}` }))} onSelectionChange={value => setSelectedId(String(value))} /> : null}
      {shown ? <>
        <div className={styles.row}>
          <strong className="whitespace-nowrap text-xs">{zh ? labels[shown.status] : shown.status} · {shown.folds.length} {zh ? "轮" : "folds"}</strong>
          <span className={styles.note}>{zh ? "预留 Token（含重试）" : "Reserved tokens (incl. retries)"} {shown.estimatedTokens.toLocaleString()} / {shown.maxTokens.toLocaleString()}</span>
          <span className={styles.note}>{zh ? "已占用预算" : "Committed budget"} {(shown.budgetTokensCommitted ?? 0).toLocaleString()}</span>
          {shown.status === "preview" ? <VButton icon={<Play size={14} />} isDisabled={pending} onPress={() => void perform(async () => accept(await actWalkForward(agentId, shown.workflowId, "start")))}>{zh ? "按冻结预算启动" : "Start frozen plan"}</VButton> : active.has(shown.status) ? <VButton icon={<Square size={14} />} isDisabled={pending || shown.status === "stop_requested"} onPress={() => void perform(async () => accept(await actWalkForward(agentId, shown.workflowId, "stop")))}>{zh ? "停止" : "Stop"}</VButton> : ["stopped", "paused_unknown", "failed"].includes(shown.status) ? <VButton icon={<Play size={14} />} isDisabled={pending} onPress={() => void perform(async () => accept(await actWalkForward(agentId, shown.workflowId, "resume")))}>{zh ? "继续计划" : "Resume"}</VButton> : null}
          {shown.activeRunId ? <VButton variant="ghost" onPress={() => onSelectRun(shown.activeRunId!)}>{zh ? "查看当前子回测" : "Open current run"}</VButton> : null}
          <VButton variant="ghost" icon={<Download size={14} />} isDisabled={pending} onPress={() => void perform(() => exportWalkForward(agentId, shown.workflowId))}>JSON</VButton>
        </div>
        {shown.terminalReason ? <VStateSurface tone="error" density="compact" title={shown.terminalReason} /> : null}
        <div className={styles.table}><VDenseTable ariaLabel="滚动样本外验证各轮结果" rows={shown.folds} getRowKey={row => row.foldId} emptyText={zh ? "没有完整窗口" : "No complete folds"} columns={[
          { id: "train", header: zh ? "训练区间" : "Training", render: row => `${row.trainStart} — ${row.trainEnd}` },
          { id: "test", header: zh ? "测试区间" : "Test", render: row => `${row.testStart} — ${row.testEnd}` },
          { id: "candidate", header: zh ? "选定仓位上限" : "Selected cap", render: row => { const candidate = shown.candidates.find(item => item.candidateId === row.selectedCandidateId); return candidate ? `${candidate.maxPositionPct}%` : "—"; } },
          { id: "return", header: zh ? "测试收益" : "Test return", render: row => pct(row.metrics?.totalReturnPct) },
          { id: "excess", header: zh ? "测试超额" : "Test excess", render: row => pct(row.metrics?.excessReturnPct) },
          { id: "detail", header: zh ? "测试记录" : "Test run", render: row => row.testRunId ? <VButton variant="ghost" onPress={() => onSelectRun(row.testRunId!)}>{zh ? "查看" : "Open"}</VButton> : "—" },
        ]} /></div>
        <p className={styles.note}>{shown.notice}</p>
      </> : null}
    </VSurface> : null}
  </section>;
}
