import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, History, Plus, Settings2 } from "lucide-react";
import { useLocation } from "react-router-dom";
import { createChatSession, querySessions } from "../../api/chat";
import type { FinancialAssistant } from "../../api/financialAssistant";
import { VButton, VDialog, VInput, VRouteLinkButton, VSkeleton, VStateSurface } from "../../components/vui";
import { ChatCodingRoute } from "../ChatCodingRoute";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import { useChatRouteSelection } from "../chat/useChatRouteSelection";
import styles from "../FinanceRoute.styles";
import { FinanceResearchFrame } from "./FinanceResearchFrame";
import { FinanceReportLibrary } from "./FinanceReportLibrary";
import { FinancialResearchBridgeContext, type FinancialDraftRequest, type FinancialSessionView } from "./FinancialResearchBridge";
import { financialResearchPrompt, isFinancialSession, type FinancialResearchKind } from "./financialResearchModel";

export function FinanceResearchWorkspace({ assistant, sessionId, zh }: {
  assistant: FinancialAssistant; sessionId: string; zh: boolean;
}) {
  const location = useLocation();
  const route = useChatRouteSelection();
  const routeRef = useRef(route);
  routeRef.current = route;
  const client = useQueryClient();
  const [company, setCompany] = useState("");
  const [period, setPeriod] = useState("");
  const [dialog, setDialog] = useState<"history" | "evidence" | null>(null);
  const dialogOpener = useRef<HTMLElement | null>(null);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const createGate = useRef(false);
  const createKey = useRef("");
  const mounted = useRef(false);
  const [view, setView] = useState<FinancialSessionView | null>(null);
  const [draftRequest, setDraftRequest] = useState<FinancialDraftRequest | null>(null);
  const requestSequence = useRef(0);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const history = useInfiniteQuery({
    queryKey: ["sessions", "finance", assistant.agentId],
    queryFn: ({ signal, pageParam }) => querySessions({ agentId: assistant.agentId, limit: 30, cursor: pageParam || undefined }, { signal }),
    initialPageParam: "",
    getNextPageParam: (page) => page.nextCursor || undefined,
    staleTime: 15_000, retry: false, refetchInterval: 30_000,
  });
  const records = (history.data?.pages.flatMap((page) => page.items) ?? []).filter((row) => isFinancialSession(row, assistant.agentId));
  const nativeReady = view?.sessionId === sessionId;
  const onSessionView = useCallback((next: FinancialSessionView) => {
    setView((current) => current && Object.keys(next).every((key) => current[key as keyof FinancialSessionView] === next[key as keyof FinancialSessionView]) ? current : next);
  }, []);
  const bridge = useMemo(() => ({ agentId: assistant.agentId, draftRequest, onSessionView }), [assistant.agentId, draftRequest, onSessionView]);
  const returnTo = `${location.pathname}${location.search}`;
  function openDialog(next: "history" | "evidence") {
    dialogOpener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setDialog(next);
  }

  async function newResearch() {
    if (createGate.current) return;
    createGate.current = true;
    createKey.current ||= crypto.randomUUID();
    const expected = routeRef.current.selection;
    setCreating(true); setCreateError("");
    try {
      const result = await createChatSession({ agentId: assistant.agentId, title: [company.trim() || (zh ? "新研究" : "New research"), period.trim()].filter(Boolean).join(" · ") }, createKey.current);
      if (!isFinancialSession(result, assistant.agentId)) throw new Error(zh ? "新会话身份不匹配" : "Session identity mismatch");
      // Async create may return only a summary. Never replace a transcript cache
      // here; the native detail/SSE handoff hydrates the conversation.
      void client.invalidateQueries({ queryKey: ["sessions", "finance", assistant.agentId] });
      createKey.current = "";
      if (mounted.current) {
        const navigated = routeRef.current.replaceIfStillViewing(expected, { kind: "session", sessionId: result.id });
        if (navigated) { setDraftRequest(null); setDialog(null); }
      }
    } catch (error) {
      if (mounted.current) setCreateError(error instanceof Error ? error.message : (zh ? "创建失败，请重试" : "Could not create research"));
    } finally {
      createGate.current = false;
      if (mounted.current) setCreating(false);
    }
  }
  function chooseResearch(kind: FinancialResearchKind) {
    const text = financialResearchPrompt(company, period, kind, zh);
    if (!text || !nativeReady) return;
    requestSequence.current += 1;
    setDraftRequest({ id: requestSequence.current, sessionId, text });
    dialogOpener.current = null;
    setDialog(null);
  }
  const rail = <div className={styles.rail}>
    <VButton variant="secondary" className={styles.newButton} icon={<Plus size={16} aria-hidden="true" />} isDisabled={creating} onPress={() => void newResearch()}>{creating ? (zh ? "创建中" : "Creating") : (zh ? "新研究" : "New research")}</VButton>
    {createError ? <VStateSurface density="compact" tone="error" title={zh ? "未创建研究" : "Could not create research"}>{createError}</VStateSurface> : null}
    <div className={styles.fields}>
      <label className={styles.field}>{zh ? "研究标的" : "Research target"}<VInput value={company} onChange={(event) => setCompany(event.target.value)} aria-label={zh ? "公司或股票代码" : "Company or ticker"} placeholder={zh ? "公司或股票代码" : "Company or ticker"} maxLength={120} className={styles.input} /></label>
      <label className={styles.field}>{zh ? "报告期" : "Report period"}<VInput value={period} onChange={(event) => setPeriod(event.target.value)} aria-label={zh ? "报告期" : "Report period"} placeholder="2025FY / 2026H1" maxLength={40} className={styles.input} /></label>
      <div className={styles.tasks}>{(["financial", "events", "risk"] as const).map((kind) => <VButton key={kind} variant="ghost" isDisabled={!company.trim() || !nativeReady} onPress={() => chooseResearch(kind)}>{zh ? { financial: "财报", events: "事件", risk: "风险" }[kind] : { financial: "Reports", events: "Events", risk: "Risks" }[kind]}</VButton>)}</div>
    </div>
    <div className={styles.sectionHeading}><span>{zh ? "研究记录" : "Research history"}</span><History size={14} aria-hidden="true" /></div>
    {history.isError ? <VStateSurface density="compact" tone="error" title={zh ? "记录加载失败" : "History unavailable"} actions={<VButton onPress={() => void history.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> :
      history.isPending ? <div className={styles.skeleton}><VSkeleton /><VSkeleton /></div> :
      <div className={styles.records}>
        {records.length === 0 ? <p className={styles.small}>{zh ? "暂无研究记录" : "No research history"}</p> : null}
        {records.map((record) => <VButton key={record.id} variant="ghost" contentLayout="plain" className={`${styles.record} ${record.id === sessionId ? styles.selected : ""}`} aria-pressed={record.id === sessionId} onPress={() => { route.openSession(record.id, { replace: false, telemetrySource: "finance_research_history" }); setDraftRequest(null); setDialog(null); }}>
          <span className={styles.rowText}><strong>{record.title || (zh ? "研究会话" : "Research session")}</strong><span className={`${styles.small} truncate`}>{record.status === "running" ? (zh ? "研究中" : "Running") : record.taskSummary || (zh ? "研究对话" : "Research chat")}</span></span>
        </VButton>)}
        {history.hasNextPage ? <VButton variant="ghost" isDisabled={history.isFetchingNextPage} onPress={() => void history.fetchNextPage()}>{zh ? "更多记录" : "More history"}</VButton> : null}
      </div>}
  </div>;
  const library = <FinanceReportLibrary assistant={assistant} zh={zh} returnTo={returnTo} />;
  return (
    <FinancialResearchBridgeContext.Provider value={bridge}>
      <FinanceResearchFrame zh={zh} sidebar={rail} aside={library} onHistory={() => openDialog("history")} onEvidence={() => openDialog("evidence")} actions={
        <VRouteLinkButton to={agentCenterConfigRoute({ agentId: assistant.agentId, returnTo, returnLabel: zh ? "炒股智能体" : "Investment assistant" })} aria-label={zh ? "模型与助手配置" : "Assistant settings"}><Settings2 size={16} /></VRouteLinkButton>
      }>
        <div className={styles.context}>
          <div className={styles.contextTitle}><FileText size={16} aria-hidden="true" /><span>{nativeReady ? view.title || (zh ? "研究对话" : "Research chat") : (zh ? "研究对话" : "Research chat")}</span></div>
          <div className={styles.actions}>
            <VButton variant="ghost" className={styles.mobileHistory} onPress={() => openDialog("history")}>{zh ? "标的" : "Target"}</VButton>
            <span className={styles.contextMeta} role="status">{nativeReady && view.stopping ? (zh ? "停止中" : "Stopping") : nativeReady && view.busy ? (zh ? "研究中" : "Running") : assistant.modelStatus !== "configured_unverified" ? (zh ? "模型未配置" : "Model not configured") : ""}</span>
          </div>
        </div>
        <div className={styles.native}><ChatCodingRoute /></div>
      </FinanceResearchFrame>
      <VDialog open={dialog !== null} contentClassName={styles.dialog} onOpenChange={(open) => { if (!open) setDialog(null); }} onCloseAutoFocus={(event) => {
        event.preventDefault();
        if (dialogOpener.current?.isConnected) dialogOpener.current.focus();
      }} title={dialog === "history" ? (zh ? "研究与记录" : "Research and history") : (zh ? "财报资料" : "Report library")} size="md">
        <div className={styles.dialogBody}>{dialog === "history" ? rail : dialog === "evidence" ? library : null}</div>
      </VDialog>
    </FinancialResearchBridgeContext.Provider>
  );
}
