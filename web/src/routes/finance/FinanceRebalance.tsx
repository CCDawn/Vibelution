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
import { fetchFinancialReportDocument, fetchFinancialReports, financialReportKeys, type FinancialReportSummary } from "../../api/financialReports";
import type {
  FinancialPortfolioPosition,
  FinancialPortfolioProposal,
  FinancialPortfolioProposalCreateRequest,
  FinancialPortfolioRebalancePolicy,
  FinancialPortfolioRebalanceTarget,
} from "../../api/types/financialPortfolio";
import { VButton, VCheckbox, VDenseTable, VDialog, VInput, VStateSurface, VSurface, VTextarea, type VDenseTableColumn } from "../../components/vui";
import { FinanceReportExport } from "./FinanceReportExport";
import { normalizeFinancialBatchAShareSymbol } from "./financialJobModel";
import type { FinanceProposalBatchImport } from "./financeProposalImportModel";
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

export function FinanceRebalance({ agentId, positions, zh, batchImport, onBatchImportHandled }: {
  agentId: string; positions: FinancialPortfolioPosition[]; zh: boolean;
  batchImport?: FinanceProposalBatchImport | null;
  onBatchImportHandled?: (importId: string) => void;
}) {
  const queryClient = useQueryClient();
  const [symbolsText, setSymbolsText] = useState(() => positions.map((position) => position.symbol).join(", "));
  const [instruction, setInstruction] = useState("");
  const [policy, setPolicy] = useState<FinancialPortfolioRebalancePolicy>(() => ({ ...DEFAULT_POLICY }));
  const [selectedReports, setSelectedReports] = useState<Map<string, FinancialReportSummary>>(() => new Map());
  const [importedBatchReports, setImportedBatchReports] = useState<FinancialReportSummary[]>([]);
  const [importedBatchSource, setImportedBatchSource] = useState<{ batchId: string; researchDate: string } | null>(null);
  const [selectedProposalId, setSelectedProposalId] = useState("");
  const [editedTargets, setEditedTargets] = useState<FinancialPortfolioRebalanceTarget[]>([]);
  const [editedPolicy, setEditedPolicy] = useState<FinancialPortfolioRebalancePolicy>(() => ({ ...DEFAULT_POLICY }));
  const [planDirty, setPlanDirty] = useState(false);
  const [createAttempt, setCreateAttempt] = useState<CreateAttempt | null>(null);
  const [approvalOpen, setApprovalOpen] = useState(false);
  const [expandedReportPreviews, setExpandedReportPreviews] = useState<Set<string>>(() => new Set());
  const [summaryExpanded, setSummaryExpanded] = useState(false);
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
    setImportedBatchReports([]);
    setImportedBatchSource(null);
    setSelectedProposalId("");
    setEditedTargets([]);
    setEditedPolicy({ ...DEFAULT_POLICY });
    setPlanDirty(false);
    setCreateAttempt(null);
    setApprovalOpen(false);
    setExpandedReportPreviews(new Set());
    setSummaryExpanded(false);
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
  const batchImportQuery = useQuery({
    queryKey: ["finance", "portfolio-proposal-batch-import", agentId, batchImport?.importId ?? ""],
    enabled: Boolean(batchImport),
    queryFn: async ({ signal }) => {
      if (!batchImport) return [];
      if (batchImport.assistantAgentId !== agentId) throw new Error("研究批次所属助手已切换，请重新选择批次");
      if (!batchImport.reports.length || batchImport.reports.length > 5) throw new Error("批次报告数量无效，请重新选择1至5份报告");
      const batchSymbols = batchImport.reports.map((reference) => normalizeFinancialBatchAShareSymbol(reference.symbol));
      if (batchSymbols.some((symbol) => !symbol)) throw new Error("组合建议仅支持沪、深、北交所 A 股；请重新选择批次报告");
      const documents = await Promise.all(batchImport.reports.map((reference) => fetchFinancialReportDocument({ assistantAgentId: agentId, sessionId: reference.sessionId, turnId: reference.turnId }, { signal })));
      return documents.map((document, index): FinancialReportSummary => {
        const reference = batchImport.reports[index];
        const symbol = batchSymbols[index];
        if (document.assistantAgentId !== agentId || document.sessionId !== reference.sessionId || document.turnId !== reference.turnId) {
          throw new Error("研究报告身份与批次引用不一致");
        }
        if (!symbol) throw new Error("批次报告股票代码无效");
        const preview = document.content.replace(/https?:\/\/\S+/g, " ").replace(/[#*_`>|]/g, " ").replace(/\s+/g, " ").trim().slice(0, 240);
        return {
          sessionId: document.sessionId, turnId: document.turnId,
          title: `${symbol} · ${zh ? "批次汇总报告" : "Batch synthesis report"}`,
          sessionTitle: `${batchImport.batchId} · ${batchImport.researchDate}`,
          ticker: null, marketCode: null, completedAt: document.completedAt,
          preview, chars: document.content.length, kind: "research",
        };
      });
    },
    retry: false,
  });
  const displayReports = useMemo(() => {
    const items = new Map(importedBatchReports.map((report) => [reportKey(report), report]));
    for (const report of reports) items.set(reportKey(report), report);
    return [...items.values()];
  }, [importedBatchReports, reports]);
  const reportsByRef = useMemo(() => new Map(displayReports.map((report) => [reportKey(report), report])), [displayReports]);
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
  const batchImportPending = Boolean(batchImport && batchImportQuery.isPending);
  const batchImportFailed = Boolean(batchImport && batchImportQuery.isError);
  const frozenCreateForm = Boolean(createAttempt) || pending === "create" || pending === "readback";

  useEffect(() => {
    if (!batchImport || !batchImportQuery.data) return;
    const batchSymbols = [...new Set(batchImport.reports.map((reference) => normalizeFinancialBatchAShareSymbol(reference.symbol)).filter((symbol): symbol is string => Boolean(symbol)))];
    setSymbolsText(batchSymbols.join(", "));
    setImportedBatchReports(batchImportQuery.data);
    setImportedBatchSource({ batchId: batchImport.batchId, researchDate: batchImport.researchDate });
    setSelectedReports(new Map(batchImportQuery.data.map((report) => [reportKey(report), report])));
    setSelectedProposalId("");
    setEditedTargets([]);
    setPlanDirty(false);
    setCreateAttempt(null);
    setError("");
    onBatchImportHandled?.(batchImport.importId);
  }, [batchImport?.importId, batchImport?.batchId, batchImport?.researchDate, batchImportQuery.data, onBatchImportHandled]);

  useEffect(() => {
    if (batchImport && batchImportQuery.isError) setError(errorText(batchImportQuery.error));
  }, [batchImport?.importId, batchImportQuery.error, batchImportQuery.isError]);

  useEffect(() => {
    if (!proposal) return;
    setEditedTargets(proposal.targets.map((target) => ({ ...target })));
    setEditedPolicy({ ...proposal.policy });
    setPlanDirty(false);
    setSummaryExpanded(false);
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

  function clearImportedBatchReports() {
    const importedKeys = new Set(importedBatchReports.map(reportKey));
    setSelectedReports((current) => new Map([...current].filter(([key]) => !importedKeys.has(key))));
    setImportedBatchReports([]);
    setImportedBatchSource(null);
  }

  function dismissBatchImport() {
    if (batchImport) onBatchImportHandled?.(batchImport.importId);
    setError("");
  }

  function toggleReportPreview(key: string) {
    setExpandedReportPreviews((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
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
    setSelectedProposalId("");
    const requestPromise = createFinancialPortfolioProposal(agentId, request);
    void queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.proposals(agentId) });
    const outcome = await runAction("create", () => requestPromise);
    if (!outcome.ok) {
      if (outcome.stale) return;
      setCreateAttempt({ request, retryAllowed: false });
      if (retry) setError(zh ? "结果暂未确认，请先查询结果，再决定是否重试。" : "The result is still unknown. Check it before retrying.");
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
      void queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.proposals(agentId) });
      return;
    }
    if (isFinancialPortfolioProposalNotFound(outcome.error)) {
      setCreateAttempt({ request, retryAllowed: true });
      setError(zh ? "暂未找到结果，可以重试生成。" : "No result was found. You can retry generation.");
    }
  }

  function invalidateApprovalQueries(targetAgentId: string, proposalId?: string) {
    const invalidations = [
      queryClient.invalidateQueries({ queryKey: financialPaperKeys.account(targetAgentId) }),
      queryClient.invalidateQueries({ queryKey: ["financial-paper", targetAgentId, "review"] }),
      queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.research(targetAgentId) }),
      queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.proposals(targetAgentId) }),
    ];
    if (proposalId) invalidations.push(queryClient.invalidateQueries({ queryKey: financialPortfolioKeys.proposal(targetAgentId, proposalId) }));
    void Promise.all(invalidations);
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
      if (outcome.stale) {
        invalidateApprovalQueries(agentId, proposal.proposalId);
        return;
      }
      setPlanDirty(true);
      try {
        const readback = await fetchFinancialPortfolioProposal(agentId, proposal.proposalId);
        if (agentRef.current !== agentId || agentEpoch.current !== requestedEpoch) {
          if (readback.status === "executed") invalidateApprovalQueries(agentId, proposal.proposalId);
          return;
        }
        queryClient.setQueryData(financialPortfolioKeys.proposal(agentId, proposal.proposalId), readback);
        if (readback.status === "executed") {
          setPlanDirty(false);
          setApprovalOpen(false);
          invalidateApprovalQueries(agentId);
        }
      } catch {
        // Keep approval disabled until the user can recheck or reload this exact proposal.
      }
      return;
    }
    setApprovalOpen(false);
    queryClient.setQueryData(financialPortfolioKeys.proposal(agentId, proposal.proposalId), outcome.value);
    invalidateApprovalQueries(agentId);
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

  const canCreate = !pending && !createAttempt && !batchImportPending && !batchImportFailed && symbols.length > 0 && symbols.length <= 10
    && selectedReportRows.length > 0 && instruction.trim().length > 0 && instruction.length <= 2_000 && validPolicy(policy);
  const parsedExpiry = proposal?.expiresAt ? Date.parse(proposal.expiresAt) : Number.NaN;
  const isExpired = !Number.isFinite(parsedExpiry) || parsedExpiry <= Date.now();
  const canPreview = !pending && (planDirty || isExpired) && validTargets(editedTargets) && validPolicy(editedPolicy);
  const allRiskChecksPassed = Boolean(proposal?.riskChecks.length && proposal.riskChecks.every((check) => check.passed));
  const canRecheck = proposal?.status === "ready" || proposal?.status === "blocked";
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
        <p className={styles.note}>{zh ? "选报告、生成建议，确认后只在模拟账户成交。" : "Select reports, generate a proposal, then confirm simulated trades."}</p>
      </div>
      <VButton variant="secondary" isDisabled={Boolean(pending) || Boolean(createAttempt)} onPress={startNewProposal}>{zh ? "新建建议" : "New proposal"}</VButton>
    </header>

    <div className={styles.layout}>
      <VSurface tone="panel" padding="normal" className={styles.panel}>
        <div className={styles.heading}>
          <div>
            <h4 className={styles.panelTitle}>{zh ? "研究报告与风控" : "Reports and risk"}</h4>
            <p className={styles.note}>{zh ? "最多选5份已完成报告。" : "Select up to five completed reports."}</p>
          </div>
          <div className={styles.headerActions}>
            {importedBatchSource ? <><span className={styles.note} title={importedBatchSource.batchId}>{zh ? `研究批次 · ${importedBatchSource.researchDate}` : `Research batch · ${importedBatchSource.researchDate}`}</span><VButton variant="ghost" isDisabled={frozenCreateForm} onPress={clearImportedBatchReports}>{zh ? "清除批次来源" : "Clear batch source"}</VButton></> : null}
            <VButton variant="ghost" isPending={reportCatalog.isFetching} onPress={() => void reportCatalog.refetch()}>{zh ? "刷新报告" : "Refresh reports"}</VButton>
          </div>
        </div>
        {batchImportPending ? <VStateSurface tone="loading" density="compact" busy title={zh ? "正在核验批次报告" : "Validating batch reports"}>{zh ? "正在读取每个精确的研究回合；核验完成前不能生成建议。" : "Reading each exact research Turn. Proposal generation stays disabled until validation completes."}</VStateSurface> : null}
        {batchImportFailed ? <VStateSurface tone="error" density="compact" title={errorText(batchImportQuery.error)} actions={<div className={styles.headerActions}><VButton isPending={batchImportQuery.isFetching} onPress={() => void batchImportQuery.refetch()}>{zh ? "重试核验" : "Retry validation"}</VButton><VButton variant="secondary" onPress={dismissBatchImport}>{zh ? "取消导入" : "Cancel import"}</VButton></div>} /> : null}
        {reportCatalog.isError ? <VStateSurface tone="error" density="compact" title={errorText(reportCatalog.error)} actions={<VButton onPress={() => void reportCatalog.refetch()}>{zh ? "重试目录" : "Retry catalog"}</VButton>} /> : null}
        {reportCatalog.isPending && !displayReports.length ? <VStateSurface tone="loading" density="compact" busy title={zh ? "读取研究报告" : "Loading reports"} /> : !displayReports.length ? <VStateSurface tone="empty" density="compact" title={zh ? "暂无已完成研究报告" : "No completed research reports"} /> : <div className={styles.reports}>
          {displayReports.map((report) => {
            const key = reportKey(report);
            const checked = selectedReports.has(key);
            const previewExpanded = expandedReportPreviews.has(key);
            return <div key={key} className={styles.report}>
              <VCheckbox aria-label={`${zh ? "选择报告" : "Select report"} ${report.title}`} isSelected={checked} isDisabled={frozenCreateForm || (!checked && selectedReports.size >= 5)} onChange={(value) => selectReport(report, value)} />
              <div className={styles.reportText}>
                <strong className={styles.reportTitle} title={report.title}>{report.title}</strong>
                <small className={styles.reportMeta}>{zh ? "完成于 " : "Completed "}{formatTime(report.completedAt, zh)}</small>
                {report.preview ? <div className={styles.reportPreviewRow}>
                  <small className={`${styles.reportPreview} ${previewExpanded ? "" : styles.reportPreviewCollapsed}`} data-report-preview={key}>{report.preview}</small>
                  <VButton density="compact" variant="ghost" className={styles.textToggle} aria-label={`${zh ? (previewExpanded ? "收起报告摘要" : "展开报告摘要") : (previewExpanded ? "Collapse report summary" : "Expand report summary")} ${report.title}`} onPress={() => toggleReportPreview(key)}>{zh ? (previewExpanded ? "收起" : "展开") : (previewExpanded ? "Show less" : "Show more")}</VButton>
                </div> : null}
              </div>
            </div>;
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
        <p className={styles.note}>{zh ? `已选 ${selectedReportRows.length}/5 份报告；候选 ${symbols.length}/10 只。现有持仓计入建议；仅做多、按整手交易并遵守T+1卖出规则。` : `${selectedReportRows.length}/5 reports selected; ${symbols.length}/10 candidates. Existing holdings are included; long-only, board lots, and T+1 sells apply.`}</p>
        <div className={styles.controls}>
          <VButton variant="primary" isPending={pending === "create"} isDisabled={!canCreate} onPress={() => void submitCreate(buildCreateRequest())}>{zh ? "生成建议" : "Generate proposal"}</VButton>
          {createAttempt ? <>
            <VButton variant="secondary" isPending={pending === "readback"} isDisabled={Boolean(pending)} onPress={() => void readUnknownCreate()}>{zh ? "查询结果" : "Check result"}</VButton>
            {createAttempt.retryAllowed ? <VButton variant="secondary" isPending={pending === "create"} isDisabled={Boolean(pending)} onPress={() => void submitCreate(createAttempt.request, true)}>{zh ? "重试生成" : "Retry generation"}</VButton> : null}
          </> : null}
        </div>
      </VSurface>

      <VSurface tone="panel" padding="normal" className={styles.panel}>
        <div className={styles.heading}><h4 className={styles.panelTitle}>{zh ? "历史建议" : "Proposal history"}</h4><VButton variant="ghost" isDisabled={proposalList.isFetching} onPress={() => void proposalList.refetch()}>{zh ? "刷新" : "Refresh"}</VButton></div>
        {proposalList.isPending ? <VStateSurface tone="loading" density="compact" busy title={zh ? "读取建议历史" : "Loading proposals"} /> : proposalList.isError ? <VStateSurface tone="error" density="compact" title={errorText(proposalList.error)} actions={<VButton onPress={() => void proposalList.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : !proposalList.data?.items.length ? <VStateSurface tone="empty" density="compact" title={zh ? "尚无组合建议" : "No proposals yet"} /> : <div className={styles.reports}>
          {proposalList.data.items.map((item) => <VButton key={item.proposalId} variant={item.proposalId === selectedProposalId ? "secondary" : "ghost"} className={styles.historyButton} onPress={() => selectProposal(item.proposalId)}>
            <span className={styles.historyButtonText}><strong>{statusLabels[item.status][zh ? "zh" : "en"]} · {formatTime(item.createdAt, zh)}</strong></span>
          </VButton>)}
        </div>}
      </VSurface>
    </div>

    {error ? <VStateSurface tone="error" density="compact" title={error} /> : null}
    {selectedProposalId && proposalDetail.isPending ? <VStateSurface tone="loading" density="compact" busy title={zh ? "读取建议详情" : "Loading proposal details"} /> : null}
    {selectedProposalId && proposalDetail.isError ? <VStateSurface tone="error" density="compact" title={errorText(proposalDetail.error)} actions={<VButton onPress={() => void proposalDetail.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : null}

    {proposal ? <VSurface tone="panel" padding="normal" className={styles.panel}>
      <div className={styles.heading}>
        <div><h4 className={styles.panelTitle}>{zh ? "建议详情" : "Proposal details"} <span className={styles.status}>{statusLabels[proposal.status][zh ? "zh" : "en"]}</span></h4><p className={styles.note}>{zh ? "创建" : "Created"} {formatTime(proposal.createdAt, zh)}{proposal.expiresAt ? ` · ${zh ? "有效至" : "Expires"} ${formatTime(proposal.expiresAt, zh)}` : ""}</p></div>
        {proposal.status === "ready" || proposal.status === "blocked" ? <VButton variant="secondary" isPending={pending === "preview"} isDisabled={!canPreview} onPress={() => void previewEditedPlan()}>{zh ? "重新检查计划" : "Recheck plan"}</VButton> : null}
      </div>
      {proposal.error ? <VStateSurface tone="error" density="compact" title={proposal.error} /> : null}
      {proposal.summaryReason ? <div className={styles.summarySection}>
        <p className={`${styles.summaryReason} ${summaryExpanded ? "" : styles.summaryReasonCollapsed}`} data-model-summary>{proposal.summaryReason}</p>
        {proposal.summaryReason.length > 180 ? <VButton density="compact" variant="ghost" className={styles.textToggle} aria-label={zh ? (summaryExpanded ? "收起模型摘要" : "展开模型摘要") : (summaryExpanded ? "Collapse model summary" : "Expand model summary")} onPress={() => setSummaryExpanded((current) => !current)}>{zh ? (summaryExpanded ? "收起" : "展开") : (summaryExpanded ? "Show less" : "Show more")}</VButton> : null}
      </div> : null}
      {proposal.reportRefs.length ? <div className={styles.reports} aria-label={zh ? "参考报告" : "Source reports"}>
        {proposal.reportRefs.map((ref) => {
          const source = reportsByRef.get(reportKey(ref));
          const sourceLabel = source
            ? `${source.title} · ${formatTime(source.completedAt, zh)}`
            : (zh ? "原始研究报告" : "Original research report");
          return <div key={reportKey(ref)} className={styles.sourceRow}>
            <span className={styles.sourceLabel} title={`${sourceLabel}\nSession ${ref.sessionId}\nTurn ${ref.turnId}`}>{sourceLabel}</span>
            <FinanceReportExport assistantAgentId={agentId} sessionId={ref.sessionId} turnId={ref.turnId} zh={zh} />
          </div>;
        })}
      </div> : <p className={styles.note}>{zh ? "没有参考报告" : "No source reports"}</p>}
      <p className={styles.modelLabel} title={proposal.modelId}>{zh ? "模型" : "Model"} {proposal.modelId}</p>

      <div className={styles.fields}>
        <label className={styles.field}>{zh ? "单股仓位上限 %" : "Max position %"}<VInput type="number" min="1" max="100" step="0.1" value={String(editedPolicy.maxPositionPct)} disabled={proposal.status === "executed" || proposal.status === "failed" || proposal.status === "generating" || Boolean(pending)} onChange={(event) => editPlanPolicy("maxPositionPct", Number(event.target.value))} /></label>
        <label className={styles.field}>{zh ? "最低现金比例 %" : "Minimum cash %"}<VInput type="number" min="0" max="100" step="0.1" value={String(editedPolicy.minCashPct)} disabled={proposal.status === "executed" || proposal.status === "failed" || proposal.status === "generating" || Boolean(pending)} onChange={(event) => editPlanPolicy("minCashPct", Number(event.target.value))} /></label>
        <label className={styles.field}>{zh ? "换手上限 %" : "Max turnover %"}<VInput type="number" min="0" max="200" step="0.1" value={String(editedPolicy.maxTurnoverPct)} disabled={proposal.status === "executed" || proposal.status === "failed" || proposal.status === "generating" || Boolean(pending)} onChange={(event) => editPlanPolicy("maxTurnoverPct", Number(event.target.value))} /></label>
        <label className={styles.field}>{zh ? "报价最大时效（小时）" : "Max quote age (hours)"}<VInput type="number" min="1" max="168" step="1" value={String(editedPolicy.maxQuoteAgeHours)} disabled={proposal.status === "executed" || proposal.status === "failed" || proposal.status === "generating" || Boolean(pending)} onChange={(event) => editPlanPolicy("maxQuoteAgeHours", Number(event.target.value))} /></label>
      </div>
      <div className={styles.table}><VDenseTable ariaLabel={zh ? "可编辑组合目标仓位" : "Editable portfolio targets"} rows={editedTargets} getRowKey={(row) => row.symbol} emptyText={zh ? "尚无目标仓位" : "No target weights"} columns={targetColumns} /></div>
      {proposal.riskChecks.length ? <ul className={styles.risk} aria-label={zh ? "确定性风险检查" : "Deterministic risk checks"}>{proposal.riskChecks.map((check) => <li key={check.code} className={check.passed ? styles.passed : styles.failed}><strong>{check.passed ? "✓" : "!"} {check.label}：</strong>{check.detail}</li>)}</ul> : null}
      <div className={styles.controls}><span className={styles.note}>{zh ? "净值" : "Equity"} {money(proposal.metrics.equityYuan, zh)} · {zh ? "预计现金" : "Cash after"} {money(proposal.metrics.cashAfterYuan, zh)} · {zh ? "换手" : "Turnover"} {proposal.metrics.turnoverPct}% · {zh ? "费用" : "Fees"} {money(proposal.metrics.feesYuan, zh)}</span>
        {planDirty ? <span className={styles.error}>{zh ? "目标或风控已修改，请重新检查后确认。" : "Targets or risk settings changed. Recheck before confirming."}</span> : null}
        {isExpired && canRecheck ? <span className={styles.error}>{zh ? "建议已过期，请重新检查行情与风控。" : "Proposal expired; recheck quotes and risk."}</span> : null}
        {proposal.status === "ready" && !allRiskChecksPassed ? <span className={styles.error}>{zh ? "风控检查未完成，暂不能确认。" : "Risk checks are incomplete; confirmation is disabled."}</span> : null}
        {proposal.status === "blocked" ? <span className={styles.error}>{zh ? "风控未通过，不能确认。" : "Risk checks failed; confirmation is disabled."}</span> : null}
        {proposal.status !== "executed" ? <VButton variant="primary" isDisabled={!canApprove} onPress={() => setApprovalOpen(true)}>{zh ? "核对订单" : "Review orders"}</VButton> : null}
      </div>
      <div className={styles.table}><VDenseTable ariaLabel={zh ? "模拟订单" : "Simulated orders"} rows={proposal.orders} getRowKey={(row) => `${row.side}:${row.symbol}`} emptyText={zh ? "没有可执行订单" : "No executable orders"} columns={orderColumns} /></div>
      {proposal.execution ? <p className={styles.note}>{zh ? "模拟成交" : "Simulated trades"} · {formatTime(proposal.execution.executedAt, zh)}</p> : null}
    </VSurface> : null}

    <VDialog open={approvalOpen} onOpenChange={setApprovalOpen} title={zh ? "确认模拟成交" : "Confirm simulated trades"} description={zh ? "只在模拟账户成交，不会发送真实订单。" : "Trades are simulated only. No real orders are sent."} footer={<>
      <VButton variant="secondary" isDisabled={Boolean(pending)} onPress={() => setApprovalOpen(false)}>{zh ? "返回检查" : "Back"}</VButton>
      <VButton variant="primary" isPending={pending === "approve"} isDisabled={!canApprove} onPress={() => void approvePlan()}>{zh ? "确认模拟成交" : "Confirm simulated trades"}</VButton>
    </>}>
      {proposal ? <div className={styles.dialogOrders}>
        {proposal.orders.map((order) => <div key={`${order.side}:${order.symbol}`} className={styles.dialogOrder}><strong>{order.side === "buy" ? (zh ? "买入" : "Buy") : (zh ? "卖出" : "Sell")} {order.name} · {order.symbol}</strong><span>{order.quantity.toLocaleString()} {zh ? "股" : "shares"}</span><small>{money(order.priceYuan, zh)} × {order.quantity.toLocaleString()} · {zh ? "费用" : "fee"} {money(order.feeYuan, zh)}</small><small>{order.reason || "—"}</small></div>)}
      </div> : null}
    </VDialog>
  </section>;
}
