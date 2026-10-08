import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createFinancialClaim, financialEvaluationKeys } from "../../api/financialEvaluation";
import { VButton, VDialog, VInput, VSelect, VStateSurface, VTextarea } from "../../components/vui";
import styles from "./FinanceEvaluation.styles";

export function FinanceClaimRegistration({ agentId, sessionId, turnId, zh, initialSymbol = "" }: { agentId: string; sessionId: string; turnId: string; zh: boolean; initialSymbol?: string }) {
  const [open, setOpen] = useState(false), [symbol, setSymbol] = useState(initialSymbol), [dueDate, setDueDate] = useState("");
  const [direction, setDirection] = useState<"up" | "down">("up"), [threshold, setThreshold] = useState("0"), [claim, setClaim] = useState("");
  const [error, setError] = useState(""), [pending, setPending] = useState(false);
  const gate = useRef(false), request = useRef<{ fingerprint: string; id: string } | null>(null), client = useQueryClient();
  async function save() {
    if (gate.current || !threshold.trim() || !Number.isFinite(Number(threshold)) || Number(threshold) < 0 || Number(threshold) > 100) return;
    gate.current = true; setPending(true); setError("");
    const payload = { sessionId, turnId, symbol, dueDate, direction, thresholdPct: Number(threshold), claimText: claim.trim() };
    const fingerprint = JSON.stringify(payload);
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, id: crypto.randomUUID() };
    try { await createFinancialClaim(agentId, { ...payload, clientRequestId: request.current.id }); await client.invalidateQueries({ queryKey: financialEvaluationKeys.claims(agentId) }); setOpen(false); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "登记失败"); }
    finally { gate.current = false; setPending(false); }
  }
  return <>
    <VButton variant="secondary" onPress={() => { setOpen(true); setError(""); }}>{zh ? "登记到期核验" : "Track outcome"}</VButton>
    <VDialog open={open} onOpenChange={value => { if (!pending) setOpen(value); }} title={zh ? "登记报告判断" : "Track report claim"} footer={<VButton variant="primary" isPending={pending} isDisabled={pending || !symbol.trim() || !dueDate || !claim.trim()} onPress={() => void save()}>{zh ? "保存判据" : "Save rule"}</VButton>}>
      <div className={styles.panel}>
        <p className={styles.note}>{zh ? "绑定本报告；用截止日最后完整收盘相对分析日收盘的涨跌幅核验。事后登记会标为回顾，不纳入事前预测统计。" : "Bound to this report; compare the final completed close at the deadline with the analysis-date close. Late registrations are retrospective."}</p>
        <label className={styles.field}>{zh ? "股票代码" : "CN symbol"}<VInput aria-label="核验股票代码" value={symbol} maxLength={24} placeholder="sz000001" onChange={event => setSymbol(event.target.value)} /></label>
        <label className={styles.field}>{zh ? "截止日" : "Deadline"}<VInput aria-label="核验截止日" type="date" value={dueDate} onChange={event => setDueDate(event.target.value)} /></label>
        <div className={styles.row}><VSelect aria-label="核验方向" selectedKey={direction} options={[{ id: "up", label: zh ? "上涨至少" : "Up at least" }, { id: "down", label: zh ? "下跌至少" : "Down at least" }]} onSelectionChange={key => setDirection(String(key) as "up" | "down")} /><label className={styles.field}>%<VInput aria-label="核验涨跌阈值" type="number" min={0} max={100} value={threshold} onChange={event => setThreshold(event.target.value)} /></label></div>
        <label className={styles.panel}>{zh ? "报告判断与备注" : "Claim and note"}<VTextarea aria-label="核验判断" value={claim} maxLength={500} onChange={event => setClaim(event.target.value)} /></label>
        {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
      </div>
    </VDialog>
  </>;
}
