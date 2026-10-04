import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, History, LayoutDashboard, Plus, Search, Settings2, Star } from "lucide-react";
import { useLocation } from "react-router-dom";
import { createChatSession, fetchSessionDetail, querySessions } from "../../api/chat";
import type { FinancialAssistant } from "../../api/financialAssistant";
import { fetchFinancialStock, financialMarketKeys, searchFinancialStocks, type StockIdentity, type StockPeriod } from "../../api/financialMarket";
import type { AssistantConversationTurn, SessionSummary } from "../../api/types";
import { VButton, VInput, VRouteLinkButton, VSkeleton, VStateSurface, VSurface, VTabs } from "../../components/vui";
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
import { EMPTY_FINANCIAL_MESSAGES, projectStockReport, reportMatchesStock, stockResearchPrompt, type ReportCitation } from "./stockResearchModel";
import { useFinanceWatchlist } from "./useFinanceWatchlist";

export function FinanceResearchWorkspace({ assistant, sessionId, zh }: { assistant: FinancialAssistant; sessionId: string; zh: boolean }) {
  const location = useLocation(), route = useChatRouteSelection();
  const routeRef = useRef(route); routeRef.current = route;
  const client = useQueryClient(), stocks = useFinanceWatchlist(assistant.agentId);
  const [search, setSearch] = useState(""), [debouncedSearch, setDebouncedSearch] = useState("");
  const [period, setPeriod] = useState<StockPeriod>("day");
  const [area, setArea] = useState("workspace"), [tab, setTab] = useState("overview"), [asideTab, setAsideTab] = useState("process");
  const [config, setConfig] = useState<FinanceResearchConfigValue>({ period: "", date: new Date().toLocaleDateString("en-CA"), scope: "comprehensive", depth: "brief" });
  const [citation, setCitation] = useState<ReportCitation | null>(null);
  const [creating, setCreating] = useState(false), [launching, setLaunching] = useState(false), [createError, setCreateError] = useState("");
  const createGate = useRef(false), launchGate = useRef(false), createKey = useRef("");
  const mounted = useRef(false), requestSequence = useRef(0), hydratedSession = useRef("");
  const recordSequence = useRef(0);
  const [view, setView] = useState<FinancialSessionView | null>(null);
  const [activeTurn, setActiveTurn] = useState<{ sessionId: string; turn: AssistantConversationTurn | null } | null>(null);
  const [draftRequest, setDraftRequest] = useState<FinancialDraftRequest | null>(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { const timer = setTimeout(() => setDebouncedSearch(search.trim()), 250); return () => clearTimeout(timer); }, [search]);
  useEffect(() => { setCitation(null); setDraftRequest((request) => request?.sessionId === sessionId ? request : null); setLaunching(false); launchGate.current = false; }, [sessionId]);
  const market = useQuery({ queryKey: financialMarketKeys.stock(stocks.selected.symbol, period), queryFn: ({ signal }) => fetchFinancialStock(stocks.selected.symbol, period, { signal }), staleTime: 30_000, retry: false, refetchInterval: 60_000 });
  const lookup = useQuery({ queryKey: financialMarketKeys.search(debouncedSearch), queryFn: ({ signal }) => searchFinancialStocks(debouncedSearch, { signal }), enabled: Boolean(debouncedSearch), staleTime: 60_000, retry: false });
  const history = useInfiniteQuery({ queryKey: ["sessions", "finance", assistant.agentId], queryFn: ({ signal, pageParam }) => querySessions({ agentId: assistant.agentId, limit: 30, cursor: pageParam || undefined }, { signal }), initialPageParam: "", getNextPageParam: (page) => page.nextCursor || undefined, staleTime: 15_000, retry: false, refetchInterval: 30_000 });
  const records = (history.data?.pages.flatMap((page) => page.items) ?? []).filter((row) => isFinancialSession(row, assistant.agentId));
  const nativeReady = view?.sessionId === sessionId, currentView = nativeReady ? view : null;
  const messages = currentView?.messages ?? EMPTY_FINANCIAL_MESSAGES;
  const report = useMemo(() => projectStockReport(messages), [messages]);
  const stockReport = reportMatchesStock(report, messages, stocks.selected) ? report : null;
  const busy = Boolean(currentView?.busy || currentView?.submitPending);
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
      setTab("report");
    } catch (error) {
      if (mounted.current && sequence === recordSequence.current) {
        setCreateError(error instanceof Error ? error.message : (zh ? "记录加载失败" : "Could not open research"));
      }
    }
  }
  function selectStock(stock: StockIdentity) { stocks.selectStock(stock); setSearch(""); setDebouncedSearch(""); setArea("workspace"); setTab("overview"); setCitation(null); }
  function draft(text: string, targetId: string, submit: boolean) { requestSequence.current += 1; setDraftRequest({ id: requestSequence.current, sessionId: targetId, text, submit }); setArea("workspace"); setTab("research"); setAsideTab("process"); }
  async function newResearch(start = false) {
    if (createGate.current) return;
    createGate.current = true; createKey.current ||= crypto.randomUUID();
    const expected = routeRef.current.selection;
    const text = stockResearchPrompt(market.data?.stock ?? stocks.selected, config.period, config.date, config.scope, config.depth, market.data);
    setCreating(true); setCreateError("");
    try {
      const result = await createChatSession({ agentId: assistant.agentId, title: `${stocks.selected.name} (${stocks.selected.ticker}) · ${config.period || config.date}` }, createKey.current);
      if (!isFinancialSession(result, assistant.agentId)) throw new Error(zh ? "新会话身份不匹配" : "Session identity mismatch");
      // Reuse the verified create response at the finance entry guard. Otherwise
      // its loading frame would unmount this workspace and discard the draft.
      client.setQueryData(["finance", "session-binding", assistant.agentId, result.id], result);
      void client.invalidateQueries({ queryKey: ["sessions", "finance", assistant.agentId] }); createKey.current = "";
      if (mounted.current && routeRef.current.replaceIfStillViewing(expected, { kind: "session", sessionId: result.id })) { if (start) draft(text, result.id, true); else { setDraftRequest(null); setArea("workspace"); setTab("research"); } }
    } catch (error) { if (mounted.current) setCreateError(error instanceof Error ? error.message : (zh ? "创建失败，请重试" : "Could not create research")); }
    finally { createGate.current = false; launchGate.current = false; if (mounted.current) { setCreating(false); setLaunching(false); } }
  }
  function startResearch() {
    if (!readyForResearch || busy || createGate.current || launchGate.current || !config.date || assistant.modelStatus !== "configured_unverified") return;
    launchGate.current = true; setLaunching(true);
    if (messages.length) { void newResearch(true); return; }
    draft(stockResearchPrompt(market.data?.stock ?? stocks.selected, config.period, config.date, config.scope, config.depth, market.data), sessionId, true);
  }
  function focusCitation(next: ReportCitation) { setCitation(next); setAsideTab("evidence"); }
  const researchConfig = <FinanceResearchConfig value={config} onChange={setConfig} onStart={startResearch} disabled={!readyForResearch || busy || creating || launching || !config.date || assistant.modelStatus !== "configured_unverified"} pending={creating || launching} zh={zh} />;
  function historyContent(compact = true) { return history.isError ? <VStateSurface density="compact" tone="error" title={zh ? "记录加载失败" : "History unavailable"} actions={<VButton onPress={() => void history.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : history.isPending ? <div className="grid gap-4"><VSkeleton /><VSkeleton /></div> : <FinanceResearchHistory records={records} selectedId={sessionId} onOpen={openRecord} zh={zh} compact={compact} />; }
  const sidebar = <div className={styles.rail}>
    <nav className="grid gap-1" aria-label={zh ? "股票研究导航" : "Stock research navigation"}>{[{ id: "workspace", label: zh ? "研究工作台" : "Research workspace", icon: <LayoutDashboard size={15} /> }, { id: "watchlist", label: zh ? "自选股票" : "Watchlist", icon: <Star size={15} /> }, { id: "reports", label: zh ? "报告中心" : "Reports", icon: <FileText size={15} /> }].map((item) => <VButton key={item.id} variant="ghost" className={`!justify-start !w-full ${area === item.id ? "!bg-[color-mix(in_srgb,var(--accent-cool)_9%,transparent)] !text-[var(--accent-cool)]" : ""}`} icon={item.icon} aria-pressed={area === item.id} onPress={() => setArea(item.id)}>{item.label}</VButton>)}</nav>
    <VButton variant="secondary" className={styles.newButton} icon={<Plus size={15} />} isDisabled={creating} onPress={() => void newResearch()}>{creating ? (zh ? "创建中" : "Creating") : (zh ? "新研究" : "New research")}</VButton>
    <div className="grid gap-2"><span className={styles.sectionHeading}><Search size={14} />{zh ? "查找股票" : "Find a stock"}</span><VInput value={search} onChange={(event) => setSearch(event.target.value)} maxLength={40} aria-label={zh ? "公司或股票代码" : "Company or ticker"} placeholder={zh ? "名称 / 拼音 / 代码" : "Name / ticker"} />
      {debouncedSearch ? lookup.isPending ? <VSkeleton /> : lookup.isError ? <VStateSurface tone="error" density="compact" title={zh ? "股票查询失败" : "Lookup failed"} actions={<VButton onPress={() => void lookup.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> : <div className="grid gap-1" aria-label={zh ? "股票搜索结果" : "Stock search results"}>{lookup.data?.length ? lookup.data.map((stock) => <VButton key={stock.symbol} variant="ghost" className="!justify-start !h-auto !py-2 !w-full" onPress={() => selectStock(stock)}><span className="grid gap-1 text-left"><strong className="text-xs">{stock.name}</strong><span className={styles.small}>{stock.ticker} · {stock.market}</span></span></VButton>) : <span className={styles.small}>{zh ? "没有匹配股票" : "No matches"}</span>}</div> : null}
    </div>
    <div className="grid gap-2"><span className={styles.sectionHeading}><span>{zh ? "我的自选" : "Following"}</span><span>{stocks.watchlist.length}</span></span>{stocks.watchlist.length ? stocks.watchlist.map((stock) => <VButton key={stock.symbol} variant="ghost" className="!justify-start !w-full !h-auto !py-2" aria-pressed={stocks.selected.symbol === stock.symbol} onPress={() => selectStock(stock)}><span className="flex w-full justify-between gap-2 text-xs"><span className="truncate">{stock.name}</span><span className="font-mono text-[var(--fg-tertiary)]">{stock.ticker}</span></span></VButton>) : <span className={styles.small}>{zh ? "点击股票右上角 ☆ 添加" : "Use ☆ to follow a stock"}</span>}{stocks.storageError ? <span className="text-xs text-[var(--state-warning)]">{zh ? "自选未保存，关闭页面后会丢失" : "Watchlist could not be saved"}</span> : null}</div>
    <div className="grid gap-2 border-t border-[var(--vui-border-subtle)] pt-4"><div className={styles.sectionHeading}><span>{zh ? "最近研究" : "Recent research"}</span><History size={14} /></div>{historyContent()}{history.hasNextPage ? <VButton variant="ghost" isDisabled={history.isFetchingNextPage} onPress={() => void history.fetchNextPage()}>{zh ? "更多记录" : "More history"}</VButton> : null}</div>
  </div>;
  const aside = <div className="flex min-h-0 h-full flex-col overflow-hidden bg-[var(--vui-surface-row)]"><VTabs value={asideTab} onValueChange={setAsideTab} aria-label={zh ? "研究辅助面板" : "Research inspector"} className="shrink-0 px-3 pt-3" items={[{ id: "process", label: zh ? "研究过程" : "Activity" }, { id: "evidence", label: zh ? "引用与资料" : "Sources" }]} /><div className="flex-1 min-h-0 overflow-y-auto">{asideTab === "process" ? <FinanceResearchProcess view={currentView} activeTurn={activeTurn?.sessionId === sessionId ? activeTurn.turn : null} zh={zh} onOpenChat={() => { setArea("workspace"); setTab("research"); }} /> : <FinanceReportLibrary assistant={assistant} zh={zh} returnTo={returnTo} citation={citation} />}</div></div>;
  return <FinancialResearchBridgeContext.Provider value={bridge}><FinanceResearchFrame zh={zh} sidebar={sidebar} aside={aside} actions={<VRouteLinkButton to={agentCenterConfigRoute({ agentId: assistant.agentId, returnTo, returnLabel: zh ? "炒股智能体" : "Investment assistant" })} aria-label={zh ? "模型与助手配置" : "Assistant settings"}><Settings2 size={16} /></VRouteLinkButton>}>
    {createError ? <VStateSurface tone="error" title={zh ? "操作未完成" : "Could not complete action"}><span className="block break-words">{createError}</span></VStateSurface> : null}
    {area === "workspace" ? <><FinanceStockHeader stock={stocks.selected} query={market} starred={stocks.watchlist.some((stock) => stock.symbol === stocks.selected.symbol)} onToggleStar={() => stocks.toggleStock(market.data?.stock ?? stocks.selected)} zh={zh} /><div className="shrink-0 px-6 py-3 border-b border-[var(--vui-border-subtle)]"><VTabs value={tab} onValueChange={setTab} aria-label={zh ? "股票研究视图" : "Stock research view"} items={[{ id: "overview", label: zh ? "股票概览" : "Overview" }, { id: "research", label: zh ? "AI 研究" : "AI research" }, { id: "report", label: zh ? "研究报告" : "Report" }]} /></div>
      {tab !== "research" ? <div className="min-h-0 flex-1 overflow-y-auto p-6 grid content-start gap-5">{tab === "overview" ? <><FinanceMarketPanel query={market} period={period} onPeriodChange={setPeriod} zh={zh} />{researchConfig}<FinanceResearchReport report={stockReport} zh={zh} busy={busy} summaryOnly onCitation={focusCitation} onResearch={() => { if (stockReport) setTab("report"); else startResearch(); }} /></> : <FinanceResearchReport report={stockReport} zh={zh} busy={busy} onCitation={focusCitation} onResearch={startResearch} />}</div> : <div className="px-5 pt-3 shrink-0 flex items-center justify-between gap-3 text-xs text-[var(--fg-tertiary)]"><span>{currentView?.title || (zh ? "研究助手" : "Research assistant")}</span><VButton variant="ghost" onPress={() => setTab("overview")}>{zh ? "研究设置" : "Research settings"}</VButton></div>}
    </> : area === "reports" ? <div className="min-h-0 flex-1 overflow-auto p-6"><h1 className="text-lg font-semibold mt-0 mb-5">{zh ? "报告中心" : "Report center"}</h1>{historyContent(false)}{history.hasNextPage ? <VButton onPress={() => void history.fetchNextPage()} isDisabled={history.isFetchingNextPage}>{zh ? "更多记录" : "More history"}</VButton> : null}</div> : <div className="min-h-0 flex-1 overflow-auto p-6"><h1 className="text-lg font-semibold mt-0 mb-5">{zh ? "自选股票" : "Watchlist"}</h1>{stocks.watchlist.length ? <div className="grid gap-2">{stocks.watchlist.map((stock) => <VSurface key={stock.symbol} tone="panel" className="flex items-center justify-between gap-4 border border-[var(--vui-border-subtle)]"><div className="flex items-center gap-4"><strong className="text-sm">{stock.name}</strong><span className={styles.small}>{stock.ticker} · {stock.market}</span></div><div className="flex gap-2"><VButton onPress={() => selectStock(stock)}>{zh ? "查看股票" : "Open stock"}</VButton><VButton variant="ghost" onPress={() => stocks.toggleStock(stock)}>{zh ? "移除自选" : "Unfollow"}</VButton></div></VSurface>)}</div> : <VStateSurface tone="empty" title={zh ? "暂无自选股票" : "No followed stocks"} actions={<VButton onPress={() => setArea("workspace")}>{zh ? "浏览股票" : "Browse stocks"}</VButton>} />}</div>}
    <div className={area === "workspace" && tab === "research" ? styles.native : "hidden"} aria-hidden={area !== "workspace" || tab !== "research"}>{nativeWorkspace}</div>
  </FinanceResearchFrame></FinancialResearchBridgeContext.Provider>;
}
