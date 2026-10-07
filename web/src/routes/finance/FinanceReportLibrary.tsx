import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { BookOpen, ExternalLink, FileText, RefreshCw } from "lucide-react";
import type { FinancialAssistant } from "../../api/financialAssistant";
import { fetchKnowledgeTrace, listKnowledgeItems } from "../../api/knowledge";
import { fetchKnowledgeItemBody } from "../../api/knowledgeLifecycle";
import type { KnowledgeItemsPayload, KnowledgeTracePayload } from "../../api/types/knowledge";
import { VButton, VInput, VRouteLinkButton, VSkeleton, VStateSurface } from "../../components/vui";
import { agentCenterMemoryRoute } from "../agentCenterRoutes";
import styles from "../FinanceRoute.styles";
import { activeFinancialItems, activeFinancialSources, financialSourceMetadata } from "./financialResearchModel";
import type { ReportCitation } from "./stockResearchModel";

const CITATION_TRACE_BATCH_SIZE = 20;

export function FinanceReportLibrary({ assistant, zh, returnTo, citation = null }: {
  assistant: FinancialAssistant; zh: boolean; returnTo: string; citation?: ReportCitation | null;
}) {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const { agentId, knowledgeBaseId } = assistant;
  const readable = assistant.knowledgeReadable && Boolean(knowledgeBaseId);
  const itemsQuery = useQuery({
    queryKey: ["finance", "library", agentId, knowledgeBaseId],
    queryFn: ({ signal }) => listKnowledgeItems<KnowledgeItemsPayload>(knowledgeBaseId, { agentId, signal }),
    enabled: readable, staleTime: 15_000, retry: false, refetchInterval: 60_000,
  });
  const canonicalItems = useMemo(() => activeFinancialItems(itemsQuery.data?.items ?? [], knowledgeBaseId), [itemsQuery.data?.items, knowledgeBaseId]);
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
    if (!citationKey || citationScan.key !== citationKey || !itemsQuery.data || citationMatch || citationTraceReadFailed
      || citationItems.length >= canonicalItems.length || citationTraces.some((trace) => trace.isPending)) return;
    setCitationScan({ key: citationKey, limit: Math.min(citationLimit + CITATION_TRACE_BATCH_SIZE, canonicalItems.length) });
  }, [citationKey, citationScan.key, itemsQuery.data, citationMatch, citationTraceReadFailed, citationItems.length, canonicalItems.length, citationTraces, citationLimit]);
  useEffect(() => {
    if (matchedItemId && matchedSourceId) { setSearch(""); setSelectedId(matchedItemId); setSourceId(matchedSourceId); }
  }, [matchedItemId, matchedSourceId]);
  const items = canonicalItems.filter((item) =>
    `${item.title} ${item.summary}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const selected = items.find((item) => item.knowledgeItemId === selectedId) ?? items[0];
  const traceQuery = useQuery({
    queryKey: ["finance", "source-trace", agentId, knowledgeBaseId, selected?.knowledgeItemId],
    queryFn: ({ signal }) => fetchKnowledgeTrace<KnowledgeTracePayload>(knowledgeBaseId, selected!.knowledgeItemId, { agentId, signal }),
    enabled: readable && Boolean(selected), staleTime: 15_000, retry: false, refetchInterval: 60_000,
  });
  const sources = selected ? activeFinancialSources(selected, traceQuery.data?.nodes.sourceArtifacts ?? []) : [];
  const source = sources.find((item) => item.sourceArtifactId === sourceId) ?? sources[0];
  const metadata = source ? financialSourceMetadata(source) : null;
  const bodyQuery = useQuery({
    queryKey: ["finance", "source-body", agentId, knowledgeBaseId, selected?.knowledgeItemId, source?.sourceArtifactId],
    queryFn: ({ signal }) => fetchKnowledgeItemBody({
      knowledgeBaseId, knowledgeItemId: selected!.knowledgeItemId, agentId, signal,
      readMode: "source", sourceArtifactId: source!.sourceArtifactId, maxChars: 2400,
    }),
    enabled: readable && Boolean(selected && source), staleTime: 15_000, retry: false, refetchInterval: 60_000,
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
          <VRouteLinkButton to={`${citation.url}${citation.page ? `#page=${citation.page}` : ""}`} target="_blank" rel="noopener noreferrer" reloadDocument className={`${styles.link} ${styles.libraryCitationAction}`}><ExternalLink size={14} aria-hidden="true" />{zh ? "打开原文" : "Open source"}</VRouteLinkButton>
        </div>
        {(citationScanComplete || citationTraceReadFailed) && !matchedItemId ? <span className={`${styles.small} basis-full`}>{citationTraceReadFailed ? (zh ? "部分资料来源读取失败，无法确认库内原文" : "Some source records could not be read") : (zh ? "当前库未找到对应页原文" : "This source page is not in the current library")}</span> : null}
      </div> : null}
      {knowledgeBaseId ? <VRouteLinkButton to={libraryUrl} className={styles.link}>{zh ? "管理财报库" : "Manage library"}</VRouteLinkButton> : null}
      {!readable ? <VStateSurface density="compact" tone="unavailable" title={zh ? "财报库不可读" : "Library unavailable"} /> :
        itemsQuery.isError ? <VStateSurface density="compact" tone="error" title={zh ? "资料加载失败" : "Could not load reports"} actions={<VButton onPress={() => void itemsQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> :
        itemsQuery.isPending ? <div className={styles.skeleton} aria-label={zh ? "正在加载资料" : "Loading reports"}><VSkeleton /><VSkeleton /><VSkeleton /></div> : <>
          <VInput value={search} onChange={(event) => setSearch(event.target.value)} aria-label={zh ? "查找财报资料" : "Find reports"} placeholder={zh ? "查找资料" : "Find reports"} className={styles.input} />
          {items.length === 0 ? <VStateSurface density="compact" tone="empty" title={search ? (zh ? "没有匹配资料" : "No matches") : (zh ? "暂无有效财报" : "No active reports")} /> :
            <div className={styles.sourceList}>{items.map((item) => <VButton key={item.knowledgeItemId} variant="ghost" contentLayout="plain" className={`${styles.sourceButton} ${selected?.knowledgeItemId === item.knowledgeItemId ? styles.selected : ""}`} aria-pressed={selected?.knowledgeItemId === item.knowledgeItemId} onPress={() => { setSelectedId(item.knowledgeItemId); setSourceId(""); }}>
              <span className={styles.rowText}><strong>{item.title}</strong><span className={styles.small}>{item.summary.slice(0, 80)}</span></span>
            </VButton>)}</div>}
          {selected ? <section className={styles.detail} aria-label={zh ? "资料来源" : "Report source"}>
            {traceQuery.isError ? <VStateSurface density="compact" tone="error" title={zh ? "来源加载失败" : "Could not load source"} actions={<VButton onPress={() => void traceQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> :
              traceQuery.isPending ? <VSkeleton /> :
              !source ? <p className={styles.small}>{zh ? "没有有效原文来源" : "No active source available"}</p> : <>
                {sources.length > 1 ? <div className={styles.sourceList}>{sources.map((row) => {
                  const rowMetadata = financialSourceMetadata(row);
                  return <VButton key={row.sourceArtifactId} variant="ghost" contentLayout="plain" className={styles.sourceArtifactButton} aria-pressed={row.sourceArtifactId === source.sourceArtifactId} onPress={() => setSourceId(row.sourceArtifactId)}>
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
                <span className={styles.sectionHeading}>{zh ? "原文摘录" : "Source excerpt"}</span>
                {bodyQuery.isError ? <VStateSurface density="compact" tone="error" title={zh ? "原文加载失败" : "Could not read source"} actions={<VButton onPress={() => void bodyQuery.refetch()}>{zh ? "重试" : "Retry"}</VButton>} /> :
                  bodyQuery.isPending ? <VSkeleton /> :
                  sourceContent ? <><blockquote className={styles.excerpt}>{sourceContent}</blockquote>{body?.hasMore ? <span className={styles.small}>{zh ? "仅显示开头摘录" : "Opening excerpt only"}</span> : null}</> :
                  <p className={styles.small}>{zh ? "原文未提供" : "Source text unavailable"}</p>}
                {metadata?.url ? <VRouteLinkButton to={`${metadata.url}${/^\d+$/.test(metadata.page) ? `#page=${metadata.page}` : ""}`} target="_blank" rel="noopener noreferrer" reloadDocument className={styles.link}><ExternalLink size={14} aria-hidden="true" />{zh ? "查看原始财报" : "Open original report"}</VRouteLinkButton> : null}
              </>}
          </section> : null}
        </>}
    </div>
  );
}
