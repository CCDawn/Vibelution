import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Brain, ChartPie, ClipboardList, FileText, Filter, History, LayoutDashboard, Plus, Search, Settings2, Sparkles, Star, Users, Wallet } from "lucide-react";
import { useLocation } from "react-router-dom";
import { createChatSession, fetchSessionDetail, querySessions } from "../../api/chat";
import { createFinancialAssistant, type FinancialAssistant } from "../../api/financialAssistant";
import { queryKeys } from "../../api/queryKeys";
import { fetchFinancialStock, financialMarketKeys, searchFinancialStocks, type StockIdentity, type StockPeriod } from "../../api/financialMarket";
import type { AssistantConversationTurn, SessionSummary } from "../../api/types";
import { VButton, VInput, VRouteLinkButton, VSkeleton, VStateSurface, VTabs } from "../../components/vui";
import { ChatCodingRoute } from "../ChatCodingRoute";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import { useChatRouteSelection } from "../chat/useChatRouteSelection";
import styles from "../FinanceRoute.styles";
import { FinanceResearchFrame } from "./FinanceResearchFrame";
import { FinanceReportLibrary } from "./FinanceReportLibrary";
import { FinancialResearchBridgeContext, type FinancialDraftRequest, type FinancialSessionView } from "./FinancialResearchBridge";
import { isFinancialSession } from "./financialResearchModel";
import { FinanceMarketPanel, FinanceStockHeader } from "./FinanceStockOverview";
import { FinanceResearchConfig, type FinanceResearchConfigValue } from "./FinanceResearchConfig";
import { FinanceResearchReport } from "./FinanceResearchReport";
import { FinanceResearchProcess } from "./FinanceResearchProcess";
import { FinanceResearchHistory } from "./FinanceResearchHistory";
import { EMPTY_FINANCIAL_MESSAGES, isResearchSearchResult, isValidResearchDate, localResearchDate, projectStockReport, reportMatchesStock, stockResearchPrompt, type ReportCitation } from "./stockResearchModel";
import { useFinanceWatchlist } from "./useFinanceWatchlist";
import { FinanceGeneralResearch } from "./FinanceGeneralResearch";
import { FinanceKnowledgeCenter } from "./FinanceKnowledgeCenter";
import { FinanceTaskCenter } from "./FinanceTaskCenter";
import { FinanceMarketExplorer } from "./FinanceMarketExplorer";
import { FinanceWatchlistTable } from "./FinanceWatchlistTable";
import { FinancePaperTrading } from "./FinancePaperTrading";
import { FinanceAnalystTeam, FinanceAnalystTeamInspector } from "./FinanceAnalystTeam";
import type { FinancialTeamRun } from "../../api/financialTeam";
import { FinancePortfolioResearch } from "./FinancePortfolioResearch";
import { listArchivedChatSessions } from "../../api/sessionArchive";
import { isSessionDeleteTombstoned } from "../sessionDeleteTombstone";
import type { FinanceSessionLifecycle } from "./useFinanceSessionLifecycle";

export function FinanceResearchWorkspace({ assistant, sessionId, zh, lifecycle }: { assistant: FinancialAssistant; sessionId: string; zh: boolean; lifecycle: FinanceSessionLifecycle }) {
  const location = useLocation(), route = useChatRouteSelection();
  const routeRef = useRef(route); routeRef.current = route;
  const client = useQueryClient(), stocks = useFinanceWatchlist(assistant.agentId);
  const [search, setSearch] = useState(""), [debouncedSearch, setDebouncedSearch] = useState("");
  const [historySearch, setHistorySearch] = useState(""), [historyQuery, setHistoryQuery] = useState("");
  const [period, setPeriod] = useState<StockPeriod>("day");
  const [area, setArea] = useState("workspace"), [tab, setTab] = useState("overview"), [asideTab, setAsideTab] = useState("process");
  const [taskTab, setTaskTab] = useState("records");
  const [requestedTeamRunId, setRequestedTeamRunId] = useState("");
  const [teamSelectedRun, setTeamSelectedRun] = useState<FinancialTeamRun | null>(null);
  const [researchKind, setResearchKind] = useState<"stock" | "topic">("stock");
  const [reportCollection, setReportCollection] = useState("active");
  const [config, setConfig] = useState<FinanceResearchConfigValue>({ period: "", date: localResearchDate(), scope: "comprehensive", depth: "brief" });
  const [citation, setCitation] = useState<ReportCitation | null>(null);
  const [creating, setCreating] = useState(false), [launching, setLaunching] = useState(false), [createError, setCreateError] = useState("");
  const [upgradingMarket, setUpgradingMarket] = useState(false);
  const marketUpgradeGate = useRef(false);
  const createGate = useRef(false), launchGate = useRef(false), createKey = useRef("");
  const mounted = useRef(false), requestSequence = useRef(0), hydratedSession = useRef("");
  const recordSequence = useRef(0);
  const [view, setView] = useState<FinancialSessionView | null>(null);
  const [activeTurn, setActiveTurn] = useState<{ sessionId: string; turn: AssistantConversationTurn | null } | null>(null);
  const [draftRequest, setDraftRequest] = useState<FinancialDraftRequest | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { const timer = setTimeout(() => setDebouncedSearch(search.trim()), 250); return () => clearTimeout(timer); }, [search]);
  useEffect(() => { const timer = setTimeout(() => setHistoryQuery(historySearch.trim()), 250); return () => clearTimeout(timer); }, [historySearch]);
  useEffect(() => { setCitation(null); setDraftRequest((request) => request?.sessionId === sessionId ? request : null); setLaunching(false); launchGate.current = false; }, [sessionId]);
  const market = useQuery({ queryKey: financialMarketKeys.stock(stocks.selected.symbol, period), queryFn: ({ signal }) => fetchFinancialStock(stocks.selected.symbol, period, { signal }), staleTime: 30_000, retry: false, refetchInterval: 60_000 });
  const lookup = useQuery({ queryKey: financialMarketKeys.search(debouncedSearch), queryFn: ({ signal }) => searchFinancialStocks(debouncedSearch, { signal }), enabled: Boolean(debouncedSearch), staleTime: 60_000, retry: false });
  const history = useInfiniteQuery({ queryKey: ["sessions", "finance", assistant.agentId], queryFn: ({ signal, pageParam }) => querySessions({ agentId: assistant.agentId, limit: 30, cursor: pageParam || undefined }, { signal }), initialPageParam: "", getNextPageParam: (page) => page.nextCursor || undefined, staleTime: 15_000, retry: false, refetchInterval: 30_000 });
  const records = (history.data?.pages.flatMap((page) => page.items) ?? []).filter((row) => isFinancialSession(row, assistant.agentId));
  const reportHistory = useInfiniteQuery({ queryKey: ["sessions", "finance", assistant.agentId, { q: historyQuery }], queryFn: ({ signal, pageParam }) => querySessions({ agentId: assistant.agentId, q: historyQuery, limit: 30, cursor: pageParam || undefined }, { signal }), enabled: area === "reports", initialPageParam: "", getNextPageParam: (page) => page.nextCursor || undefined, staleTime: 15_000, retry: false });
  const reportRecords = (reportHistory.data?.pages.flatMap((page) => page.items) ?? []).filter((row) => isFinancialSession(row, assistant.agentId) && isResearchSearchResult(row, historyQuery));
  const archivedHistory = useInfiniteQuery({ queryKey: ["sessions", "finance-archived", assistant.agentId], queryFn: ({ signal, pageParam }) => listArchivedChatSessions({ signal, limit: 200, cursor: pageParam || undefined }), enabled: area === "reports" && reportCollection === "archived", initialPageParam: "", getNextPageParam: (page) => page.nextCursor || undefined, staleTime: 15_000, retry: false });
  const archivedRecords = (archivedHistory.data?.pages.flatMap((page) => page.items) ?? []).filter((row) => row.agentId === assistant.agentId && row.archiveState?.status === "archived" && !isSessionDeleteTombstoned(row.id));
  const nativeReady = view?.sessionId === sessionId, currentView = nativeReady ? view : null;
  const messages = currentView?.messages ?? EMPTY_FINANCIAL_MESSAGES;
  const report = useMemo(() => projectStockReport(messages, currentView), [messages, currentView?.terminalReason, currentView?.lastTurnStatus, currentView?.lastTurnTerminalTurnId]);
  const stockReport = reportMatchesStock(report, messages, stocks.selected) ? report : null;
  const busy = Boolean(currentView?.busy || currentView?.submitPending);
  const marketUpgradeDisabled = busy || creating || launching || Boolean(currentView?.stopping);
  const readyForResearch = nativeReady && !currentView?.transcriptPending && !currentView?.stopping;
  const onSessionView = useCallback((next: FinancialSessionView) => setView((current) => current?.sessionId === next.sessionId && Object.keys(next).every((key) => current[key as keyof FinancialSessionView] === next[key as keyof FinancialSessionView]) ? current : next), []);
  const onActiveTurn = useCallback((id: string, turn: AssistantConversationTurn | null) => setActiveTurn((current) => current?.sessionId === id && current.turn === turn ? current : { sessionId: id, turn }), []);
  const onDraftSubmitted = useCallback(() => { launchGate.current = false; setLaunching(false); }, []);
  const bridge = useMemo(() => ({ agentId: assistant.agentId, draftRequest, onSessionView, onActiveTurn, onDraftSubmitted }), [assistant.agentId, draftRequest, onSessionView, onActiveTurn, onDraftSubmitted]);
  // Keep the native workbench stable when the financial presentation updates.
  const nativeWorkspace = useMemo(() => <ChatCodingRoute />, []);
  const returnTo = `${location.pathname}${location.search}`;
  useEffect(() => {
    if (!nativeReady || !messages.length || currentView?.transcriptPending || hydratedSession.current === sessionId) return;
    hydratedSession.current = sessionId;
    setResearchKind(currentView?.title.startsWith("主题 ·") ? "topic" : "stock");
    const user = [...messages].reverse().find((message) => message.role === "user");
    const ticker = user?.role === "user" ? /(?:^|[^\d])([036489]\d{5})(?!\d)/.exec(user.content)?.[1] : undefined;
    if (ticker && ticker !== stocks.selected.ticker) stocks.selectStock({ symbol: (ticker[0] === "6" ? "sh" : "03".includes(ticker[0]) ? "sz" : "bj") + ticker, ticker, name: ticker, market: ticker[0] === "6" ? "上交所" : "03".includes(ticker[0]) ? "深交所" : "北交所" });
  }, [currentView?.transcriptPending, messages, nativeReady, sessionId, stocks]);
  useEffect(() => { if (market.data?.stock.symbol === stocks.selected.symbol && market.data.stock.name !== stocks.selected.name) stocks.selectStock(market.data.stock); }, [market.data, stocks]);
  async function openRecord(record: SessionSummary) {
    const expected = routeRef.current.selection;
    const sequence = ++recordSequence.current;
    setCreateError("");
    try {
      const detail = await fetchSessionDetail(record.id, { transcriptScope: "none", includeSecondary: false });
      if (detail.id !== record.id || !isFinancialSession(detail, assistant.agentId)) {
        throw new Error(zh ? "这条记录不属于当前金融助手" : "This research belongs to another agent");
      }
      if (!mounted.current || sequence !== recordSequence.current || !routeRef.current.matchesSelection(expected)) return;
      client.setQueryData(["finance", "session-binding", assistant.agentId, record.id], detail);
      routeRef.current.openSession(record.id, { replace: false, telemetrySource: "finance_research_history" });
      setDraftRequest(null);
      setCitation(null);
      setArea("workspace");
      setResearchKind(detail.title.startsWith("主题 ·") ? "topic" : "stock");
      setTab("report");
    } catch (error) {
      if (mounted.current && sequence === recordSequence.current) {
        setCreateError(error instanceof Error ? error.message : (zh ? "记录加载失败" : "Could not open research"));
      }
    }
  }
  function openBatchRun(runId: string, symbol: string) {
    const ticker = symbol.slice(2);
    stocks.selectStock({ symbol, ticker, name: stocks.watchlist.find((item) => item.symbol === symbol)?.name || ticker, market: symbol.startsWith("sh") ? "上交所" : "深交所" });
    setTeamSelectedRun(null); setRequestedTeamRunId(runId); setArea("team"); setAsideTab("process");
  }
  function selectStock(stock: StockIdentity) { stocks.selectStock(stock); setSearch(""); setDebouncedSearch(""); setArea("workspace"); setResearchKind("stock"); setTab("overview"); setCitation(null); }
  function draft(text: string, targetId: string, submit: boolean) { requestSequence.current += 1; setDraftRequest({ id: requestSequence.current, sessionId: targetId, text, submit }); setArea("workspace"); setTab("research"); setAsideTab("process"); }
  async function newResearch(start = false, custom?: { text: string; title: string }, prepareDraft = false) {
    if (createGate.current) return;
    createGate.current = true; createKey.current ||= crypto.randomUUID();
    const expected = routeRef.current.selection;
    const text = custom?.text ?? stockResearchPrompt(market.data?.stock ?? stocks.selected, config.period, config.date, config.scope, config.depth, market.data);
    setCreating(true); setCreateError("");
    try {
      const result = await createChatSession({ agentId: assistant.agentId, title: custom ? `主题 · ${custom.title}` : `${stocks.selected.name} (${stocks.selected.ticker}) · ${config.period || config.date}` }, createKey.current);
      if (!isFinancialSession(result, assistant.agentId)) throw new Error(zh ? "新会话身份不匹配" : "Session identity mismatch");
      // Reuse the verified create response at the finance entry guard. Otherwise
      // its loading frame would unmount this workspace and discard the draft.
      client.setQueryData(["finance", "session-binding", assistant.agentId, result.id], result);
      void client.invalidateQueries({ queryKey: ["sessions", "finance", assistant.agentId] }); createKey.current = "";
      if (mounted.current && routeRef.current.replaceIfStillViewing(expected, { kind: "session", sessionId: result.id })) { setResearchKind(custom ? "topic" : "stock"); if (start || prepareDraft) draft(text, result.id, start); else { setDraftRequest(null); setArea("workspace"); setTab("research"); } }
    } catch (error) { if (mounted.current) setCreateError(error instanceof Error ? error.message : (zh ? "创建失败，请重试" : "Could not create research")); }
    finally { createGate.current = false; launchGate.current = false; if (mounted.current) { setCreating(false); setLaunching(false); } }
  }
  function startResearch() {
    if (!readyForResearch || busy || createGate.current || launchGate.current || !isValidResearchDate(config.date) || assistant.modelStatus !== "configured_unverified") return;
    launchGate.current = true; setLaunching(true);
    if (messages.length) { void newResearch(true); return; }
    draft(stockResearchPrompt(market.data?.stock ?? stocks.selected, config.period, config.date, config.scope, config.depth, market.data), sessionId, true);
  }
  function startTopicResearch(text: string, title: string) {
    if (!readyForResearch || busy || createGate.current || launchGate.current || assistant.modelStatus !== "configured_unverified") return;
    launchGate.current = true; setLaunching(true);
    void newResearch(true, { text, title });
  }
  function prepareResearchPrompt(text: string) {
    if (!nativeReady || currentView?.stopping || currentView?.transcriptPending || createGate.current || launchGate.current) {
      setCreateError(zh ? "研究会话尚未准备好，请稍后再试" : "Research session is not ready yet");
      return;
    }
    setCreateError("");
    draft(text, sessionId, false);
  }
  function prepareTopicPrompt(text: string, title: string) {
    if (!nativeReady || busy || currentView?.stopping || currentView?.transcriptPending || createGate.current || launchGate.current) {
      setCreateError(zh ? "研究会话尚未准备好，请稍后再试" : "Research session is not ready yet");
      return;
    }
    void newResearch(false, { text, title }, true);
  }
  function focusCitation(next: ReportCitation) { setCitation(next); setAsideTab("evidence"); }
  async function enableMarketQueries() {
    if (marketUpgradeGate.current || marketUpgradeDisabled || assistant.marketToolStatus !== "upgrade_available") return;
    marketUpgradeGate.current = true; setUpgradingMarket(true); setCreateError("");
    try {
      const result = await createFinancialAssistant();
      if (result.assistant.agentId !== assistant.agentId) throw new Error(zh ? "助手身份已变化，请刷新后核对" : "Assistant identity changed; refresh and check");
      client.setQueryData<FinancialAssistant[]>(queryKeys.financialAssistants(), (rows) => [
        ...(rows ?? []).filter((row) => row.agentId !== result.assistant.agentId), result.assistant,
      ]);
    } catch (error) {
      if (mounted.current) setCreateError(error instanceof Error ? error.message : (zh ? "行情查询启用失败，请重试" : "Could not enable market queries"));
    } finally {
      marketUpgradeGate.current = false;
      if (mounted.current) setUpgradingMarket(false);
    }
  }
  const researchConfig = <FinanceResearchConfig value={config} onChange={setConfig} onStart={startResearch} disabled={!readyForResearch || busy || creating || launching || !isValidResearchDate(config.date) || assistant.modelStatus !== "configured_unverified"} pending={creating || launching} zh={zh} />;
  function historyContent(compact = true) { return history.isError ? <VStateSurface density="compact" tone="error" title={zh ? "记录加载失败" : "History unavailable"} actions={<VButton onPress={() => void history.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : history.isPending ? <div className={styles.workspaceHistoryLoading}><VSkeleton /><VSkeleton /></div> : <FinanceResearchHistory records={records} selectedId={sessionId} onOpen={openRecord} zh={zh} compact={compact} onAction={lifecycle.requestAction} actionPending={lifecycle.pending} />; }
  const navigation = [
    { id: "workspace", label: zh ? "股票研究" : "Stock research", icon: <LayoutDashboard size={15} /> },
    { id: "general", label: zh ? "通用研究" : "Topic research", icon: <Search size={15} /> },
    { id: "team", label: zh ? "分析员协作" : "Analyst team", icon: <Users size={15} /> },
    { id: "screen", label: zh ? "股票筛选" : "Stock screener", icon: <Filter size={15} /> },
    { id: "watchlist", label: zh ? "自选行情" : "Watchlist", icon: <Star size={15} /> },
    { id: "reports", label: zh ? "报告中心" : "Reports", icon: <FileText size={15} /> },
    { id: "tasks", label: zh ? "研究任务" : "Research tasks", icon: <ClipboardList size={15} /> },
    { id: "account", label: zh ? "模拟账户" : "Paper account", icon: <Wallet size={15} /> },
    { id: "portfolio", label: zh ? "组合研究" : "Portfolio research", icon: <ChartPie size={15} /> },
    { id: "review", label: zh ? "交易复盘" : "Trading review", icon: <History size={15} /> },
    { id: "memory", label: zh ? "研究记忆" : "Memory", icon: <Brain size={15} /> },
    { id: "skills", label: zh ? "技能中心" : "Skills", icon: <Sparkles size={15} /> },
    { id: "learning", label: zh ? "学习中心" : "Learning", icon: <BookOpen size={15} /> },
  ];
  const sidebar = <div className={styles.rail}>
    <div className={styles.workspaceActions}><VButton variant="secondary" className={styles.newButton} icon={<Plus size={15} />} isDisabled={creating} onPress={() => void newResearch()}>{creating ? (zh ? "创建中" : "Creating") : (zh ? "新研究" : "New research")}</VButton><VRouteLinkButton className={styles.workspaceSettings} to={agentCenterConfigRoute({ agentId: assistant.agentId, returnTo, returnLabel: zh ? "炒股智能体" : "Investment assistant" })} aria-label={zh ? "模型与助手配置" : "Assistant settings"}><Settings2 size={16} /></VRouteLinkButton></div>
    <div className={styles.workspaceSection}><span className={styles.sectionHeading}><Search size={14} />{zh ? "查找股票" : "Find a stock"}</span><VInput value={search} onChange={(event) => setSearch(event.target.value)} maxLength={40} aria-label={zh ? "公司或股票代码" : "Company or ticker"} placeholder={zh ? "名称 / 拼音 / 代码" : "Name / ticker"} />
      {debouncedSearch ? lookup.isPending ? <VSkeleton /> : lookup.isError ? <VStateSurface tone="error" density="compact" title={zh ? "股票查询失败" : "Lookup failed"} actions={<VButton onPress={() => void lookup.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : <div className={styles.workspaceNav} aria-label={zh ? "股票搜索结果" : "Stock search results"}>{lookup.data?.length ? lookup.data.map((stock) => <VButton key={stock.symbol} variant="ghost" className={styles.workspaceSearchButton} onPress={() => selectStock(stock)}><span className={styles.workspaceSearchText}><strong className={styles.workspaceStockName}>{stock.name}</strong><span className={styles.small}>{stock.ticker} · {stock.market}</span></span></VButton>) : <span className={styles.small}>{zh ? "没有匹配股票" : "No matches"}</span>}</div> : null}
    </div>
    <nav className={styles.workspaceNav} aria-label={zh ? "股票研究导航" : "Stock research navigation"}>{navigation.map((item) => <VButton key={item.id} variant="ghost" className={[styles.workspaceNavButton, area === item.id ? styles.workspaceNavSelected : ""].join(" ")} icon={item.icon} aria-pressed={area === item.id} onPress={() => { if (item.id === "team") setRequestedTeamRunId(""); setArea(item.id); }}>{item.label}</VButton>)}</nav>
    <div className={styles.workspaceSection}><span className={styles.sectionHeading}><span>{zh ? "我的自选" : "Following"}</span><span>{stocks.watchlist.length}</span></span>{stocks.watchlist.length ? stocks.watchlist.map((stock) => <VButton key={stock.symbol} variant="ghost" className={styles.workspaceWatchlistButton} aria-pressed={stocks.selected.symbol === stock.symbol} onPress={() => selectStock(stock)}><span className={styles.workspaceWatchlistRow}><span className={styles.workspaceTruncate}>{stock.name}</span><span className={styles.workspaceTicker}>{stock.ticker}</span></span></VButton>) : <span className={styles.small}>{zh ? "点击股票右上角 ☆ 添加" : "Use ☆ to follow a stock"}</span>}{stocks.storageError ? <span className={styles.workspaceStorageWarning}>{zh ? "自选未保存，关闭页面后会丢失" : "Watchlist could not be saved"}</span> : null}</div>
    <div className={styles.workspaceRecent}><div className={styles.sectionHeading}><span>{zh ? "最近研究" : "Recent research"}</span><History size={14} /></div>{historyContent()}{history.hasNextPage ? <VButton variant="ghost" isDisabled={history.isFetchingNextPage} onPress={() => void history.fetchNextPage()}>{zh ? "更多记录" : "More history"}</VButton> : null}</div>
  </div>;
  const aside = <div className={styles.workspaceAside}><VTabs value={asideTab} onValueChange={setAsideTab} aria-label={zh ? "研究辅助面板" : "Research inspector"} className={styles.workspaceAsideTabs} items={[{ id: "process", label: zh ? "研究过程" : "Activity" }, { id: "evidence", label: zh ? "引用与资料" : "Sources" }]} /><div className={styles.workspaceAsideBody}>{asideTab === "process" ? area === "team" ? <FinanceAnalystTeamInspector run={teamSelectedRun?.assistantAgentId === assistant.agentId ? teamSelectedRun : null} zh={zh} onOpenSession={(id) => routeRef.current.openSession(id, { surface: "chat", replace: false, telemetrySource: "finance_team_inspector" })} /> : <FinanceResearchProcess view={currentView} activeTurn={activeTurn?.sessionId === sessionId ? activeTurn.turn : null} zh={zh} onEnableMarket={assistant.marketToolStatus === "upgrade_available" ? () => void enableMarketQueries() : undefined} marketPending={upgradingMarket} marketDisabled={marketUpgradeDisabled} onOpenChat={() => { setArea("workspace"); setTab("research"); }} /> : <FinanceReportLibrary assistant={assistant} zh={zh} returnTo={returnTo} citation={citation} />}</div></div>;
  return <FinancialResearchBridgeContext.Provider value={bridge}><FinanceResearchFrame zh={zh} sidebar={sidebar} aside={aside}>
    {createError || lifecycle.error ? <VStateSurface tone="error" title={zh ? "操作未完成" : "Could not complete action"}><span className={styles.workspaceErrorText}>{createError || lifecycle.error}</span></VStateSurface> : null}
    {lifecycle.dialog}
    {area === "workspace" ? <>{researchKind === "stock" ? <FinanceStockHeader stock={stocks.selected} query={market} starred={stocks.watchlist.some((stock) => stock.symbol === stocks.selected.symbol)} onToggleStar={() => stocks.toggleStock(market.data?.stock ?? stocks.selected)} zh={zh} /> : <div className={styles.workspaceTopicHeader}><strong>{currentView?.title || (zh ? "主题研究" : "Topic research")}</strong><VButton variant="ghost" onPress={() => setArea("general")}>{zh ? "新主题" : "New topic"}</VButton></div>}<div className={styles.workspaceViewTabs}><VTabs value={tab} onValueChange={setTab} aria-label={zh ? "股票研究视图" : "Stock research view"} items={[{ id: "overview", label: researchKind === "topic" ? (zh ? "研究设置" : "Research settings") : (zh ? "股票概览" : "Overview") }, ...(researchKind === "stock" ? [{ id: "news", label: zh ? "新闻公告" : "News" }, { id: "fundamentals", label: zh ? "财务指标" : "Financials" }] : []), { id: "research", label: zh ? "AI 研究" : "AI research" }, { id: "report", label: zh ? "研究报告" : "Report" }]} /></div>
      {tab === "news" || tab === "fundamentals" ? <div className={styles.workspaceCollection}><FinanceMarketExplorer mode={tab} stock={stocks.selected} onSelectStock={selectStock} onResearchPrompt={prepareResearchPrompt} zh={zh} /></div> : tab === "overview" && researchKind === "topic" ? <FinanceGeneralResearch onStart={startTopicResearch} disabled={!readyForResearch || busy || creating || launching || assistant.modelStatus !== "configured_unverified"} pending={creating || launching} zh={zh} /> : tab !== "research" ? <div className={styles.workspaceOverview}>{tab === "overview" ? <><FinanceMarketPanel query={market} period={period} onPeriodChange={setPeriod} zh={zh} />{researchConfig}<FinanceResearchReport assistantAgentId={assistant.agentId} sessionId={sessionId} report={stockReport} zh={zh} busy={busy} summaryOnly onCitation={focusCitation} onResearch={() => { if (stockReport) setTab("report"); else startResearch(); }} /></> : <FinanceResearchReport assistantAgentId={assistant.agentId} sessionId={sessionId} report={researchKind === "topic" ? report : stockReport} zh={zh} busy={busy} onCitation={focusCitation} onResearch={researchKind === "topic" ? () => setArea("general") : startResearch} />}</div> : <div className={styles.workspaceChatHeading}><span>{currentView?.title || (zh ? "研究助手" : "Research assistant")}</span><VButton variant="ghost" onPress={() => setTab("overview")}>{zh ? "研究设置" : "Research settings"}</VButton></div>}
    </> : area === "general" ? <FinanceGeneralResearch onStart={startTopicResearch} disabled={!readyForResearch || busy || creating || launching || assistant.modelStatus !== "configured_unverified"} pending={creating || launching} zh={zh} />
      : area === "screen" ? <div className={styles.workspaceCollection}><FinanceMarketExplorer mode="screen" stock={stocks.selected} onSelectStock={selectStock} onResearchPrompt={prepareResearchPrompt} zh={zh} /></div>
      : area === "team" ? <div className={styles.workspaceCollection}><FinanceAnalystTeam key={`${assistant.agentId}:${requestedTeamRunId}`} requestedRunId={requestedTeamRunId} onBackToBatch={requestedTeamRunId ? () => { setTaskTab("batches"); setArea("tasks"); } : undefined} assistant={assistant} stock={stocks.selected} zh={zh} onSelectedRunChange={setTeamSelectedRun} onOpenSession={(id) => routeRef.current.openSession(id, { surface: "chat", replace: false, telemetrySource: "finance_analyst_session" })} /></div>
      : area === "account" || area === "review" ? <div className={styles.workspaceCollection}><FinancePaperTrading assistant={assistant} stock={stocks.selected} mode={area} zh={zh} onResearchPrompt={(text) => prepareTopicPrompt(text, zh ? "模拟交易复盘" : "Paper trading review")} /></div>
      : area === "portfolio" ? <div className={styles.workspaceCollection}><FinancePortfolioResearch assistant={assistant} zh={zh} onSelectStock={selectStock} onResearchPrompt={(text) => prepareTopicPrompt(text, zh ? "模拟持仓研究" : "Simulated portfolio research")} onOpenAccount={() => setArea("account")} /></div>
      : area === "memory" || area === "skills" || area === "learning" ? <FinanceKnowledgeCenter assistant={assistant} stock={stocks.selected} mode={area} zh={zh} onResearchPrompt={prepareResearchPrompt} />
      : area === "tasks" ? <><FinanceTaskCenter tab={taskTab} onTabChange={setTaskTab} assistant={assistant} stock={stocks.selected} watchlist={stocks.watchlist} onOpenRun={openBatchRun} moreRecords={history.hasNextPage ? <VButton isPending={history.isFetchingNextPage} onPress={() => void history.fetchNextPage()}>{zh ? "更多记录" : "More records"}</VButton> : null} records={records} selectedId={sessionId} onOpen={openRecord} onRefresh={() => void history.refetch()} loading={history.isFetching} error={history.isError} zh={zh} onAction={lifecycle.requestAction} actionPending={lifecycle.pending} /></>
      : area === "reports" ? <div className={styles.workspaceCollection}><h1 className={styles.workspaceCollectionTitle}>{zh ? "报告中心" : "Report center"}</h1><VTabs value={reportCollection} onValueChange={setReportCollection} aria-label={zh ? "研究记录范围" : "Research collection"} items={[{ id: "active", label: zh ? "活动研究" : "Active" }, { id: "archived", label: zh ? "已归档" : "Archived" }]} />{reportCollection === "archived" ? <><FinanceResearchHistory records={archivedRecords} selectedId="" onOpen={(record) => routeRef.current.openSession(record.id, { surface: "chat", replace: false, telemetrySource: "finance_archived_research" })} zh={zh} archived busy={archivedHistory.isPending} error={archivedHistory.isError} onRetry={() => void archivedHistory.refetch()} onAction={lifecycle.requestAction} actionPending={lifecycle.pending} />{archivedHistory.hasNextPage ? <VButton onPress={() => void archivedHistory.fetchNextPage()} isPending={archivedHistory.isFetchingNextPage}>{zh ? "更多归档" : "More archived"}</VButton> : null}</> : <><FinanceResearchHistory records={reportRecords} selectedId={sessionId} onOpen={openRecord} zh={zh} searchValue={historySearch} onSearchChange={setHistorySearch} busy={reportHistory.isPending || historySearch.trim() !== historyQuery} error={reportHistory.isError && historySearch.trim() === historyQuery} onRetry={() => void reportHistory.refetch()} onAction={lifecycle.requestAction} actionPending={lifecycle.pending} />{reportHistory.hasNextPage && historySearch.trim() === historyQuery ? <VButton onPress={() => void reportHistory.fetchNextPage()} isPending={reportHistory.isFetchingNextPage}>{zh ? "更多记录" : "More history"}</VButton> : null}</>}</div>
      : <div className={styles.workspaceCollection}><h1 className={styles.workspaceCollectionTitle}>{zh ? "自选行情" : "Watchlist"}</h1><FinanceWatchlistTable watchlist={stocks.watchlist} onSelectStock={selectStock} onRemoveStock={stocks.toggleStock} zh={zh} /></div>}
    <div className={area === "workspace" && tab === "research" ? styles.native : "hidden"} aria-hidden={area !== "workspace" || tab !== "research"}>{nativeWorkspace}</div>
  </FinanceResearchFrame></FinancialResearchBridgeContext.Provider>;
}
