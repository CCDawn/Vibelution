import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { BookOpen, ExternalLink, FileText, RefreshCw } from "lucide-react";
import type { FinancialAssistant } from "../../api/financialAssistant";
import { fetchKnowledgeTrace, listKnowledgeItems } from "../../api/knowledge";
import { fetchKnowledgeItemBody } from "../../api/knowledgeLifecycle";
import type { KnowledgeItemsPayload, KnowledgeTracePayload } from "../../api/types/knowledge";
import { VButton, VInput, VRouteLinkButton, VSkeleton, VStateSurface, VSelect } from "../../components/vui";
import { agentCenterMemoryRoute } from "../agentCenterRoutes";
import styles from "../FinanceRoute.styles";
import { activeFinancialItems, activeFinancialSources, financialSourceMetadata } from "./financialResearchModel";
import type { StockIdentity } from "../../api/financialMarket";
import type { ReportCitation } from "./stockResearchModel";
import libraryStyles from "./FinanceReportLibrary.styles";
import { FinanceEvidenceImport } from "./FinanceEvidenceImport";

const CITATION_TRACE_BATCH_SIZE = 20;

type SourceIdentity = { company: string; ticker: string };
type ScopeScanState = { key: string; limit: number; scannedThrough: number; identities: Record<string, SourceIdentity[]>; failedItemIds: string[] };

function stockScopeKey(stock: StockIdentity | undefined) {
  return stock ? [stock.symbol, stock.ticker, stock.name].join("\u0000") : "";
}

function itemSourceIdentities(item: Parameters<typeof activeFinancialSources>[0], sources: Parameters<typeof activeFinancialSources>[1]) {
  const identities = new Map<string, SourceIdentity>();
  for (const source of activeFinancialSources(item, sources)) {
    const metadata = financialSourceMetadata(source);
    if (!metadata.company && !metadata.ticker) continue;
    identities.set(`${metadata.company.toLocaleLowerCase()}\u0000${metadata.ticker.toLocaleUpperCase()}`, {
      company: metadata.company,
      ticker: metadata.ticker,
    });
  }
  return [...identities.values()];
}

function normalizedIdentity(value: string) {
  return value.trim().replace(/\s+/g, "").toLocaleLowerCase();
}

function sourceIdentityMatchesStock(identity: SourceIdentity, stock: StockIdentity) {
  const tickerMatches = Boolean(identity.ticker) && identity.ticker.trim().toLocaleUpperCase() === stock.ticker.trim().toLocaleUpperCase();
  const companyMatches = Boolean(identity.company) && normalizedIdentity(identity.company) === normalizedIdentity(stock.name);
  // Reviewed A-share codes are stable identities; legal names and market
  // abbreviations routinely differ. A different code must never match by name.
  return identity.ticker ? tickerMatches : companyMatches;
}

function sourceIdentityLabel(identities: SourceIdentity[], zh: boolean) {
  if (!identities.length) return zh ? "公司 / 代码未提供" : "Company / ticker unavailable";
  return identities.map((identity) => [identity.company, identity.ticker].filter(Boolean).join(" · ")
    || (zh ? "公司 / 代码未提供" : "Company / ticker unavailable")).join("；");
}

export function FinanceReportLibrary({ assistant, zh, returnTo, citation = null, currentStock }: {
  assistant: FinancialAssistant; zh: boolean; returnTo: string; citation?: ReportCitation | null; currentStock?: StockIdentity;
}) {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const { agentId, knowledgeBaseId } = assistant;
  const stockKey = stockScopeKey(currentStock);
  const [selectionScope, setSelectionScope] = useState({ agentId, knowledgeBaseId, citation, stockKey });
  const [manualBrowse, setManualBrowse] = useState(false);
  const [showAllDocuments, setShowAllDocuments] = useState(false);
  const [scopeScan, setScopeScan] = useState<ScopeScanState>(() => ({ key: stockKey, limit: CITATION_TRACE_BATCH_SIZE, scannedThrough: 0, identities: {}, failedItemIds: [] }));
  const [excerptOpen, setExcerptOpen] = useState(false);
  if (selectionScope.agentId !== agentId || selectionScope.knowledgeBaseId !== knowledgeBaseId || selectionScope.citation !== citation || selectionScope.stockKey !== stockKey) {
    setSelectionScope({ agentId, knowledgeBaseId, citation, stockKey });
    setSearch("");
    setSelectedId("");
    setSourceId("");
    setManualBrowse(false);
    setShowAllDocuments(false);
    setExcerptOpen(false);
    setScopeScan({ key: stockKey, limit: CITATION_TRACE_BATCH_SIZE, scannedThrough: 0, identities: {}, failedItemIds: [] });
  }
  const readable = assistant.knowledgeReadable && Boolean(knowledgeBaseId);
  const itemsQuery = useQuery({
    queryKey: ["finance", "library", agentId, knowledgeBaseId],
    queryFn: ({ signal }) => listKnowledgeItems<KnowledgeItemsPayload>(knowledgeBaseId, { agentId, signal }),
    enabled: readable, staleTime: 15_000, retry: false, refetchInterval: 60_000,
  });
  const canonicalItems = useMemo(() => activeFinancialItems(itemsQuery.data?.items ?? [], knowledgeBaseId), [itemsQuery.data?.items, knowledgeBaseId]);
  const activeScopeScan = scopeScan.key === stockKey ? scopeScan : {
    key: stockKey, limit: CITATION_TRACE_BATCH_SIZE, scannedThrough: 0, identities: {}, failedItemIds: [],
  } satisfies ScopeScanState;
  const scopeItems = currentStock ? canonicalItems.slice(0, activeScopeScan.limit) : [];
  const scopeTraces = useQueries({ queries: scopeItems.map((item) => ({
    queryKey: ["finance", "source-trace", agentId, knowledgeBaseId, item.knowledgeItemId],
    queryFn: ({ signal }: { signal: AbortSignal }) => fetchKnowledgeTrace<KnowledgeTracePayload>(knowledgeBaseId, item.knowledgeItemId, { agentId, signal }),
    enabled: readable && Boolean(currentStock), staleTime: 60_000, retry: false,
  })) });
  useEffect(() => {
    if (!currentStock || !itemsQuery.data || scopeScan.key !== stockKey || activeScopeScan.scannedThrough >= scopeItems.length
      || scopeTraces.some((trace) => trace.isPending)) return;
    setScopeScan((current) => {
      const active = current.key === stockKey ? current : {
        key: stockKey, limit: CITATION_TRACE_BATCH_SIZE, scannedThrough: 0, identities: {}, failedItemIds: [],
      } satisfies ScopeScanState;
      if (active.scannedThrough >= scopeItems.length) return current;
      const identities = { ...active.identities };
      const failedItemIds = new Set(active.failedItemIds);
      scopeItems.slice(active.scannedThrough).forEach((item, offset) => {
        const trace = scopeTraces[active.scannedThrough + offset];
        if (trace?.isError) failedItemIds.add(item.knowledgeItemId);
        else if (trace?.data) identities[item.knowledgeItemId] = itemSourceIdentities(item, trace.data.nodes.sourceArtifacts ?? []);
      });
      const scannedThrough = scopeItems.length;
      return {
        key: stockKey,
        limit: scannedThrough + CITATION_TRACE_BATCH_SIZE,
        scannedThrough,
        identities,
        failedItemIds: [...failedItemIds],
      };
    });
  }, [currentStock, itemsQuery.data, scopeScan.key, stockKey, activeScopeScan.scannedThrough, scopeItems, scopeTraces, canonicalItems.length]);
  const scopeComplete = !currentStock || (Boolean(itemsQuery.data) && activeScopeScan.scannedThrough >= canonicalItems.length);
  const scopeReadFailed = activeScopeScan.failedItemIds.length > 0;
  const scopeMatchedIds = useMemo(() => new Set(Object.entries(activeScopeScan.identities)
    .filter(([, identities]) => identities.some((identity) => currentStock && sourceIdentityMatchesStock(identity, currentStock)))
    .map(([itemId]) => itemId)), [activeScopeScan.identities, currentStock]);
  const scopedCanonicalItems = currentStock && !showAllDocuments
    ? canonicalItems.filter((item) => scopeMatchedIds.has(item.knowledgeItemId)) : canonicalItems;
  const citationKey = citation ? `${agentId}\u0000${knowledgeBaseId}\u0000${citation.url}\u0000${citation.page}` : "";
  const [citationScan, setCitationScan] = useState({ key: "", limit: CITATION_TRACE_BATCH_SIZE });
  const citationLimit = citationScan.key === citationKey ? citationScan.limit : CITATION_TRACE_BATCH_SIZE;
  const citationItems = canonicalItems.slice(0, citationLimit);
  const citationTraces = useQueries({ queries: citationItems.map((item) => ({
    queryKey: ["finance", "source-trace", agentId, knowledgeBaseId, item.knowledgeItemId],
    queryFn: ({ signal }: { signal: AbortSignal }) => fetchKnowledgeTrace<KnowledgeTracePayload>(knowledgeBaseId, item.knowledgeItemId, { agentId, signal }),
    enabled: readable && Boolean(citation), staleTime: 60_000, retry: false,
  })) });
  let citationMatch: { itemId: string; sourceId: string } | null = null;
  for (const [index, trace] of citationTraces.entries()) {
    if (!citation) break;
    const matched = activeFinancialSources(citationItems[index], trace.data?.nodes.sourceArtifacts ?? []).find((source) => {
      const metadata = financialSourceMetadata(source);
      return metadata.url === citation.url && (!citation.page || metadata.page === citation.page);
    });
    if (matched) {
      citationMatch = { itemId: citationItems[index].knowledgeItemId, sourceId: matched.sourceArtifactId };
      break;
    }
  }
  const matchedItemId = citationMatch?.itemId;
  const matchedSourceId = citationMatch?.sourceId;
  const citationScanComplete = Boolean(itemsQuery.data) && citationItems.length >= canonicalItems.length
    && !citationTraces.some((trace) => trace.isPending);
  const citationTraceReadFailed = citationTraces.some((trace) => trace.isError);
  useEffect(() => {
    if (!citationKey || citationScan.key === citationKey) return;
    setCitationScan({ key: citationKey, limit: CITATION_TRACE_BATCH_SIZE });
  }, [citationKey, citationScan.key]);
  useEffect(() => {
    if (!citationKey || citationScan.key !== citationKey || !itemsQuery.data || citationMatch
      || citationItems.length >= canonicalItems.length || citationTraces.some((trace) => trace.isPending)) return;
    setCitationScan({ key: citationKey, limit: Math.min(citationLimit + CITATION_TRACE_BATCH_SIZE, canonicalItems.length) });
  }, [citationKey, citationScan.key, itemsQuery.data, citationMatch, citationItems.length, canonicalItems.length, citationTraces, citationLimit]);
  const items = scopedCanonicalItems.filter((item) =>
    `${item.title} ${item.summary}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const activeSelectionId = citation && !manualBrowse ? matchedItemId : selectedId;
  const selected = activeSelectionId
    ? items.find((item) => item.knowledgeItemId === activeSelectionId) ?? (manualBrowse || !citation ? items[0] : undefined)
    : citation && !manualBrowse ? undefined : items[0];
  const traceQuery = useQuery({
    queryKey: ["finance", "source-trace", agentId, knowledgeBaseId, selected?.knowledgeItemId],
    queryFn: ({ signal }) => fetchKnowledgeTrace<KnowledgeTracePayload>(knowledgeBaseId, selected!.knowledgeItemId, { agentId, signal }),
    enabled: readable && Boolean(selected), staleTime: 15_000, retry: false, refetchInterval: 60_000,
  });
  const sources = selected ? activeFinancialSources(selected, traceQuery.data?.nodes.sourceArtifacts ?? []) : [];
  const activeSourceId = citation && !manualBrowse ? matchedSourceId : sourceId;
  const source = citation && !manualBrowse
    ? sources.find((item) => item.sourceArtifactId === activeSourceId)
    : sources.find((item) => item.sourceArtifactId === activeSourceId) ?? sources[0];
  const metadata = source ? financialSourceMetadata(source) : null;
  const bodyQuery = useQuery({
    queryKey: ["finance", "source-body", agentId, knowledgeBaseId, selected?.knowledgeItemId, source?.sourceArtifactId],
    queryFn: ({ signal }) => fetchKnowledgeItemBody({
      knowledgeBaseId, knowledgeItemId: selected!.knowledgeItemId, agentId, signal,
      readMode: "source", sourceArtifactId: source!.sourceArtifactId, maxChars: 2400,
    }),
    enabled: readable && Boolean(selected && source && excerptOpen), staleTime: 15_000, retry: false, refetchInterval: 60_000,
  });
  const body = bodyQuery.data;
  const sourceContent = body && body.knowledgeBaseId === knowledgeBaseId
    && body.knowledgeItemId === selected?.knowledgeItemId
    && body.sourceArtifactIds.includes(source?.sourceArtifactId ?? "")
    && body.sourceBodyStatus === "source_body_available" ? body.content : "";
  const libraryUrl = agentCenterMemoryRoute({ agentId, knowledgeBaseId, view: "knowledge", returnTo, returnLabel: zh ? "炒股智能体" : "Investment assistant" });

  return (
    <div className={styles.aside} data-finance-report-library>
      <div className={styles.sectionHeading}>
        <span className={styles.libraryHeading}><BookOpen size={15} aria-hidden="true" />{zh ? "财报资料" : "Report library"}</span>
        <VButton variant="ghost" aria-label={zh ? "刷新财报资料" : "Refresh reports"} isDisabled={!readable || itemsQuery.isFetching} onPress={() => {
          void itemsQuery.refetch();
          setScopeScan({ key: stockKey, limit: CITATION_TRACE_BATCH_SIZE, scannedThrough: 0, identities: {}, failedItemIds: [] });
          scopeTraces.filter((trace) => trace.isError).forEach((trace) => { void trace.refetch(); });
          citationTraces.filter((trace) => trace.isError).forEach((trace) => { void trace.refetch(); });
          if (selected) void traceQuery.refetch();
          if (source) void bodyQuery.refetch();
        }}><RefreshCw size={14} /></VButton>
      </div>
      {citation ? <div className={styles.libraryCitation}>
        <div className={styles.libraryCitationRow}>
          <strong className={styles.libraryCitationTitle} title={`${zh ? "当前引用" : "Selected citation"} · ${citation.label}`}>
            <FileText size={14} aria-hidden="true" /><span className="min-w-0 truncate">{zh ? "当前引用" : "Selected citation"} · {citation.label}</span>
          </strong>
          <VRouteLinkButton to={`${citation.url}${citation.page ? `#page=${citation.page}` : ""}`} target="_blank" rel="noopener noreferrer" reloadDocument icon={<ExternalLink size={14} aria-hidden="true" />} className={`${styles.link} ${styles.libraryCitationAction}`}>{zh ? "打开原文" : "Open source"}</VRouteLinkButton>
        </div>
        {citationScanComplete && !matchedItemId ? <span className={`${styles.small} basis-full`}>{citationTraceReadFailed ? (zh ? "部分资料来源读取失败，无法确认库内原文" : "Some source records could not be read") : (zh ? "当前库未找到对应页原文" : "This source page is not in the current library")}</span> : null}
      </div> : null}
      {knowledgeBaseId ? <div className="flex min-w-0 items-center gap-2"><FinanceEvidenceImport key={`${agentId}:${stockKey}`} agentId={agentId} knowledgeBaseId={knowledgeBaseId} stock={currentStock} sourceUrl={citation?.url} zh={zh} /><VRouteLinkButton to={libraryUrl} className={styles.link}>{zh ? "管理财报库" : "Manage library"}</VRouteLinkButton></div> : null}
      {!readable ? <VStateSurface density="compact" tone="unavailable" title={zh ? "财报库不可读" : "Library unavailable"} /> :
        itemsQuery.isError ? <VStateSurface density="compact" tone="error" title={zh ? "资料加载失败" : "Could not load reports"} actions={<VButton onPress={() => void itemsQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> :
        itemsQuery.isPending ? <div className={styles.skeleton} aria-label={zh ? "正在加载资料" : "Loading reports"}><VSkeleton /><VSkeleton /><VSkeleton /></div> : <>
          {currentStock ? <div className={libraryStyles.scope}>
            <label className={libraryStyles.scopeLabel}>{zh ? "资料范围" : "Material scope"}<VSelect
              className={libraryStyles.scopeSelect}
              aria-label={zh ? "资料范围" : "Material scope"}
              selectedKey={showAllDocuments ? "all" : "current"}
              options={[{ id: "current", label: zh ? `当前股票 · ${currentStock.name} ${currentStock.ticker}` : `Current stock · ${currentStock.name} ${currentStock.ticker}` }, { id: "all", label: zh ? "全部资料" : "All materials" }]}
              onSelectionChange={(key) => {
                const showAll = String(key) === "all";
                setShowAllDocuments(showAll);
                setManualBrowse(showAll);
                setSelectedId("");
                setSourceId("");
                setExcerptOpen(false);
              }}
            /></label>
            {showAllDocuments ? <p className={libraryStyles.scopeNotice}>{zh ? "全部资料仅供查阅；跨公司资料不会自动作为当前股票引用。" : "All materials are for browsing; other-company documents are not added as current-stock citations."}</p> : null}
            {!scopeComplete ? <div className={styles.skeleton} aria-label={zh ? "正在核对资料公司与代码" : "Checking material company and ticker"}><VSkeleton /></div> : null}
            {scopeComplete && scopeReadFailed ? <p role="status" className={libraryStyles.scopeNotice}>{zh ? "部分资料来源未能读取，当前股票范围可能不完整；未核实资料已排除。" : "Some source records could not be read. The current-stock scope may be incomplete; unverified materials are excluded."}</p> : null}
          </div> : null}
          <VInput value={search} onChange={(event) => setSearch(event.target.value)} aria-label={zh ? "查找财报资料" : "Find reports"} placeholder={zh ? "查找资料" : "Find reports"} className={styles.input} />
          {!scopeComplete ? null : items.length === 0 ? <VStateSurface density="compact" tone="empty" title={search ? (zh ? "没有匹配资料" : "No matches") : currentStock && !showAllDocuments ? (zh ? `暂无 ${currentStock.name}（${currentStock.ticker}）的匹配资料` : `No materials matched ${currentStock.name} (${currentStock.ticker})`) : (zh ? "暂无有效财报" : "No active reports")} /> :
            <div className={styles.sourceList}>{items.map((item) => <VButton key={item.knowledgeItemId} variant="ghost" contentLayout="plain" className={`${styles.sourceButton} ${selected?.knowledgeItemId === item.knowledgeItemId ? styles.selected : ""}`} aria-pressed={selected?.knowledgeItemId === item.knowledgeItemId} onPress={() => { setManualBrowse(true); setSelectedId(item.knowledgeItemId); setSourceId(""); setExcerptOpen(false); }}>
              <span className={styles.rowText}><strong>{item.title}</strong>{currentStock && showAllDocuments ? <span className={libraryStyles.identity}>{sourceIdentityLabel(activeScopeScan.identities[item.knowledgeItemId] ?? [], zh)}</span> : null}{item.summary && item.summary !== "Financial PDF excerpt awaiting source review." ? <span className={styles.small}>{item.summary.slice(0, 80)}</span> : null}</span>
            </VButton>)}</div>}
          {selected ? <section className={styles.detail} aria-label={zh ? "资料来源" : "Report source"}>
            {traceQuery.isError ? <VStateSurface density="compact" tone="error" title={zh ? "来源加载失败" : "Could not load source"} actions={<VButton onPress={() => void traceQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> :
              traceQuery.isPending ? <VSkeleton /> :
              !source ? <p className={styles.small}>{zh ? "没有有效原文来源" : "No active source available"}</p> : <>
                {sources.length > 1 ? <div className={styles.sourceList}>{sources.map((row) => {
                  const rowMetadata = financialSourceMetadata(row);
                  return <VButton key={row.sourceArtifactId} variant="ghost" contentLayout="plain" className={styles.sourceArtifactButton} aria-pressed={row.sourceArtifactId === source.sourceArtifactId} onPress={() => { setManualBrowse(true); setSelectedId(selected.knowledgeItemId); setSourceId(row.sourceArtifactId); setExcerptOpen(false); }}>
                    <span className={styles.sourceArtifactRow}>
                      <FileText size={14} aria-hidden="true" />
                      <strong title={row.title}>{row.title}</strong>
                      {rowMetadata.page ? <span title={zh ? `第${rowMetadata.page}页` : `Page ${rowMetadata.page}`}>{zh ? `第${rowMetadata.page}页` : `p. ${rowMetadata.page}`}</span> : null}
                    </span>
                  </VButton>;
                })}</div> : null}
                {metadata ? <dl className={styles.facts}>
                  {metadata.company ? <><dt>{zh ? "公司" : "Company"}</dt><dd>{metadata.company}</dd></> : null}
                  {metadata.ticker ? <><dt>{zh ? "代码" : "Ticker"}</dt><dd>{metadata.ticker}</dd></> : null}
                  {metadata.period ? <><dt>{zh ? "报告期" : "Period"}</dt><dd>{metadata.period}</dd></> : null}
                  {metadata.version ? <><dt>{zh ? "版本" : "Version"}</dt><dd>{metadata.version}</dd></> : null}
                  {metadata.page ? <><dt>{zh ? "页码" : "Page"}</dt><dd>{metadata.page}</dd></> : null}
                  {metadata.publishedAt ? <><dt>{zh ? "发布" : "Published"}</dt><dd>{metadata.publishedAt}</dd></> : null}
                </dl> : null}
                {metadata?.url ? <VRouteLinkButton to={`${metadata.url}${/^\d+$/.test(metadata.page) ? `#page=${metadata.page}` : ""}`} target="_blank" rel="noopener noreferrer" reloadDocument icon={<ExternalLink size={14} aria-hidden="true" />} className={styles.link}>{zh ? "查看原始财报" : "Open original report"}</VRouteLinkButton> : null}
                <details className={libraryStyles.excerptDisclosure} open={excerptOpen} onToggle={(event) => setExcerptOpen(event.currentTarget.open)}>
                  <summary className={libraryStyles.excerptSummary}>{zh ? "展开原文摘录" : "Show source excerpt"}</summary>
                  {bodyQuery.isError && <VStateSurface density="compact" tone="error" title={zh ? "原文加载失败" : "Could not read source"} actions={<VButton onPress={() => void bodyQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>} />}
                  {bodyQuery.isPending && <VSkeleton />}
                  {!bodyQuery.isError && !bodyQuery.isPending && (sourceContent
                    ? <><blockquote className={styles.excerpt}>{sourceContent}</blockquote>{body?.hasMore && <span className={styles.small}>{zh ? "仅显示开头摘录" : "Opening excerpt only"}</span>}</>
                    : <p className={styles.small}>{zh ? "原文未提供" : "Source text unavailable"}</p>)}
                </details>
              </>}
          </section> : null}
        </>}
    </div>
  );
}
