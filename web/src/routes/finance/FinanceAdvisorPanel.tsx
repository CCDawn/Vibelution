import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { checkFinancialAdvisorPlan, fetchFinancialAdvisorProposal, financialAdvisorCommand, financialWorkspaceKey } from "../../api/financialPreferences";
import type { FinancialAdvisorCheck, FinancialAdvisorCommand, FinancialInvestmentPlan, FinancialPlanDraft, FinancialWorkspaceSettings } from "../../api/types/financialPreferences";
import { VButton, VDialog, VStateSurface } from "../../components/vui";
import { FinanceAdvisorExecution } from "./FinanceAdvisorExecution";
import { ADVISOR_PLAN_PROMPT, advisorCheckText, investmentConditionRows, latestAdvisorProposalTurn } from "./financeAdvisorModel";
import type { FinancialSessionView } from "./FinancialResearchBridge";
import { useFinanceWorkspace } from "./useFinanceWorkspace";
import styles from "./FinanceAdvisorPanel.styles";

const labels = {
  proposed: ["待采纳", "Proposed"], adopted: ["已采纳，尚未记录执行", "Adopted, not recorded as executed"],
  executed: ["已记录执行", "Execution recorded"], invalidated: ["已失效", "Invalidated"],
} as const;

function PlanDetails({ plan, zh }: { plan: FinancialPlanDraft; zh: boolean }) {
  return <div className={styles.section}>
    <strong className={styles.heading}>{plan.title}</strong>
    <p className={styles.summary}>{plan.rationale}</p>
    {plan.orders.length ? <ul className={styles.list}>{plan.orders.map((order, index) => <li key={`${order.symbol}-${index}`}>{order.symbol} · {order.side === "buy" ? (zh ? "买入" : "Buy") : (zh ? "卖出" : "Sell")} {order.quantity} {zh ? "股" : "shares"}</li>)}</ul> : <p>{zh ? "本方案不包含交易，继续观察。" : "No orders; continue observing."}</p>}
    <p className={styles.caption}>{zh ? "下次复核：" : "Review after: "}{plan.reviewAfter ? new Date(plan.reviewAfter).toLocaleString() : (zh ? "未设置" : "Not set")}</p>
  </div>;
}

/** A compact projection of the private workspace; native Session remains the conversation. */
export function FinanceAdvisorPanel({ agentId, view, zh, onConditions, onResearch }: {
  agentId: string; view: FinancialSessionView | null; zh: boolean;
  onConditions: () => void; onResearch: (text: string) => void;
}) {
  const workspace = useFinanceWorkspace(agentId), client = useQueryClient();
  const state = workspace.query.data;
  const [open, setOpen] = useState(false);
  const [execution, setExecution] = useState<{ planId: string; state: FinancialWorkspaceSettings } | null>(null);
  const [pending, setPending] = useState(false), [error, setError] = useState(""), [saved, setSaved] = useState("");
  const [check, setCheck] = useState<{ planId: string; revision: number; value: FinancialAdvisorCheck } | null>(null);
  const [handled, setHandled] = useState<string | null>(null);
  const gate = useRef(false);
  const turnId = latestAdvisorProposalTurn(view?.agentId === agentId ? view.messages ?? [] : []);
  const sourceKey = `${view?.sessionId ?? ""}/${turnId ?? ""}`;
  const proposalQuery = useQuery({
    queryKey: ["finance", "advisor-proposal", agentId, view?.sessionId, turnId],
    queryFn: ({ signal }) => fetchFinancialAdvisorProposal(agentId, view!.sessionId, turnId!, { signal }),
    enabled: Boolean(turnId && !view?.busy && handled !== sourceKey),
    staleTime: Infinity, retry: false,
  });
  const proposal = handled !== sourceKey ? proposalQuery.data?.proposal : null;
  const plans = state?.investmentPlans ?? [];
  const current: FinancialInvestmentPlan | undefined = plans[plans.length - 1];
  const sourceSaved = plans.some(plan => plan.source.sessionId === view?.sessionId && plan.source.turnId === turnId);
  const freshProposal = proposal && !sourceSaved;
  const unrecognizedProposal = turnId && handled !== sourceKey && proposalQuery.isSuccess && !proposal;
  const proposalStale = proposal?.baseFingerprint !== state?.investmentStateFingerprint;
  const checked = check && check.planId === current?.id && check.revision === state?.revision ? check.value : null;
  async function command(payload: FinancialAdvisorCommand) {
    if (gate.current) return;
    gate.current = true; setPending(true); setError(""); setSaved("");
    try {
      const result = await financialAdvisorCommand(agentId, payload);
      if (result.agentId !== agentId || result.revision <= payload.expectedRevision) throw new Error(zh ? "保存结果身份或版本无效" : "Invalid saved identity or revision");
      client.setQueryData(financialWorkspaceKey(agentId), result);
      setCheck(null); setExecution(null);
      if (payload.action === "confirm_proposal") setHandled(sourceKey);
      setSaved(zh ? "已保存，下次对话会读取最新状态。" : "Saved. Your next turn will use this state.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      await workspace.query.refetch();
      throw cause;
    } finally { setPending(false); gate.current = false; }
  }
  function run(payload: FinancialAdvisorCommand) { void command(payload).catch(() => undefined); }
  async function validate() {
    if (!current || !state || gate.current) return;
    gate.current = true; setPending(true); setError("");
    try { const result = await checkFinancialAdvisorPlan(agentId, current.id); setCheck({ planId: current.id, revision: state.revision, value: result }); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setPending(false); gate.current = false; }
  }
  const status = current ? current.needsReview && current.status !== "invalidated" ? (zh ? "待复核" : "Needs review") : labels[current.status][zh ? 0 : 1] : (zh ? "尚无方案" : "No plan");
  return <>
    <div className={styles.strip} aria-label={zh ? "投资摘要" : "Investment summary"}>
      <VButton variant="ghost" onPress={onConditions}>{zh ? "投资条件" : "Conditions"} · {state?.investmentProfile?.budgetCny == null ? (zh ? "待确认" : "Unknown") : `¥${state.investmentProfile.budgetCny.toLocaleString()}`}</VButton>
      <VButton variant="ghost" onPress={() => setOpen(true)}>{freshProposal ? (zh ? "查看待确认内容" : "Review proposal") : unrecognizedProposal || proposalQuery.isError ? (zh ? "建议需要重新核对" : "Proposal needs attention") : `${zh ? "当前方案" : "Plan"} · ${status}`}</VButton>
      {current?.reviewAfter ? <span className={styles.caption}>{zh ? "下次复核 " : "Next review "}{new Date(current.reviewAfter).toLocaleDateString()}</span> : null}
    </div>
    <VDialog open={open} onOpenChange={setOpen} title={zh ? "我的投资方案" : "My investment plan"} size="lg">
      <div className={styles.root}>
        {workspace.query.isError ? <VStateSurface tone="error" title={zh ? "投资状态读取失败" : "Cannot read investment state"} actions={<VButton onPress={() => void workspace.query.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : !state ? <p>{zh ? "正在读取…" : "Loading…"}</p> : <>
          {freshProposal ? <section className={styles.section}>
            <strong>{zh ? "对话提出了以下修改，请核对后保存" : "Review the proposed changes before saving"}</strong>
            {proposal.kind === "profile" ? <div className={styles.rows}>{investmentConditionRows(proposal.profile, zh).map(([label, value], index) => {
              const previous = investmentConditionRows(state.investmentProfile, zh)[index][1];
              return <div className={styles.row} key={label}><strong>{label}</strong><span>{value}</span>{value !== previous ? <span className={styles.difference}>{zh ? "原来：" : "Previously: "}{previous}</span> : null}</div>;
            })}</div> : <PlanDetails plan={proposal.plan} zh={zh} />}
            {proposalStale ? <p role="status">{zh ? "投资条件或持仓已改变，请让助手基于最新状态重新提出修改。" : "Conditions or holdings changed. Ask the advisor for an updated proposal."}</p> : null}
            <div className={styles.actions}><VButton isDisabled={pending || proposalStale} onPress={() => run({ action: "confirm_proposal", expectedRevision: state.revision, sessionId: view!.sessionId, turnId: turnId! })}>{zh ? "确认保存" : "Confirm and save"}</VButton><VButton variant="ghost" isDisabled={pending} onPress={() => setHandled(sourceKey)}>{zh ? "暂不保存" : "Not now"}</VButton></div>
          </section> : null}
          {proposalQuery.isError ? <VStateSurface tone="error" density="compact" title={zh ? "对话建议无法核验，尚未保存" : "Could not verify the proposal; nothing saved"} actions={<VButton onPress={() => void proposalQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : null}
          {unrecognizedProposal ? <p role="status">{zh ? "这条建议暂不能作为有效方案保存，请让助手基于当前条件重新整理。" : "This suggestion cannot be saved as a valid proposal. Ask the advisor to prepare it again using current conditions."}</p> : null}
          {current ? <section className={styles.section}>
            <strong>{status}</strong><PlanDetails plan={current} zh={zh} />
            <p className={styles.caption}>{zh ? "建议和采纳不会修改实际持仓。复核时间只作提示，目前不会自动启动研究。" : "Suggestions and adoption do not change holdings. The review date is a reminder here; research does not start automatically."}</p>
            {current.needsReview && current.status !== "invalidated" ? <p role="status">{zh ? "条件、持仓或复核时间发生变化，请先在主会话重新分析。" : "State or review timing changed. Reassess in the main conversation."}</p> : null}
            {current.status === "proposed" || current.status === "adopted" ? <div className={styles.actions}>
              <VButton variant="secondary" isDisabled={pending || current.needsReview} onPress={() => void validate()}>{zh ? "核算金额与仓位" : "Check amounts and allocation"}</VButton>
              {current.status === "proposed" ? <VButton isDisabled={pending || current.needsReview || !checked?.passed} onPress={() => run({ action: "adopt", planId: current.id, expectedRevision: state.revision })}>{zh ? "采纳方案" : "Adopt plan"}</VButton> : <VButton isDisabled={pending || current.needsReview} onPress={() => setExecution(execution ? null : { planId: current.id, state: structuredClone(state) })}>{zh ? "记录实际执行" : "Record actual execution"}</VButton>}
              <VButton variant="ghost" isDisabled={pending} onPress={() => run({ action: "invalidate", planId: current.id, expectedRevision: state.revision })}>{zh ? "标记失效" : "Invalidate"}</VButton>
            </div> : null}
            {checked ? <div className={styles.section} role="status"><strong>{checked.passed ? (zh ? "金额约束检查通过" : "Amount checks passed") : (zh ? "暂不满足采纳条件" : "Cannot adopt yet")}</strong>
              <p>{zh ? "预计费用：" : "Estimated fees: "}{checked.feesCny.toFixed(2)} CNY · {zh ? "预计剩余现金：" : "Estimated cash: "}{checked.cashAfterCny == null ? (zh ? "未知" : "Unknown") : `${checked.cashAfterCny.toFixed(2)} CNY`}</p>
              <ul className={styles.list}>{[...checked.blockers, ...checked.warnings].map((text, index) => <li key={index}>{advisorCheckText(text)}</li>)}</ul>
            </div> : null}
            {execution && current.status === "adopted" ? <>
              <VButton variant="ghost" isDisabled={pending} onPress={() => setExecution(null)}>{zh ? "关闭执行表单" : "Close execution form"}</VButton>
              {execution.state.revision !== state.revision || execution.planId !== current.id ? <p role="status">{zh ? "记录期间投资状态发生变化，请关闭执行表单后重新核对。" : "Investment state changed. Close and reopen the execution form to review it again."}</p> : null}
              <FinanceAdvisorExecution key={`${execution.planId}-${execution.state.revision}`} initialCash={execution.state.investmentProfile?.availableCashCny ?? null} initialPositions={execution.state.manualPositions} pending={pending || execution.state.revision !== state.revision || execution.planId !== current.id || current.needsReview} zh={zh} onConfirm={(actualCashCny, actualPositions) => command({ action: "execute", expectedRevision: execution.state.revision, planId: execution.planId, actualCashCny, actualPositions })} />
            </> : null}
          </section> : <p>{zh ? "先在主会话说明预算和想法。助手提出方案后，在这里核对并保存。" : "Discuss your budget and goals in the main conversation, then review and save its proposal here."}</p>}
          <div className={styles.actions}><VButton variant="ghost" isDisabled={pending || Boolean(view?.busy)} onPress={() => { setOpen(false); onResearch(ADVISOR_PLAN_PROMPT); }}>{zh ? "在主会话分析 / 复核" : "Analyze / review in main conversation"}</VButton></div>
          <p className={styles.caption}>{zh ? "状态更新：" : "State updated: "}{state.updatedAt ? new Date(state.updatedAt).toLocaleString() : (zh ? "尚未保存" : "Not saved")}</p>
        </>}
        {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
        {saved ? <p role="status">{saved}</p> : null}
      </div>
    </VDialog>
  </>;
}
