import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  approveFinancialPortfolioProposal,
  createFinancialPortfolioProposal,
  fetchFinancialPortfolioProposal,
  fetchFinancialPortfolioProposals,
  financialPortfolioKeys,
  isFinancialPortfolioProposalNotFound,
  previewFinancialPortfolioProposal,
} from "../../api/financialPortfolio";
import { financialPaperKeys } from "../../api/financialPaper";
import { fetchFinancialReports, financialReportKeys, type FinancialReportSummary } from "../../api/financialReports";
import type {
  FinancialPortfolioPosition,
  FinancialPortfolioProposal,
  FinancialPortfolioProposalCreateRequest,
  FinancialPortfolioRebalancePolicy,
  FinancialPortfolioRebalanceTarget,
} from "../../api/types/financialPortfolio";
import { VButton, VCheckbox, VDenseTable, VDialog, VInput, VStateSurface, VSurface, VTextarea, type VDenseTableColumn } from "../../components/vui";
import styles from "./FinanceRebalance.styles";

const DEFAULT_POLICY: FinancialPortfolioRebalancePolicy = {
  maxPositionPct: 30,
  minCashPct: 10,
  maxTurnoverPct: 100,
  maxQuoteAgeHours: 72,
};

const statusLabels: Record<FinancialPortfolioProposal["status"], { zh: string; en: string }> = {
  generating: { zh: "生成中", en: "Generating" },
  ready: { zh: "待批准", en: "Ready" },
  blocked: { zh: "风控阻断", en: "Blocked" },
  failed: { zh: "生成失败", en: "Failed" },
  executed: { zh: "已模拟执行", en: "Executed" },
};

type CreateAttempt = { request: FinancialPortfolioProposalCreateRequest; retryAllowed: boolean };
type ActionResult<T> = { ok: true; value: T } | { ok: false; error: unknown; stale?: boolean };

function reportKey(report: Pick<FinancialReportSummary, "sessionId" | "turnId">) {
  return JSON.stringify([report.sessionId, report.turnId]);
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败，请重试";
}

function money(value: string, zh: boolean): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "—";
  return new Intl.NumberFormat(zh ? "zh-CN" : "en-US", { style: "currency", currency: "CNY", maximumFractionDigits: 2 }).format(parsed);
}

function formatTime(value: string, zh: boolean): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(zh ? "zh-CN" : "en-US", { hour12: false, timeZone: "Asia/Shanghai" });
}

function parseSymbols(value: string): string[] {
  return [...new Set(value.split(/[,，;；\s]+/).map((item) => item.trim().toUpperCase()).filter(Boolean))];
}

function validPolicy(policy: FinancialPortfolioRebalancePolicy): boolean {
  return Number.isFinite(policy.maxPositionPct) && policy.maxPositionPct >= 1 && policy.maxPositionPct <= 100
    && Number.isFinite(policy.minCashPct) && policy.minCashPct >= 0 && policy.minCashPct <= 100
    && Number.isFinite(policy.maxTurnoverPct) && policy.maxTurnoverPct >= 0 && policy.maxTurnoverPct <= 200
    && Number.isFinite(policy.maxQuoteAgeHours) && policy.maxQuoteAgeHours >= 1 && policy.maxQuoteAgeHours <= 168;
}

function validTargets(targets: FinancialPortfolioRebalanceTarget[]): boolean {
  return targets.length > 0 && targets.every((target) => Number.isFinite(target.weightPct)
    && target.weightPct >= 0 && target.weightPct <= 100 && target.reason.trim().length > 0 && target.reason.length <= 500);
}

export function FinanceRebalance({ agentId, positions, zh }: { agentId: string; positions: FinancialPortfolioPosition[]; zh: boolean }) {
  const queryClient = useQueryClient();
  const [symbolsText, setSymbolsText] = useState(() => positions.map((position) => position.symbol).join(", "));
  const [instruction, setInstruction] = useState("");
  const [policy, setPolicy] = useState<FinancialPortfolioRebalancePolicy>(() => ({ ...DEFAULT_POLICY }));
  const [selectedReports, setSelectedReports] = useState<Map<string, FinancialReportSummary>>(() => new Map());
  const [selectedProposalId, setSelectedProposalId] = useState("");
  const [editedTargets, setEditedTargets] = useState<FinancialPortfolioRebalanceTarget[]>([]);
  const [editedPolicy, setEditedPolicy] = useState<FinancialPortfolioRebalancePolicy>(() => ({ ...DEFAULT_POLICY }));
  const [planDirty, setPlanDirty] = useState(false);
  const [createAttempt, setCreateAttempt] = useState<CreateAttempt | null>(null);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const [, refreshExpiry] = useState(0);
  const gate = useRef(false);
  const agentRef = useRef(agentId);
  const agentEpoch = useRef(0);

  useLayoutEffect(() => {
    if (agentRef.current === agentId) return;
    agentRef.current = agentId;
    agentEpoch.current += 1;
    gate.current = false;
  }, [agentId]);

  useEffect(() => {
    setSymbolsText(positions.map((position) => position.symbol).join(", "));
    setInstruction("");
    setPolicy({ ...DEFAULT_POLICY });
    setSelectedReports(new Map());
    setSelectedProposalId("");
    setEditedTargets([]);
    setEditedPolicy({ ...DEFAULT_POLICY });
    setPlanDirty(false);
    setCreateAttempt(null);
    setApprovalOpen(false);
    setPending("");
    setError("");
  }, [agentId]);

  const reportFilters = useMemo(() => ({ kind: "research" as const, limit: 30 }), []);
  const reportCatalog = useInfiniteQuery({
    queryKey: financialReportKeys.catalog(agentId, reportFilters),
    queryFn: ({ signal, pageParam }) => fetchFinancialReports(agentId, { ...reportFilters, cursor: pageParam }, { signal }),
    initialPageParam: "",
    getNextPageParam: (page) => page.nextCursor || undefined,
    retry: false,
  });
  const reports = reportCatalog.data?.pages.flatMap((page) => page.items) ?? [];
  const proposalList = useQuery({
    queryKey: financialPortfolioKeys.proposals(agentId),
    queryFn: ({ signal }) => fetchFinancialPortfolioProposals(agentId, { signal }),
    staleTime: 10_000,
    retry: false,
    refetchInterval: (query) => query.state.data?.items.some((item) => item.status === "generating") ? 2_000 : false,
  });
  const proposalDetail = useQuery({
    queryKey: financialPortfolioKeys.proposal(agentId, selectedProposalId),
    queryFn: ({ signal }) => fetchFinancialPortfolioProposal(agentId, selectedProposalId, { signal }),
    enabled: Boolean(selectedProposalId),
    retry: false,
    refetchInterval: (query) => query.state.data?.status === "generating" ? 2_000 : false,
  });
  const proposal = proposalDetail.data?.proposalId === selectedProposalId ? proposalDetail.data : null;
  const symbols = useMemo(() => parseSymbols(symbolsText), [symbolsText]);
  const selectedReportRows = [...selectedReports.values()];
  const frozenCreateForm = Boolean(createAttempt) || pending === "create" || pending === "readback";

  useEffect(() => {
    if (!proposal) return;
    setEditedTargets(proposal.targets.map((target) => ({ ...target })));
    setEditedPolicy({ ...proposal.policy });
    setPlanDirty(false);
    setError("");
  }, [proposal?.proposalId, proposal?.planHash]);

  useEffect(() => {
    if (!proposal?.expiresAt) return;
    const expiry = Date.parse(proposal.expiresAt);
    if (!Number.isFinite(expiry)) return;
    const timer = window.setTimeout(() => refreshExpiry((value) => value + 1), Math.min(2_147_000_000, Math.max(0, expiry - Date.now() + 1)));
    return () => window.clearTimeout(timer);
  }, [proposal?.proposalId, proposal?.expiresAt]);

  async function runAction<T>(kind: string, action: () => Promise<T>): Promise<ActionResult<T>> {
    if (gate.current) return { ok: false, error: new Error("请等待当前操作完成") };
    const actionEpoch = agentEpoch.current;
    const actionAgent = agentId;
    const isCurrent = () => agentRef.current === actionAgent && agentEpoch.current === actionEpoch;
    gate.current = true;
    setPending(kind);
    setError("");
    try {
      const value = await action();
      return isCurrent() ? { ok: true, value } : { ok: false, error: new Error("助手已切换"), stale: true };
    } catch (cause) {
      if (isCurrent()) setError(errorText(cause));
      return { ok: false, error: cause, stale: !isCurrent() };
    } finally {
      if (isCurrent()) {
        gate.current = false;
        setPending("");
      }
    }
  }

  function selectReport(report: FinancialReportSummary, checked: boolean) {
    setSelectedReports((current) => {
      const next = new Map(current);
      const key = reportKey(report);
      if (checked) {
        if (next.size < 5) next.set(key, report);
      } else next.delete(key);
      return next;
    });
  }

  function selectProposal(id: string) {
    setSelectedProposalId(id);
    setPlanDirty(false);
    setError("");
  }

  function startNewProposal() {
    if (pending || createAttempt) return;
    setSelectedProposalId("");
    setEditedTargets([]);
    setEditedPolicy({ ...policy });
    setPlanDirty(false);
    setError("");
  }

  function buildCreateRequest(): FinancialPortfolioProposalCreateRequest {
    return {
      clientRequestId: crypto.randomUUID(),
      symbols,
      reports: selectedReportRows.map(({ sessionId, turnId }) => ({ sessionId, turnId })),
      instruction: instruction.trim(),
      policy: { ...policy },
    };
  }

  async function submitCreate(request: FinancialPortfolioProposalCreateRequest, retry = false) {
    if (pending || gate.current) return;
    setCreateAttempt({ request, retryAllowed: false });
    setSelectedProposalId(request.clientRequestId);
    const requestPromise = createFinancialPortfolioProposal(agentId, request);
    void queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.proposals(agentId) });
    const outcome = await runAction("create", () => requestPromise);
    if (!outcome.ok) {
      if (outcome.stale) return;
      setCreateAttempt({ request, retryAllowed: false });
      if (retry) setError(zh ? "同一请求重试仍未确认结果。请先读取该 UUID 的结果，再决定是否安全重试。" : "The retry result is still unknown. Read this UUID before deciding whether another same-ID retry is safe.");
      return;
    }
    queryClient.setQueryData(financialPortfolioKeys.proposal(agentId, outcome.value.proposalId), outcome.value);
    setSelectedProposalId(outcome.value.proposalId);
    setCreateAttempt(null);
    setPlanDirty(false);
    void queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.proposals(agentId) });
  }

  async function readUnknownCreate() {
    if (!createAttempt || pending) return;
    const request = createAttempt.request;
    const outcome = await runAction("readback", () => fetchFinancialPortfolioProposal(agentId, request.clientRequestId));
    if (!outcome.ok && outcome.stale) return;
    if (outcome.ok) {
      queryClient.setQueryData(financialPortfolioKeys.proposal(agentId, outcome.value.proposalId), outcome.value);
      setSelectedProposalId(outcome.value.proposalId);
      setCreateAttempt(null);
      return;
    }
    if (isFinancialPortfolioProposalNotFound(outcome.error)) {
      setCreateAttempt({ request, retryAllowed: true });
      setError(zh ? "服务器尚无此 UUID 的记录；可使用原请求内容和相同 UUID 重试。" : "No record exists for this UUID; retry the identical request with the same UUID.");
    }
  }

  async function previewEditedPlan() {
    if (!proposal || (!planDirty && !isExpired) || pending || !validTargets(editedTargets) || !validPolicy(editedPolicy)) return;
    const outcome = await runAction("preview", () => previewFinancialPortfolioProposal(agentId, proposal.proposalId, {
      targets: editedTargets,
      policy: editedPolicy,
    }));
    if (!outcome.ok) return;
    queryClient.setQueryData(financialPortfolioKeys.proposal(agentId, proposal.proposalId), outcome.value);
    setPlanDirty(false);
    void queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.proposals(agentId) });
  }

  async function approvePlan() {
    if (!proposal || !canApprove || pending) return;
    const requestedEpoch = agentEpoch.current;
    const outcome = await runAction("approve", () => approveFinancialPortfolioProposal(agentId, proposal.proposalId, {
      planHash: proposal.planHash,
      confirmSimulation: true,
    }));
    if (!outcome.ok) {
      if (outcome.stale) return;
      setPlanDirty(true);
      try {
        const readback = await fetchFinancialPortfolioProposal(agentId, proposal.proposalId);
        if (agentRef.current !== agentId || agentEpoch.current !== requestedEpoch) return;
        queryClient.setQueryData(financialPortfolioKeys.proposal(agentId, proposal.proposalId), readback);
        if (readback.status === "executed") {
          setPlanDirty(false);
          setApprovalOpen(false);
          void Promise.all([
            queryClient.invalidateQueries({ queryKey: financialPaperKeys.account(agentId) }),
            queryClient.invalidateQueries({ queryKey: ["financial-paper", agentId, "review"] }),
            queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.research(agentId) }),
            queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.proposals(agentId) }),
          ]);
        }
      } catch {
        // Keep approval disabled until the user can recheck or reload this exact proposal.
      }
      return;
    }
    setApprovalOpen(false);
    queryClient.setQueryData(financialPortfolioKeys.proposal(agentId, proposal.proposalId), outcome.value);
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: financialPaperKeys.account(agentId) }),
      queryClient.invalidateQueries({ queryKey: ["financial-paper", agentId, "review"] }),
      queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.research(agentId) }),
      queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.proposals(agentId) }),
    ]);
  }

  function editTarget(symbol: string, key: "weightPct" | "reason", value: string) {
    setEditedTargets((current) => current.map((target) => target.symbol !== symbol ? target : {
      ...target,
      [key]: key === "weightPct" ? Number(value) : value,
    }));
    setPlanDirty(true);
  }

  function editPlanPolicy(key: keyof FinancialPortfolioRebalancePolicy, value: number) {
    setEditedPolicy((current) => ({ ...current, [key]: value }));
    setPlanDirty(true);
  }

  const canCreate = !pending && !createAttempt && symbols.length > 0 && symbols.length <= 10
    && selectedReportRows.length > 0 && instruction.trim().length > 0 && instruction.length <= 2_000 && validPolicy(policy);
  const parsedExpiry = proposal?.expiresAt ? Date.parse(proposal.expiresAt) : Number.NaN;
  const isExpired = !Number.isFinite(parsedExpiry) || parsedExpiry <= Date.now();
  const canPreview = !pending && (planDirty || isExpired) && validTargets(editedTargets) && validPolicy(editedPolicy);
  const allRiskChecksPassed = Boolean(proposal?.riskChecks.length && proposal.riskChecks.every((check) => check.passed));
  const canApprove = Boolean(proposal && proposal.status === "ready" && proposal.orders.length > 0 && proposal.planHash
    && !planDirty && !isExpired && allRiskChecksPassed && !pending);

  const targetColumns = useMemo<VDenseTableColumn<FinancialPortfolioRebalanceTarget>[]>(() => [
    { id: "symbol", header: zh ? "股票" : "Stock", width: 100, minWidth: 90, render: (row) => <span>{row.symbol}</span> },
    { id: "weight", header: zh ? "目标仓位 %" : "Target %", width: 140, minWidth: 130, render: (row) => <VInput aria-label={`${row.symbol}目标仓位`} type="number" min="0" max="100" step="0.1" value={String(row.weightPct)} disabled={proposal?.status === "executed" || proposal?.status === "failed" || proposal?.status === "generating" || pending !== ""} onChange={(event) => editTarget(row.symbol, "weightPct", event.target.value)} /> },
    { id: "reason", header: zh ? "建议依据" : "Reason", fill: true, minWidth: 180, render: (row) => <VInput aria-label={`${row.symbol}目标依据`} maxLength={500} value={row.reason} disabled={proposal?.status === "executed" || proposal?.status === "failed" || proposal?.status === "generating" || pending !== ""} onChange={(event) => editTarget(row.symbol, "reason", event.target.value)} /> },
  ], [proposal?.status, pending, zh]);

  const orderColumns: VDenseTableColumn<NonNullable<FinancialPortfolioProposal>["orders"][number]>[] = [
    { id: "symbol", header: zh ? "股票" : "Stock", fill: true, minWidth: 130, render: (row) => <span>{row.name} · {row.symbol}</span> },
    { id: "side", header: zh ? "方向" : "Side", width: 70, render: (row) => row.side === "buy" ? (zh ? "买入" : "Buy") : (zh ? "卖出" : "Sell") },
    { id: "quantity", header: zh ? "数量" : "Shares", width: 92, align: "right", render: (row) => row.quantity.toLocaleString() },
    { id: "price", header: zh ? "参考价" : "Mark", width: 96, align: "right", render: (row) => money(row.priceYuan, zh) },
    { id: "gross", header: zh ? "金额" : "Gross", width: 116, align: "right", render: (row) => money(row.grossAmountYuan, zh) },
    { id: "fee", header: zh ? "费用" : "Fee", width: 96, align: "right", render: (row) => money(row.feeYuan, zh) },
  ];

  return <section className={styles.section} aria-label={zh ? "组合调仓建议" : "Portfolio rebalance proposal"}>
    <header className={styles.heading}>
      <div>
        <h3>{zh ? "组合调仓" : "Portfolio rebalance"}</h3>
        <p className={styles.note}>{zh ? "使用已完成研究报告生成模拟仓位建议；订单只会在你核对精确计划并批准后写入模拟账本。" : "Build a paper allocation from completed reports. Orders enter the paper ledger only after you review and approve the exact plan."}</p>
      </div>
      <VButton variant="secondary" isDisabled={Boolean(pending) || Boolean(createAttempt)} onPress={startNewProposal}>{zh ? "新建建议" : "New proposal"}</VButton>
    </header>

    <div className={styles.layout}>
      <VSurface tone="panel" padding="normal" className={styles.panel}>
        <h4 className={styles.panelTitle}>{zh ? "研究输入与风控" : "Research inputs and risk policy"}</h4>
        <p className={styles.note}>{zh ? "最多选5份已完成研究；服务端会按原生 Session/Turn 重新读取正文并核验归属。" : "Select up to five completed reports. The server reloads the exact native Session/Turn and verifies ownership."}</p>
        {reportCatalog.isPending ? <VStateSurface tone="loading" density="compact" busy title={zh ? "读取已完成研究报告" : "Loading completed reports"} /> : reportCatalog.isError ? <VStateSurface tone="error" density="compact" title={errorText(reportCatalog.error)} actions={<VButton onPress={() => void reportCatalog.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : !reports.length ? <VStateSurface tone="empty" density="compact" title={zh ? "还没有可用的已完成研究报告" : "No completed research reports"} /> : <div className={styles.reports}>
          {reports.map((report) => {
            const checked = selectedReports.has(reportKey(report));
            return <label key={reportKey(report)} className={styles.report}>
              <VCheckbox aria-label={`${zh ? "选择报告" : "Select report"} ${report.title} ${report.turnId}`} isSelected={checked} isDisabled={frozenCreateForm || (!checked && selectedReports.size >= 5)} onChange={(value) => selectReport(report, value)} />
              <span className={styles.reportText}><strong>{report.title}</strong><small>{report.sessionTitle} · Turn {report.turnId} · {formatTime(report.completedAt, zh)}</small><small>{report.preview}</small></span>
            </label>;
          })}
          {reportCatalog.hasNextPage ? <VButton variant="ghost" isDisabled={Boolean(pending)} isPending={reportCatalog.isFetchingNextPage} onPress={() => void reportCatalog.fetchNextPage()}>{zh ? "加载更早报告" : "Load earlier reports"}</VButton> : null}
        </div>}

        <div className={styles.fields}>
          <label className={styles.field}>{zh ? "候选股票代码" : "Candidate symbols"}<VInput aria-label={zh ? "候选股票代码" : "Candidate symbols"} value={symbolsText} disabled={frozenCreateForm} placeholder="600000, 000001" onChange={(event) => setSymbolsText(event.target.value)} /></label>
          <label className={styles.field}>{zh ? "组合目标" : "Portfolio objective"}<VTextarea aria-label={zh ? "组合目标" : "Portfolio objective"} className={styles.textarea} maxLength={2_000} value={instruction} disabled={frozenCreateForm} onChange={(event) => setInstruction(event.target.value)} placeholder={zh ? "例如：降低单股集中度，优先保留有研究依据的仓位，并至少保留10%现金。" : "For example: reduce single-stock concentration, favor research-backed holdings, and keep at least 10% cash."} /></label>
          <label className={styles.field}>{zh ? "单股仓位上限 %" : "Max position %"}<VInput type="number" min="1" max="100" step="0.1" value={String(policy.maxPositionPct)} disabled={frozenCreateForm} onChange={(event) => setPolicy((current) => ({ ...current, maxPositionPct: Number(event.target.value) }))} /></label>
          <label className={styles.field}>{zh ? "最低现金比例 %" : "Minimum cash %"}<VInput type="number" min="0" max="100" step="0.1" value={String(policy.minCashPct)} disabled={frozenCreateForm} onChange={(event) => setPolicy((current) => ({ ...current, minCashPct: Number(event.target.value) }))} /></label>
          <label className={styles.field}>{zh ? "换手上限 %" : "Max turnover %"}<VInput type="number" min="0" max="200" step="0.1" value={String(policy.maxTurnoverPct)} disabled={frozenCreateForm} onChange={(event) => setPolicy((current) => ({ ...current, maxTurnoverPct: Number(event.target.value) }))} /></label>
          <label className={styles.field}>{zh ? "报价最大时效（小时）" : "Max quote age (hours)"}<VInput type="number" min="1" max="168" step="1" value={String(policy.maxQuoteAgeHours)} disabled={frozenCreateForm} onChange={(event) => setPolicy((current) => ({ ...current, maxQuoteAgeHours: Number(event.target.value) }))} /></label>
        </div>
        <p className={styles.note}>{zh ? `已选 ${selectedReportRows.length}/5 份报告；候选 ${symbols.length}/10 只。已有持仓会由服务端自动并入，并限制长仓、整手和T+1卖出。` : `${selectedReportRows.length}/5 reports selected; ${symbols.length}/10 candidates. Existing holdings are included server-side; long-only, board lots, and T+1 sells apply.`}</p>
        <div className={styles.controls}>
          <VButton variant="primary" isPending={pending === "create"} isDisabled={!canCreate} onPress={() => void submitCreate(buildCreateRequest())}>{zh ? "生成组合建议" : "Generate proposal"}</VButton>
          {createAttempt ? <>
            <VButton variant="secondary" isPending={pending === "readback"} isDisabled={Boolean(pending)} onPress={() => void readUnknownCreate()}>{zh ? `查询请求 ${createAttempt.request.clientRequestId.slice(0, 8)}` : `Check request ${createAttempt.request.clientRequestId.slice(0, 8)}`}</VButton>
            {createAttempt.retryAllowed ? <VButton variant="secondary" isPending={pending === "create"} isDisabled={Boolean(pending)} onPress={() => void submitCreate(createAttempt.request, true)}>{zh ? "用同一请求重试" : "Retry same request"}</VButton> : null}
          </> : null}
        </div>
      </VSurface>

      <VSurface tone="panel" padding="normal" className={styles.panel}>
        <div className={styles.heading}><h4 className={styles.panelTitle}>{zh ? "历史建议" : "Proposal history"}</h4><VButton variant="ghost" isDisabled={proposalList.isFetching} onPress={() => void proposalList.refetch()}>{zh ? "刷新" : "Refresh"}</VButton></div>
        {proposalList.isPending ? <VStateSurface tone="loading" density="compact" busy title={zh ? "读取建议历史" : "Loading proposals"} /> : proposalList.isError ? <VStateSurface tone="error" density="compact" title={errorText(proposalList.error)} actions={<VButton onPress={() => void proposalList.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : !proposalList.data?.items.length ? <VStateSurface tone="empty" density="compact" title={zh ? "尚无组合建议" : "No proposals yet"} /> : <div className={styles.reports}>
          {proposalList.data.items.map((item) => <VButton key={item.proposalId} variant={item.proposalId === selectedProposalId ? "secondary" : "ghost"} className={styles.historyButton} onPress={() => selectProposal(item.proposalId)}>
            <span className={styles.historyButtonText}><strong>{statusLabels[item.status][zh ? "zh" : "en"]} · {formatTime(item.createdAt, zh)}</strong><small className={styles.muted}>{item.proposalId}</small></span>
          </VButton>)}
        </div>}
      </VSurface>
    </div>

    {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
    {selectedProposalId && proposalDetail.isPending ? <VStateSurface tone="loading" density="compact" busy title={zh ? "读取建议详情" : "Loading proposal details"} /> : null}
    {selectedProposalId && proposalDetail.isError ? <VStateSurface tone="error" density="compact" title={errorText(proposalDetail.error)} actions={<VButton onPress={() => void proposalDetail.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : null}

    {proposal ? <VSurface tone="panel" padding="normal" className={styles.panel}>
      <div className={styles.heading}>
        <div><h4 className={styles.panelTitle}>{zh ? "方案详情" : "Proposal details"} <span className={styles.status}>{statusLabels[proposal.status][zh ? "zh" : "en"]}</span></h4><p className={styles.note}>{proposal.proposalId} · {proposal.modelId} · {zh ? "创建" : "Created"} {formatTime(proposal.createdAt, zh)}{proposal.expiresAt ? ` · ${zh ? "计划有效至" : "Plan expires"} ${formatTime(proposal.expiresAt, zh)}` : ""}</p></div>
        {proposal.status === "ready" || proposal.status === "blocked" ? <VButton variant="secondary" isPending={pending === "preview"} isDisabled={!canPreview} onPress={() => void previewEditedPlan()}>{zh ? "重新检查计划" : "Recheck plan"}</VButton> : null}
      </div>
      {proposal.error ? <VStateSurface tone="error" density="compact" title={proposal.error} /> : null}
      {proposal.summaryReason ? <p className={styles.note}>{proposal.summaryReason}</p> : null}
      <p className={styles.note}>{zh ? "依据报告" : "Source reports"}：{proposal.reportRefs.map((ref) => `${ref.sessionId} / ${ref.turnId}`).join("；") || "—"}</p>

      <div className={styles.fields}>
        <label className={styles.field}>{zh ? "单股仓位上限 %" : "Max position %"}<VInput type="number" min="1" max="100" step="0.1" value={String(editedPolicy.maxPositionPct)} disabled={proposal.status === "executed" || proposal.status === "failed" || proposal.status === "generating" || Boolean(pending)} onChange={(event) => editPlanPolicy("maxPositionPct", Number(event.target.value))} /></label>
        <label className={styles.field}>{zh ? "最低现金比例 %" : "Minimum cash %"}<VInput type="number" min="0" max="100" step="0.1" value={String(editedPolicy.minCashPct)} disabled={proposal.status === "executed" || proposal.status === "failed" || proposal.status === "generating" || Boolean(pending)} onChange={(event) => editPlanPolicy("minCashPct", Number(event.target.value))} /></label>
        <label className={styles.field}>{zh ? "换手上限 %" : "Max turnover %"}<VInput type="number" min="0" max="200" step="0.1" value={String(editedPolicy.maxTurnoverPct)} disabled={proposal.status === "executed" || proposal.status === "failed" || proposal.status === "generating" || Boolean(pending)} onChange={(event) => editPlanPolicy("maxTurnoverPct", Number(event.target.value))} /></label>
        <label className={styles.field}>{zh ? "报价最大时效（小时）" : "Max quote age (hours)"}<VInput type="number" min="1" max="168" step="1" value={String(editedPolicy.maxQuoteAgeHours)} disabled={proposal.status === "executed" || proposal.status === "failed" || proposal.status === "generating" || Boolean(pending)} onChange={(event) => editPlanPolicy("maxQuoteAgeHours", Number(event.target.value))} /></label>
      </div>
      <div className={styles.table}><VDenseTable ariaLabel={zh ? "可编辑组合目标仓位" : "Editable portfolio targets"} rows={editedTargets} getRowKey={(row) => row.symbol} emptyText={zh ? "尚无目标仓位" : "No target weights"} columns={targetColumns} /></div>
      {proposal.riskChecks.length ? <ul className={styles.risk} aria-label={zh ? "确定性风险检查" : "Deterministic risk checks"}>{proposal.riskChecks.map((check) => <li key={check.code} className={check.passed ? styles.passed : styles.failed}><strong>{check.passed ? "✓" : "!"} {check.label}：</strong>{check.detail}</li>)}</ul> : null}
      <div className={styles.controls}><span className={styles.note}>{zh ? "净值" : "Equity"} {money(proposal.metrics.equityYuan, zh)} · {zh ? "预计现金" : "Cash after"} {money(proposal.metrics.cashAfterYuan, zh)} · {zh ? "换手" : "Turnover"} {proposal.metrics.turnoverPct}% · {zh ? "费用" : "Fees"} {money(proposal.metrics.feesYuan, zh)}</span>
        {planDirty ? <span className={styles.error}>{zh ? "目标或风控参数已修改，或服务端校验未通过；重新检查并取得新 planHash 前不能批准。" : "Targets or risk policy changed, or server validation failed. Recheck for a new planHash before approval."}</span> : null}
        {isExpired ? <span className={styles.error}>{zh ? "方案已过期，请重新检查行情与风控。" : "Plan expired; recheck quotes and risk."}</span> : null}
        {proposal.status === "ready" && !allRiskChecksPassed ? <span className={styles.error}>{zh ? "风险检查不完整，暂不能批准。" : "Risk checks are incomplete; approval is disabled."}</span> : null}
        {proposal.status === "blocked" ? <span className={styles.error}>{zh ? "至少一项风控未通过，不能批准。" : "At least one risk check failed; approval is disabled."}</span> : null}
        <VButton variant="primary" isDisabled={!canApprove} onPress={() => setApprovalOpen(true)}>{zh ? "核对并批准模拟调仓" : "Review and approve paper rebalance"}</VButton>
      </div>
      <div className={styles.table}><VDenseTable ariaLabel={zh ? "精确模拟调仓订单" : "Exact paper rebalance orders"} rows={proposal.orders} getRowKey={(row) => `${row.side}:${row.symbol}`} emptyText={zh ? "没有可执行订单" : "No executable orders"} columns={orderColumns} /></div>
      {proposal.execution ? <p className={styles.note}>{zh ? "模拟批次" : "Paper batch"} {proposal.execution.batchId} · {formatTime(proposal.execution.executedAt, zh)}</p> : null}
    </VSurface> : null}

    <VDialog open={approvalOpen} onOpenChange={setApprovalOpen} title={zh ? "批准精确模拟订单" : "Approve exact paper orders"} description={zh ? "确认后只写入当前模拟账户，不会发送真实券商订单。批准绑定当前 planHash。" : "Confirmation writes only to this paper account. No broker order is sent. Approval is bound to the current planHash."} footer={<>
      <VButton variant="secondary" isDisabled={Boolean(pending)} onPress={() => setApprovalOpen(false)}>{zh ? "返回检查" : "Back"}</VButton>
      <VButton variant="primary" isPending={pending === "approve"} isDisabled={!canApprove} onPress={() => void approvePlan()}>{zh ? "确认模拟调仓" : "Confirm paper rebalance"}</VButton>
    </>}>
      {proposal ? <div className={styles.dialogOrders}>
        {proposal.orders.map((order) => <div key={`${order.side}:${order.symbol}`} className={styles.dialogOrder}><strong>{order.side === "buy" ? (zh ? "买入" : "Buy") : (zh ? "卖出" : "Sell")} {order.name} · {order.symbol}</strong><span>{order.quantity.toLocaleString()} {zh ? "股" : "shares"}</span><small>{money(order.priceYuan, zh)} × {order.quantity.toLocaleString()} · {zh ? "费用" : "fee"} {money(order.feeYuan, zh)}</small><small>{order.reason || "—"}</small></div>)}
      </div> : null}
    </VDialog>
  </section>;
}
