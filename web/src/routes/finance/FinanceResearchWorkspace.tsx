import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Search, Settings2 } from "lucide-react";
import { useLocation } from "react-router-dom";
import { createChatSession, fetchSessionDetail, querySessions } from "../../api/chat";
import { createFinancialAssistant, type FinancialAssistant } from "../../api/financialAssistant";
import { queryKeys } from "../../api/queryKeys";
import { fetchFinancialStock, financialMarketKeys, searchFinancialStocks, type StockIdentity, type StockMarketCode, type StockPeriod } from "../../api/financialMarket";
import type { AssistantConversationTurn, SessionSummary } from "../../api/types";
import { VButton, VDropdownMenu, VIconButton, VInput, VRouteLinkButton, VSelect, VSkeleton, VStateSurface, VTabs, VToolbar } from "../../components/vui";
import { ChatCodingRoute } from "../ChatCodingRoute";
import { agentCenterConfigRoute } from "../agentCenterRoutes";
import { useChatRouteSelection } from "../chat/useChatRouteSelection";
import styles from "../FinanceRoute.styles";
import { FinanceResearchFrame } from "./FinanceResearchFrame";
import { FinanceReportLibrary } from "./FinanceReportLibrary";
import { FinancialResearchBridgeContext, type FinancialDraftRequest, type FinancialSessionView } from "./FinancialResearchBridge";
import { isFinancialSession } from "./financialResearchModel";
import { FinanceMarketPanel, FinanceStockHeader } from "./FinanceStockOverview";
import { FinanceResearchConfig, financialResearchModelGateIssue, type FinanceResearchConfigValue } from "./FinanceResearchConfig";
import { FinanceResearchReport } from "./FinanceResearchReport";
import { FinanceResearchProcess } from "./FinanceResearchProcess";
import { FinanceResearchHistory } from "./FinanceResearchHistory";
import { EMPTY_FINANCIAL_MESSAGES, isResearchSearchResult, isValidResearchDate, localResearchDate, projectStockReport, reportMatchesStock, stockFromResearchRequest, stockResearchPrompt, type ReportCitation, type ResearchDepth } from "./stockResearchModel";
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
import { FinanceDashboard } from "./FinanceDashboard";
import { FinanceScreenWorkspace } from "./FinanceScreenWorkspace";
import { FinanceResearchProfiles } from "./FinanceResearchProfiles";
import { FinanceReportsCenter } from "./FinanceReportsCenter";
import { FinanceManualPositions } from "./FinanceManualPositions";
import { stockMarketCode } from "./financeMarketDisplay";
import { FinanceWorkspaceSidebar, type FinanceSessionCollection } from "./FinanceWorkspaceSidebar";
import { financeWorkspaceGroup } from "./financeWorkspaceNavigation";
import { useFinanceWorkspaceNavigation } from "./useFinanceWorkspaceNavigation";
import { FinanceWorkspaceInspector } from "./FinanceWorkspaceInspector";
import inspectorStyles from "./FinanceWorkspaceInspector.styles";
import type { FinancialReportSummary } from "../../api/types/financialReports";

export function FinanceResearchWorkspace({ assistant, sessionId, zh, lifecycle }: { assistant: FinancialAssistant; sessionId: string; zh: boolean; lifecycle: FinanceSessionLifecycle }) {
  const location = useLocation(), route = useChatRouteSelection();
  const navigation = useFinanceWorkspaceNavigation();
  const { area, tab, asideTab, portfolioSource, reviewTab, taskTab, reportCollection, preparing, selectedReport } = navigation;
  const setArea = (area: string) => navigation.update({ area, preparing: false, selectedReport: null });
  const setTab = (tab: string) => navigation.update({ tab, preparing: false });
  const setAsideTab = (asideTab: string) => navigation.update({ asideTab });
  const setPortfolioSource = (portfolioSource: string) => navigation.update({ portfolioSource });
  const setReviewTab = (reviewTab: string) => navigation.update({ reviewTab, selectedReport: null });
  const setTaskTab = (taskTab: string) => navigation.update({ taskTab });
  const setReportCollection = (reportCollection: string) => navigation.update({ reportCollection, selectedReport: null });
  const [reportContext, setReportContext] = useState<FinancialReportSummary | null>(null);
  const reportPaneRef = useRef<HTMLDivElement>(null);
  useEffect(() => { if (selectedReport) reportPaneRef.current?.scrollTo?.({ top: 0 }); }, [selectedReport?.sessionId, selectedReport?.turnId]);
  const locationRef = useRef(location); locationRef.current = location;
  const routeRef = useRef(route); routeRef.current = route;
  const client = useQueryClient(), stocks = useFinanceWatchlist(assistant.agentId);
  const [search, setSearch] = useState(""), [debouncedSearch, setDebouncedSearch] = useState("");
  const [searchMarket, setSearchMarket] = useState<StockMarketCode>("CN");
  const [historySearch, setHistorySearch] = useState(""), [historyQuery, setHistoryQuery] = useState("");
  const [sessionSearch, setSessionSearch] = useState(""), [sessionQuery, setSessionQuery] = useState("");
  const [sidebarCollection, setSidebarCollection] = useState<FinanceSessionCollection>("recent");
  const [period, setPeriod] = useState<StockPeriod>("day");
  const [requestedTeamRunId, setRequestedTeamRunId] = useState("");
  const [teamSelectedRun, setTeamSelectedRun] = useState<FinancialTeamRun | null>(null);
  const [researchKind, setResearchKind] = useState<"stock" | "topic">("stock");
  const [config, setConfig] = useState<FinanceResearchConfigValue>({ period: "", date: localResearchDate(), scope: "comprehensive", depth: "brief" });
  const [selectedProfileId, setSelectedProfileId] = useState("");
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
  useEffect(() => { const timer = setTimeout(() => setSessionQuery(sessionSearch.trim()), 250); return () => clearTimeout(timer); }, [sessionSearch]);
  useEffect(() => { setCitation(null); setDraftRequest((request) => request?.sessionId === sessionId ? request : null); setLaunching(false); launchGate.current = false; }, [sessionId]);
  useEffect(() => { setCitation(null); }, [area, selectedReport?.sessionId, selectedReport?.turnId]);
  const market = useQuery({ queryKey: financialMarketKeys.stock(stocks.selected.symbol, period), queryFn: ({ signal }) => fetchFinancialStock(stocks.selected.symbol, period, { signal }), staleTime: 30_000, retry: false, refetchInterval: 60_000 });
  const lookup = useQuery({ queryKey: financialMarketKeys.search(debouncedSearch, searchMarket), queryFn: ({ signal }) => searchFinancialStocks(debouncedSearch, { signal, market: searchMarket }), enabled: Boolean(debouncedSearch), staleTime: 60_000, retry: false });
  const history = useInfiniteQuery({ queryKey: ["sessions", "finance", assistant.agentId], queryFn: ({ signal, pageParam }) => querySessions({ agentId: assistant.agentId, limit: 30, cursor: pageParam || undefined }, { signal }), initialPageParam: "", getNextPageParam: (page) => page.nextCursor || undefined, staleTime: 15_000, retry: false, refetchInterval: 30_000 });
  const records = (history.data?.pages.flatMap((page) => page.items) ?? []).filter((row) => isFinancialSession(row, assistant.agentId));
  const sessionLookup = useInfiniteQuery({ queryKey: ["sessions", "finance", assistant.agentId, { q: sessionQuery }], queryFn: ({ signal, pageParam }) => querySessions({ agentId: assistant.agentId, q: sessionQuery, limit: 30, cursor: pageParam || undefined }, { signal }), enabled: sidebarCollection === "recent" && Boolean(sessionQuery), initialPageParam: "", getNextPageParam: (page) => page.nextCursor || undefined, staleTime: 15_000, retry: false });
  const reportHistory = useInfiniteQuery({ queryKey: ["sessions", "finance", assistant.agentId, { q: historyQuery }], queryFn: ({ signal, pageParam }) => querySessions({ agentId: assistant.agentId, q: historyQuery, limit: 30, cursor: pageParam || undefined }, { signal }), enabled: area === "reports" && reportCollection === "active", initialPageParam: "", getNextPageParam: (page) => page.nextCursor || undefined, staleTime: 15_000, retry: false });
  const reportRecords = (reportHistory.data?.pages.flatMap((page) => page.items) ?? []).filter((row) => isFinancialSession(row, assistant.agentId) && isResearchSearchResult(row, historyQuery));
  const archivedHistory = useInfiniteQuery({ queryKey: ["sessions", "finance-archived", assistant.agentId], queryFn: ({ signal, pageParam }) => listArchivedChatSessions({ signal, limit: 200, cursor: pageParam || undefined }), enabled: sidebarCollection === "archived" || (area === "reports" && reportCollection === "archived"), initialPageParam: "", getNextPageParam: (page) => page.nextCursor || undefined, staleTime: 15_000, retry: false });
  const archivedRecords = (archivedHistory.data?.pages.flatMap((page) => page.items) ?? []).filter((row) => row.agentId === assistant.agentId && row.archiveState?.status === "archived" && !isSessionDeleteTombstoned(row.id));
  const nativeReady = view?.sessionId === sessionId && view?.agentId === assistant.agentId, currentView = nativeReady ? view : null;
  const messages = currentView?.messages ?? EMPTY_FINANCIAL_MESSAGES;
  const report = useMemo(() => projectStockReport(messages, currentView), [messages, currentView?.terminalReason, currentView?.lastTurnStatus, currentView?.lastTurnTerminalTurnId]);
  const stockReport = reportMatchesStock(report, messages, stocks.selected) ? report : null;
  useEffect(() => {
    if (nativeReady && currentView?.terminalReason === "success" && report?.turnId && report.turnId === currentView.lastTurnTerminalTurnId) void client.invalidateQueries({ queryKey: ["finance", "report-catalog", assistant.agentId] });
  }, [client, assistant.agentId, nativeReady, currentView?.terminalReason, currentView?.lastTurnTerminalTurnId, report?.turnId]);
  useEffect(() => {
    if (teamSelectedRun?.coordinationStatus === "completed" && teamSelectedRun.synthesis.turnId) void client.invalidateQueries({ queryKey: ["finance", "report-catalog", assistant.agentId] });
  }, [client, assistant.agentId, teamSelectedRun?.coordinationStatus, teamSelectedRun?.synthesis.turnId]);
  const busy = Boolean(currentView?.busy || currentView?.submitPending);
  const marketUpgradeDisabled = busy || creating || launching || Boolean(currentView?.stopping);
  const readyForResearch = nativeReady && !currentView?.transcriptPending && !currentView?.stopping;
  const modelGateIssue = financialResearchModelGateIssue({ sessionId: nativeReady ? sessionId : undefined, options: currentView?.sessionLlmOptions, loading: currentView?.sessionLlmOptionsLoading, error: currentView?.sessionLlmOptionsError, selection: currentView?.turnModelSelection });
  const onSessionView = useCallback((next: FinancialSessionView) => setView((current) => current?.sessionId === next.sessionId && Object.keys(next).every((key) => current[key as keyof FinancialSessionView] === next[key as keyof FinancialSessionView]) ? current : next), []);
  const onActiveTurn = useCallback((id: string, turn: AssistantConversationTurn | null) => setActiveTurn((current) => current?.sessionId === id && current.turn === turn ? current : { sessionId: id, turn }), []);
  const onDraftSubmitted = useCallback(() => { launchGate.current = false; setLaunching(false); }, []);
  const bridge = useMemo(() => ({ agentId: assistant.agentId, draftRequest, onSessionView, onActiveTurn, onDraftSubmitted }), [assistant.agentId, draftRequest, onSessionView, onActiveTurn, onDraftSubmitted]);
  // Keep the native workbench stable when the financial presentation updates.
  const nativeWorkspace = useMemo(() => <ChatCodingRoute />, []);
  const returnTo = `${location.pathname}${location.search}`;
  useEffect(() => {
    if (preparing || area !== "workspace" || !["research", "report"].includes(tab) || !nativeReady || !messages.length || currentView?.transcriptPending || hydratedSession.current === sessionId) return;
    hydratedSession.current = sessionId;
    setResearchKind(currentView?.title.startsWith("主题 ·") ? "topic" : "stock");
    const identity = [...messages].reverse().flatMap((message) => message.role === "user" ? [stockFromResearchRequest(message.content)] : []).find((item) => item !== null);
    if (identity && identity.symbol !== stocks.selected.symbol) { stocks.selectStock(identity); setSearchMarket(stockMarketCode(identity)); }
  }, [preparing, area, tab, currentView?.transcriptPending, messages, nativeReady, sessionId, stocks]);
  const marketIdentityUpdated = useRef("");
  useEffect(() => { const quote = market.data?.stock; const key = quote ? `${quote.symbol}:${quote.name}` : ""; if (quote?.symbol === stocks.selected.symbol && quote.name !== stocks.selected.name && marketIdentityUpdated.current !== key) { marketIdentityUpdated.current = key; stocks.selectStock(quote); } }, [market.data, stocks]);
  async function openRecord(record: SessionSummary) {
    const expected = routeRef.current.selection;
    const expectedLocation = locationRef.current.key;
    const sequence = ++recordSequence.current;
    setCreateError("");
    try {
      const detail = await fetchSessionDetail(record.id, { transcriptScope: "none", includeSecondary: false });
      if (detail.id !== record.id || !isFinancialSession(detail, assistant.agentId)) {
        throw new Error(zh ? "这条记录不属于当前金融助手" : "This research belongs to another agent");
      }
      if (!mounted.current || sequence !== recordSequence.current || locationRef.current.key !== expectedLocation || !routeRef.current.matchesSelection(expected)) return;
      client.setQueryData(["finance", "session-binding", assistant.agentId, record.id], detail);
      routeRef.current.openSession(record.id, { replace: false, telemetrySource: "finance_research_history" });
      setDraftRequest(null);
      setCitation(null);
      navigation.showSession(record.id);
      setResearchKind(detail.title.startsWith("主题 ·") ? "topic" : "stock");
    } catch (error) {
      if (mounted.current && sequence === recordSequence.current) {
        setCreateError(error instanceof Error ? error.message : (zh ? "记录加载失败" : "Could not open research"));
      }
    }
  }
  function openBatchRun(runId: string, symbol: string) {
    const ticker = symbol.slice(2);
    stocks.selectStock({ symbol, ticker, name: stocks.watchlist.find((item) => item.symbol === symbol)?.name || ticker, market: symbol.startsWith("hk") ? "港交所" : symbol.startsWith("us") ? "美股" : symbol.startsWith("sh") ? "上交所" : symbol.startsWith("bj") ? "北交所" : "深交所" });
    setTeamSelectedRun(null); setRequestedTeamRunId(runId); setArea("team"); setAsideTab("process");
  }
  function selectStock(stock: StockIdentity) { stocks.selectStock(stock); setSearchMarket(stockMarketCode(stock)); setSearch(""); setDebouncedSearch(""); navigation.update({ area: "workspace", tab: "overview", preparing, selectedReport: null }); setResearchKind("stock"); setCitation(null); }
  function draft(text: string, targetId: string, submit: boolean, depth: ResearchDepth = config.depth) { requestSequence.current += 1; setDraftRequest({ id: requestSequence.current, sessionId: targetId, text, submit, depth, ...(submit ? { modelSelection: currentView?.turnModelSelection ?? null } : {}) }); navigation.showSession(targetId); }
  function configuredPrompt() {
    const text = stockResearchPrompt(market.data?.stock ?? stocks.selected, config.period, config.date, config.scope, config.depth, market.data);
    return config.instructions?.trim() ? `${text}\n\n用户研究档案中的分析要点：\n${config.instructions.trim()}` : text;
  }
  async function newResearch(start = false, custom?: { text: string; title: string; depth?: ResearchDepth }, prepareDraft = false) {
    if (createGate.current) return;
    createGate.current = true; createKey.current ||= crypto.randomUUID();
    const expected = routeRef.current.selection;
    const expectedLocation = locationRef.current.key;
    const text = custom ? (/^请对以下主题开展投资研究|^请研究/.test(custom.text) ? custom.text : `请对以下主题开展投资研究：${custom.title}。分析截至 ${localResearchDate()}。生成完整研究报告。\n\n${custom.text}`) : configuredPrompt();
    setCreating(true); setCreateError("");
    try {
      const result = await createChatSession({ agentId: assistant.agentId, title: custom ? `主题 · ${custom.title}` : `${stocks.selected.name} (${stocks.selected.ticker}) · ${config.period || config.date}` }, createKey.current);
      if (!isFinancialSession(result, assistant.agentId)) throw new Error(zh ? "新会话身份不匹配" : "Session identity mismatch");
      // Reuse the verified create response at the finance entry guard. Otherwise
      // its loading frame would unmount this workspace and discard the draft.
      client.setQueryData(["finance", "session-binding", assistant.agentId, result.id], result);
      void client.invalidateQueries({ queryKey: ["sessions", "finance", assistant.agentId] }); createKey.current = "";
      if (mounted.current && locationRef.current.key === expectedLocation && routeRef.current.replaceIfStillViewing(expected, { kind: "session", sessionId: result.id })) { setResearchKind(custom ? "topic" : "stock"); if (start || prepareDraft) draft(text, result.id, start, custom?.depth); else { setDraftRequest(null); navigation.showSession(result.id); } }
    } catch (error) { if (mounted.current) setCreateError(error instanceof Error ? error.message : (zh ? "创建失败，请重试" : "Could not create research")); }
    finally { createGate.current = false; launchGate.current = false; if (mounted.current) { setCreating(false); setLaunching(false); } }
  }
  function startResearch() {
    if (!readyForResearch || modelGateIssue || busy || createGate.current || launchGate.current || !isValidResearchDate(config.date) || assistant.modelStatus !== "configured_unverified") return;
    launchGate.current = true; setLaunching(true);
    if (preparing || messages.length) { void newResearch(true); return; }
    draft(configuredPrompt(), sessionId, true);
  }
  function startTopicResearch(text: string, title: string, depth: ResearchDepth = "standard") {
    if (!readyForResearch || modelGateIssue || busy || createGate.current || launchGate.current || assistant.modelStatus !== "configured_unverified") return;
    launchGate.current = true; setLaunching(true);
    void newResearch(true, { text, title, depth });
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
  const researchDisabled = !readyForResearch || Boolean(modelGateIssue) || busy || creating || launching || assistant.modelStatus !== "configured_unverified";
  const settings = stocks.workspace.query.data;
  const defaultsApplied = useRef(false);
  useEffect(() => { if (!settings || defaultsApplied.current) return; defaultsApplied.current = true; const profile = settings.profiles.find((row) => row.isDefault); if (profile) { setSelectedProfileId(profile.id); setConfig((current) => ({ ...current, scope: profile.scope, depth: profile.depth, period: profile.period, instructions: profile.instructions })); } }, [settings]);
  const researchConfig = <><FinanceResearchConfig value={config} onChange={setConfig} onStart={startResearch} disabled={researchDisabled || !isValidResearchDate(config.date)} pending={creating || launching} zh={zh} sessionId={nativeReady ? sessionId : undefined} sessionLlmOptions={currentView?.sessionLlmOptions} sessionLlmOptionsLoading={currentView?.sessionLlmOptionsLoading} sessionLlmOptionsError={currentView?.sessionLlmOptionsError} turnModelSelection={currentView?.turnModelSelection} onTurnModelSelectionChange={(selection) => currentView?.onTurnModelSelectionChange?.(sessionId, selection)} agentConfigHref={agentCenterConfigRoute({ agentId: assistant.agentId, returnTo, returnLabel: zh ? "炒股智能体" : "Investment assistant" })} /><FinanceResearchProfiles profiles={settings?.profiles ?? []} ready={Boolean(settings)} value={config} onChange={setConfig} selectedProfileId={selectedProfileId} onSelectProfile={setSelectedProfileId} pending={stocks.pending} onSave={(change) => stocks.workspace.update((current) => ({ profiles: change(current.profiles) }))} zh={zh} /></>;
  const reportCatalog = (casesOnly = false, reviewsOnly = false) => <FinanceReportsCenter key={casesOnly ? "cases" : reviewsOnly ? "reviews" : "reports"} agentId={assistant.agentId} cases={settings?.reviewCases ?? []} onSaveCases={(change) => stocks.workspace.update((current) => ({ reviewCases: change(current.reviewCases) }))} selectedReport={selectedReport} onSelectedReportChange={(selectedReport) => navigation.update({ selectedReport })} onReportContextChange={setReportContext} pending={stocks.pending} onOpenSession={(id) => routeRef.current.openSession(id, { surface: "chat", replace: false, telemetrySource: "finance_exact_report" })} casesOnly={casesOnly} initialKind={reviewsOnly ? "review" : ""} zh={zh} />;
  const activeGroup = financeWorkspaceGroup(area);
  function navigateArea(next: string) { if (next === "team") setRequestedTeamRunId(""); navigation.update({ area: next, ...(next === "workspace" ? { tab: "research" } : {}), preparing: false, selectedReport: null }); }
  const sidebarQuery = sidebarCollection === "archived" ? archivedHistory : sessionQuery ? sessionLookup : history;
  const sidebarSearchPending = sidebarCollection === "recent" && sessionSearch.trim() !== sessionQuery;
  const sidebarRecords = sidebarCollection === "archived"
    ? archivedRecords.filter(row => `${row.title} ${row.taskSummary ?? ""}`.toLocaleLowerCase().includes(sessionSearch.trim().toLocaleLowerCase()))
    : sessionQuery ? (sessionLookup.data?.pages.flatMap(page => page.items) ?? []).filter(row => isFinancialSession(row, assistant.agentId) && !isSessionDeleteTombstoned(row.id) && isResearchSearchResult(row, sessionQuery)) : records;
  const sidebar = <FinanceWorkspaceSidebar records={sidebarRecords} selectedId={sessionId} zh={zh} area={area} collection={sidebarCollection} onCollectionChange={setSidebarCollection} search={sessionSearch} onSearchChange={setSessionSearch}
    loading={sidebarQuery.isPending || sidebarSearchPending} error={sidebarQuery.isError && !sidebarSearchPending} hasMore={Boolean(sidebarQuery.hasNextPage)} morePending={sidebarQuery.isFetchingNextPage}
    onRetry={() => void sidebarQuery.refetch()} onMore={() => void sidebarQuery.fetchNextPage()} creating={creating} onNewResearch={() => { setSidebarCollection("recent"); setSessionSearch(""); setCreateError(""); setResearchKind("stock"); setCitation(null); navigation.update({ area: "workspace", tab: "overview", preparing: true, selectedReport: null, asideTab: "process" }); }}
    configHref={agentCenterConfigRoute({ agentId: assistant.agentId, returnTo, returnLabel: zh ? "炒股智能体" : "Investment assistant" })} onNavigate={navigateArea}
    onOpen={sidebarCollection === "archived" ? record => routeRef.current.openSession(record.id, { surface: "chat", replace: false, telemetrySource: "finance_archived_research" }) : openRecord} onAction={lifecycle.requestAction} actionPending={lifecycle.pending} />;
  const asideHeader = <VTabs value={asideTab} onValueChange={setAsideTab} aria-label={zh ? "研究辅助面板" : "Research inspector"} items={[{ id: "process", label: area === "workspace" && tab === "research" || area === "team" ? (zh ? "研究过程" : "Activity") : (zh ? "当前对象" : "Context") }, { id: "evidence", label: zh ? "引用与资料" : "Sources" }]} />;
  const selectedReportContext = reportContext?.sessionId === selectedReport?.sessionId && reportContext?.turnId === selectedReport?.turnId ? reportContext : null;
  const onOpenResearchChat = () => navigation.update({ area: "workspace", tab: "research", preparing: false, selectedReport: null });
  const nativeProcess = <FinanceResearchProcess view={currentView} activeTurn={activeTurn?.sessionId === sessionId ? activeTurn.turn : null} zh={zh} onEnableMarket={assistant.marketToolStatus === "upgrade_available" ? () => void enableMarketQueries() : undefined} marketPending={upgradingMarket} marketDisabled={marketUpgradeDisabled} onOpenChat={onOpenResearchChat} />;
  const contextTitle = activeGroup.areas.find(item => item.id === area);
  const aside = <div className={styles.workspaceAsideBody}>{asideTab === "process" ? area === "team" ? <FinanceAnalystTeamInspector run={teamSelectedRun?.assistantAgentId === assistant.agentId ? teamSelectedRun : null} zh={zh} onOpenSession={(id) => routeRef.current.openSession(id, { surface: "chat", replace: false, telemetrySource: "finance_team_inspector" })} /> : area === "workspace" && tab === "research" ? nativeProcess : <>
    <FinanceWorkspaceInspector area={area} title={zh ? contextTitle?.zh || activeGroup.zh : contextTitle?.en || activeGroup.en} topicTitle={researchKind === "topic" ? currentView?.title : undefined} stock={stocks.selected} snapshot={market.data} report={selectedReportContext} selection={selectedReport} preparing={preparing} date={config.date} zh={zh} />
    {busy || currentView?.stopping ? <><p className={inspectorStyles.running}>{zh ? "正在运行的研究" : "Running research"} · {currentView?.title}</p>{nativeProcess}</> : null}
  </> : <FinanceReportLibrary assistant={assistant} zh={zh} returnTo={returnTo} citation={citation} />}</div>;
  const stockLookup = <div className={styles.workspaceMarketSearch}>
    <VToolbar wrap={false} ariaLabel={zh ? "查找股票" : "Find a stock"} className={styles.workspaceMarketToolbar}><Search size={15} className={styles.workspaceMarketIcon} /><VSelect className={styles.workspaceMarketSelect} aria-label={zh ? "股票市场" : "Stock market"} selectedKey={searchMarket} options={[{ id: "CN", label: "A股" }, { id: "HK", label: "港股" }, { id: "US", label: "美股" }]} onSelectionChange={key => { setSearchMarket(String(key) as StockMarketCode); setSearch(""); setDebouncedSearch(""); }} /><VInput className={styles.workspaceMarketInput} value={search} onChange={event => setSearch(event.target.value)} maxLength={40} aria-label={zh ? "公司或股票代码" : "Company or ticker"} placeholder={zh ? "名称 / 拼音 / 代码" : "Name / ticker"} /></VToolbar>
    {debouncedSearch ? lookup.isPending ? <VSkeleton className={styles.workspaceMarketLoading} /> : lookup.isError ? <VStateSurface tone="error" density="compact" title={zh ? "股票查询失败" : "Lookup failed"} actions={<VButton onPress={() => void lookup.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : <div className={styles.workspaceMarketResults} aria-label={zh ? "股票搜索结果" : "Stock search results"}>{lookup.data?.length ? lookup.data.map(stock => <VButton key={stock.symbol} variant="ghost" contentLayout="plain" title={`${stock.name} · ${stock.ticker} · ${stock.market}`} className={styles.workspaceSearchButton} onPress={() => selectStock(stock)}><span className={styles.workspaceSearchText}><strong className={styles.workspaceStockName}>{stock.name}</strong><span className={styles.small}>{stock.ticker} · {stock.market}</span></span></VButton>) : <span className={styles.small}>{zh ? "没有匹配股票" : "No matches"}</span>}</div> : null}
  </div>;
  return <FinancialResearchBridgeContext.Provider value={bridge}><FinanceResearchFrame zh={zh} sidebar={sidebar} aside={aside} asideHeader={asideHeader}
    title={area === "workspace" ? preparing ? (zh ? "新研究" : "New research") : currentView?.title || records.find(row => row.id === sessionId)?.title || (zh ? "股票研究" : "Stock research") : zh ? activeGroup.zh : activeGroup.en}
    meta={area === "workspace" && researchKind === "stock" ? stocks.selected.ticker : undefined}
    actions={area === "workspace" ? <><VDropdownMenu align="end" trigger={<VIconButton variant="ghost" className={styles.workspacePaneAction} label={zh ? "股票资料与研究设置" : "Stock data and research settings"} icon={<Settings2 size={15} />} />} items={[{ id: "overview", label: researchKind === "topic" ? (zh ? "研究设置" : "Research settings") : (zh ? "股票概览与研究设置" : "Overview and settings"), onSelect: () => setTab("overview") }, ...(researchKind === "stock" ? [{ id: "news", label: zh ? "新闻公告" : "News", onSelect: () => setTab("news") }, { id: "fundamentals", label: zh ? "财务指标" : "Financials", onSelect: () => setTab("fundamentals") }] : [])]} /><VButton variant="ghost" className={styles.workspacePaneAction} icon={<FileText size={14} />} onPress={() => setTab("report")}>{zh ? "报告" : "Report"}</VButton></> : undefined}>
    {createError || lifecycle.error ? <VStateSurface tone="error" title={zh ? "操作未完成" : "Could not complete action"}><span className={styles.workspaceErrorText}>{createError || lifecycle.error}</span></VStateSurface> : null}
    {nativeReady && modelGateIssue && !currentView?.sessionLlmOptionsLoading && (currentView?.sessionLlmOptionsError || currentView?.sessionLlmOptions) && area !== "workspace" ? <VStateSurface tone="error" density="compact" title={zh ? "研究模型暂不可用" : "Research model unavailable"} actions={<VRouteLinkButton to={agentCenterConfigRoute({ agentId: assistant.agentId, returnTo, returnLabel: zh ? "炒股智能体" : "Investment assistant" })}>{zh ? "检查助手配置" : "Check assistant settings"}</VRouteLinkButton>}>{zh ? "请检查助手默认模型后重新开始研究。" : "Check the assistant's default model before starting research."}</VStateSurface> : null}
    {lifecycle.dialog}
    <VTabs className={styles.workspaceGroupTabs} listClassName={styles.workspaceGroupTabList} value={area} onValueChange={navigateArea} aria-label={zh ? `${activeGroup.zh}功能` : `${activeGroup.en} views`} items={activeGroup.areas.map(item => ({ id: item.id, label: zh ? item.zh : item.en }))} />
    {activeGroup.id === "market" || preparing ? stockLookup : null}
    {stocks.storageError ? <VStateSurface density="compact" tone="error" title={zh ? "自选保存失败" : "Watchlist save failed"}>{stocks.error}</VStateSurface> : null}
    {area === "dashboard" ? <div className={styles.workspaceCollection}><FinanceDashboard assistant={assistant} watchlist={stocks.watchlist} recentResearch={records} onNavigate={setArea} onSelectStock={selectStock} onOpenResearch={openRecord} onRefresh={() => history.refetch().then(() => undefined)} zh={zh} /></div> : area === "workspace" ? <>{tab === "research" ? null : researchKind === "stock" ? <FinanceStockHeader stock={stocks.selected} query={market} starred={stocks.watchlist.some((stock) => stock.symbol === stocks.selected.symbol)} onToggleStar={() => stocks.toggleStock(market.data?.stock ?? stocks.selected)} zh={zh} /> : <div className={styles.workspaceTopicHeader}><strong>{currentView?.title || (zh ? "主题研究" : "Topic research")}</strong><VButton variant="ghost" onPress={() => setArea("general")}>{zh ? "新主题" : "New topic"}</VButton></div>}{tab !== "research" && !preparing ? <div className={styles.workspaceViewTabs}><VTabs value={tab} onValueChange={setTab} aria-label={zh ? "股票研究视图" : "Stock research view"} items={[{ id: "overview", label: researchKind === "topic" ? (zh ? "研究设置" : "Research settings") : (zh ? "股票概览" : "Overview") }, ...(researchKind === "stock" ? [{ id: "news", label: zh ? "新闻公告" : "News" }, { id: "fundamentals", label: zh ? "财务指标" : "Financials" }] : []), { id: "research", label: zh ? "AI 研究" : "AI research" }, { id: "report", label: zh ? "研究报告" : "Report" }]} /></div> : null}
      {tab === "news" || tab === "fundamentals" ? <div className={styles.workspaceCollection}><FinanceMarketExplorer mode={tab} stock={stocks.selected} onSelectStock={selectStock} onResearchPrompt={prepareResearchPrompt} zh={zh} /></div> : tab === "overview" && researchKind === "topic" ? <FinanceGeneralResearch onStart={startTopicResearch} disabled={researchDisabled} pending={creating || launching} zh={zh} /> : tab !== "research" ? <div className={styles.workspaceOverview}>{tab === "overview" ? <>{researchConfig}{!preparing ? <FinanceMarketPanel query={market} period={period} onPeriodChange={setPeriod} zh={zh} /> : null}{!preparing ? <FinanceResearchReport assistantAgentId={assistant.agentId} sessionId={sessionId} report={stockReport} zh={zh} busy={busy} summaryOnly onCitation={focusCitation} onResearch={() => { if (stockReport) setTab("report"); else startResearch(); }} /> : null}</> : <FinanceResearchReport assistantAgentId={assistant.agentId} sessionId={sessionId} report={researchKind === "topic" ? report : stockReport} zh={zh} busy={busy} onCitation={focusCitation} onResearch={researchKind === "topic" ? () => setArea("general") : startResearch} />}</div> : null}
    </> : area === "general" ? <FinanceGeneralResearch onStart={startTopicResearch} disabled={researchDisabled} pending={creating || launching} zh={zh} />
      : area === "screen" ? <div className={styles.workspaceCollection}><FinanceScreenWorkspace agentId={assistant.agentId} currentStock={stocks.selected} onSelectStock={selectStock} onResearchPrompt={(text) => startTopicResearch(text, zh ? "智能选股" : "Stock screening")} disabled={researchDisabled} zh={zh} /></div>
      : area === "team" ? <div className={styles.workspaceCollection}><FinanceAnalystTeam key={`${assistant.agentId}:${requestedTeamRunId}`} requestedRunId={requestedTeamRunId} onBackToBatch={requestedTeamRunId ? () => { setTaskTab("batches"); setArea("tasks"); } : undefined} assistant={assistant} stock={stocks.selected} zh={zh} onSelectedRunChange={setTeamSelectedRun} onOpenSession={(id) => routeRef.current.openSession(id, { surface: "chat", replace: false, telemetrySource: "finance_analyst_session" })} /></div>
      : area === "account" ? <div className={styles.workspaceCollection}><FinancePaperTrading assistant={assistant} stock={stocks.selected} mode="account" zh={zh} onResearchPrompt={(text) => prepareTopicPrompt(text, zh ? "模拟交易复盘" : "Paper trading review")} /></div>
      : area === "review" ? <div ref={reportPaneRef} className={styles.workspaceCollection}><VTabs value={reviewTab} onValueChange={setReviewTab} aria-label={zh ? "交易复盘内容" : "Review content"} items={[{ id: "trades", label: zh ? "模拟交易复盘" : "Paper trade review" }, { id: "history", label: zh ? "复盘历史" : "Review reports" }, { id: "cases", label: zh ? "案例库" : "Case library" }]} />{reviewTab === "trades" ? <FinancePaperTrading assistant={assistant} stock={stocks.selected} mode="review" zh={zh} onResearchPrompt={(text) => prepareTopicPrompt(text, zh ? "模拟交易复盘" : "Paper trading review")} /> : reportCatalog(reviewTab === "cases", true)}</div>
      : area === "portfolio" ? <div className={styles.workspaceCollection}><VTabs value={portfolioSource} onValueChange={setPortfolioSource} aria-label={zh ? "持仓来源" : "Holding source"} items={[{ id: "manual", label: zh ? "手工持仓" : "Manual holdings" }, { id: "paper", label: zh ? "模拟持仓" : "Paper holdings" }]} />{portfolioSource === "manual" ? <FinanceManualPositions positions={settings?.manualPositions ?? []} stock={stocks.selected} onSave={(change) => stocks.workspace.update((current) => ({ manualPositions: change(current.manualPositions) }))} pending={stocks.pending || stocks.workspace.query.isPending || stocks.workspace.query.isError} onSelectStock={selectStock} researchDisabled={researchDisabled} onResearchPrompt={(text) => startTopicResearch(text, zh ? "手工持仓研究" : "Manual portfolio research")} zh={zh} /> : <FinancePortfolioResearch assistant={assistant} zh={zh} onSelectStock={selectStock} onResearchPrompt={(text) => prepareTopicPrompt(text, zh ? "模拟持仓研究" : "Simulated portfolio research")} onOpenAccount={() => setArea("account")} />}</div>
      : area === "memory" || area === "skills" || area === "learning" ? <FinanceKnowledgeCenter assistant={assistant} stock={stocks.selected} mode={area} zh={zh} onResearchPrompt={prepareResearchPrompt} />
      : area === "tasks" ? <><FinanceTaskCenter tab={taskTab} onTabChange={setTaskTab} assistant={assistant} stock={stocks.selected} watchlist={stocks.watchlist} onOpenRun={openBatchRun} moreRecords={history.hasNextPage ? <VButton isPending={history.isFetchingNextPage} onPress={() => void history.fetchNextPage()}>{zh ? "更多记录" : "More records"}</VButton> : null} records={records} selectedId={sessionId} onOpen={openRecord} onRefresh={() => void history.refetch()} loading={history.isFetching} error={history.isError} zh={zh} onAction={lifecycle.requestAction} actionPending={lifecycle.pending} /></>
      : area === "reports" ? <div ref={reportPaneRef} className={styles.workspaceCollection}><h1 className={styles.workspaceCollectionTitle}>{zh ? "报告中心" : "Report center"}</h1><VTabs value={reportCollection} onValueChange={setReportCollection} aria-label={zh ? "研究记录范围" : "Research collection"} items={[{ id: "completed", label: zh ? "已完成报告" : "Completed reports" }, { id: "active", label: zh ? "研究会话" : "Sessions" }, { id: "archived", label: zh ? "已归档" : "Archived" }]} />{reportCollection === "completed" ? reportCatalog() : reportCollection === "archived" ? <><FinanceResearchHistory records={archivedRecords} selectedId="" onOpen={(record) => routeRef.current.openSession(record.id, { surface: "chat", replace: false, telemetrySource: "finance_archived_research" })} zh={zh} archived busy={archivedHistory.isPending} error={archivedHistory.isError} onRetry={() => void archivedHistory.refetch()} onAction={lifecycle.requestAction} actionPending={lifecycle.pending} />{archivedHistory.hasNextPage ? <VButton onPress={() => void archivedHistory.fetchNextPage()} isPending={archivedHistory.isFetchingNextPage}>{zh ? "更多归档" : "More archived"}</VButton> : null}</> : <><FinanceResearchHistory records={reportRecords} selectedId={sessionId} onOpen={openRecord} zh={zh} searchValue={historySearch} onSearchChange={setHistorySearch} busy={reportHistory.isPending || historySearch.trim() !== historyQuery} error={reportHistory.isError && historySearch.trim() === historyQuery} onRetry={() => void reportHistory.refetch()} onAction={lifecycle.requestAction} actionPending={lifecycle.pending} />{reportHistory.hasNextPage && historySearch.trim() === historyQuery ? <VButton onPress={() => void reportHistory.fetchNextPage()} isPending={reportHistory.isFetchingNextPage}>{zh ? "更多记录" : "More history"}</VButton> : null}</>}</div>
      : <div className={styles.workspaceCollection}><h1 className={styles.workspaceCollectionTitle}>{zh ? "自选行情" : "Watchlist"}</h1><FinanceWatchlistTable watchlist={stocks.watchlist} onSelectStock={selectStock} onRemoveStock={stocks.toggleStock} onEditStock={stocks.editStock} pending={stocks.pending} zh={zh} /></div>}
    <div className={area === "workspace" && tab === "research" ? styles.native : "hidden"} aria-hidden={area !== "workspace" || tab !== "research"}>{nativeWorkspace}</div>
  </FinanceResearchFrame></FinancialResearchBridgeContext.Provider>;
}
