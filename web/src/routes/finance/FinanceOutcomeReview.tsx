import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { checkFinancialClaim, fetchFinancialClaims, fetchFinancialFeedback, financialEvaluationKeys, saveFinancialLesson } from "../../api/financialEvaluation";
import type { FinancialClaim } from "../../api/types/financialEvaluation";
import { VButton, VDialog, VInput, VStateSurface, VSurface, VTextarea } from "../../components/vui";
import styles from "./FinanceEvaluation.styles";

export function FinanceOutcomeReview({ agentId, zh, disabled, onResearchPrompt, onOpenReport }: { agentId: string; zh: boolean; disabled: boolean; onResearchPrompt: (text: string) => void; onOpenReport: (target: { sessionId: string; turnId: string }) => void }) {
  const client = useQueryClient(), query = useQuery({ queryKey: financialEvaluationKeys.claims(agentId), queryFn: ({ signal }) => fetchFinancialClaims(agentId, signal), staleTime: 10_000, refetchInterval: 30_000, retry: false });
  const [pending, setPending] = useState(""), [error, setError] = useState(""), [lesson, setLesson] = useState<FinancialClaim | null>(null), [text, setText] = useState(""), [search, setSearch] = useState("");
  const gate = useRef(false), saveRequest = useRef<{ fingerprint: string; id: string } | null>(null);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function action(row: FinancialClaim, mode: "check" | "feedback" | "lesson") {
    if (gate.current) return;
    gate.current = true; setPending(`${row.id}:${mode}`); setError("");
    try {
      if (mode === "check") { await checkFinancialClaim(agentId, row.id); await client.invalidateQueries({ queryKey: financialEvaluationKeys.claims(agentId) }); }
      else if (mode === "feedback") { const data = await fetchFinancialFeedback(agentId, row.id); if (!mounted.current) return; if (data.id !== row.id || !data.text) throw new Error("复盘身份不匹配"); onResearchPrompt(data.text); }
      else {
        const fingerprint = `${row.id}:${text.trim()}`;
        if (saveRequest.current?.fingerprint !== fingerprint) saveRequest.current = { fingerprint, id: crypto.randomUUID() };
        await saveFinancialLesson(agentId, row.id, text.trim(), saveRequest.current.id);
        await Promise.all([client.invalidateQueries({ queryKey: financialEvaluationKeys.claims(agentId) }), client.invalidateQueries({ queryKey: ["finance", "reflection-context", agentId] })]);
        if (mounted.current) setLesson(null);
      }
    } catch (cause) { if (mounted.current) setError(cause instanceof Error ? cause.message : "操作失败"); }
    finally { gate.current = false; if (mounted.current) setPending(""); }
  }
  const all = query.data?.items ?? [];
  const scored = all.filter(row => row.status === "verified" && row.registeredBeforeDue && !row.retrospective);
  const hits = scored.filter(row => row.outcome === "hit").length;
  const rows = all.filter(row => `${row.symbol} ${row.claimText}`.toLowerCase().includes(search.toLowerCase()));
  const status = (row: FinancialClaim) => row.status === "verified" ? row.outcome === "hit" ? (zh ? "命中" : "Hit") : (zh ? "未命中" : "Miss") : row.status === "pending" ? (zh ? "待到期" : "Pending") : row.status === "due" ? (zh ? "待核验" : "Due") : (zh ? "无法核验" : "Unavailable");
  return <div className={styles.page}>
    <div className={styles.row}><h3 className={styles.title}>{zh ? "报告结论核验" : "Report outcome checks"}</h3><VButton variant="ghost" isPending={query.isFetching} onPress={() => void query.refetch()}>{zh ? "刷新" : "Refresh"}</VButton></div>
    <p className={styles.note}>{zh ? "在报告详情登记判断。应用运行时检查到期项；缺少完整日线可手动重试。核验只衡量登记的涨跌规则，不证明判断因果。" : "Track a claim from report details. Due checks run while the app is open; retry incomplete data. A price rule does not establish causality."}</p>
    <div className={styles.row}><strong className={styles.status}>{zh ? `事前登记 ${scored.length} · 命中 ${hits}` : `Prospective ${scored.length} · Hits ${hits}`}</strong><span className={styles.note}>{zh ? `待到期 ${all.filter(row => row.status === "pending").length} · 待核验 ${all.filter(row => row.status === "due").length}` : `Pending ${all.filter(row => row.status === "pending").length}`}</span><VInput aria-label="核验记录搜索" placeholder={zh ? "代码 / 判断" : "Symbol / claim"} value={search} onChange={event => setSearch(event.target.value)} /></div>
    {error && !lesson ? <VStateSurface tone="error" density="compact" title={error} /> : null}
    {query.isPending ? <VStateSurface tone="loading" busy title={zh ? "读取核验记录" : "Loading checks"} /> : query.isError ? <VStateSurface tone="error" title={query.error.message} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : !rows.length ? <VStateSurface tone="empty" title={zh ? "没有核验记录" : "No tracked claims"}>{zh ? "打开已完成的股票报告，选择「登记到期核验」。" : "Open a completed stock report and select Track outcome."}</VStateSurface> : rows.map(row => <VSurface key={row.id} tone="panel" padding="normal" className={styles.panel}>
      <div className={styles.row}><strong>{row.symbol}</strong><span className={styles.status}>{status(row)}</span><span className={styles.note}>{row.analysisDate} → {row.dueDate} · {row.direction === "up" ? "↑" : "↓"} {row.thresholdPct}%{row.retrospective ? (zh ? " · 事后回顾" : " · Retrospective") : ""}</span></div>
      <p className="m-0 break-words text-xs">{row.claimText}</p>
      {row.evidence ? <p className={styles.note}>{row.evidence.baseDate} {row.evidence.baseClose.toFixed(3)} → {row.evidence.dueDateQuoteDate} {row.evidence.dueClose.toFixed(3)} · {row.evidence.returnPct.toFixed(2)}% · <a href={row.evidence.sourceUrl} target="_blank" rel="noreferrer">{zh ? "行情来源" : "Source"}</a></p> : null}
      {row.error ? <VStateSurface tone="error" density="compact" title={row.error.unavailableReason} /> : null}
      {row.lesson ? <p className={styles.note}>{zh ? "已确认教训：" : "Confirmed lesson: "}{row.lesson.text}</p> : null}
      <div className={styles.row}><VButton variant="secondary" onPress={() => onOpenReport(row)}>{zh ? "原报告" : "Report"}</VButton><VButton isDisabled={Boolean(pending) || row.status === "pending" || row.status === "verified"} isPending={pending === `${row.id}:check`} onPress={() => void action(row, "check")}>{zh ? "核验 / 重试" : "Check / retry"}</VButton><VButton isDisabled={disabled || Boolean(pending) || row.status !== "verified"} isPending={pending === `${row.id}:feedback`} onPress={() => void action(row, "feedback")}>{zh ? "开始AI复盘" : "Start AI review"}</VButton><VButton variant="ghost" isDisabled={Boolean(pending) || row.status !== "verified" || Boolean(row.lesson)} onPress={() => { setLesson(row); setText(""); setError(""); }}>{zh ? "确认研究教训" : "Confirm lesson"}</VButton></div>
    </VSurface>)}
    <VDialog open={Boolean(lesson)} onOpenChange={open => { if (!open && !pending) setLesson(null); }} title={zh ? "确认可复用的研究教训" : "Confirm a reusable lesson"} footer={<VButton variant="primary" isDisabled={!text.trim() || Boolean(pending)} isPending={Boolean(pending)} onPress={() => { if (lesson) void action(lesson, "lesson"); }}>{zh ? "保存到助手记忆" : "Save to agent memory"}</VButton>}><div className={styles.panel}><p className={styles.note}>{zh ? "写下经复盘确认的改进。绑定原报告和行情核验；后续同股票研究会读取，历史日期早于此反馈时不使用。" : "Confirm the improvement after review. It stays linked to the report and evidence and is used in later research of this stock."}</p><VTextarea aria-label="研究教训" value={text} maxLength={500} onChange={event => setText(event.target.value)} />{error ? <VStateSurface tone="error" title={error} /> : null}</div></VDialog>
  </div>;
}
