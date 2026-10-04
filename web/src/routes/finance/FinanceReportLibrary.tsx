import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ExternalLink, RefreshCw } from "lucide-react";
import type { FinancialAssistant } from "../../api/financialAssistant";
import { fetchKnowledgeTrace, listKnowledgeItems } from "../../api/knowledge";
import { fetchKnowledgeItemBody } from "../../api/knowledgeLifecycle";
import type { KnowledgeItemsPayload, KnowledgeTracePayload } from "../../api/types/knowledge";
import { VButton, VInput, VRouteLinkButton, VSkeleton, VStateSurface } from "../../components/vui";
import { agentCenterMemoryRoute } from "../agentCenterRoutes";
import styles from "../FinanceRoute.styles";
import { activeFinancialItems, activeFinancialSources, financialSourceMetadata } from "./financialResearchModel";

export function FinanceReportLibrary({ assistant, zh, returnTo }: {
  assistant: FinancialAssistant; zh: boolean; returnTo: string;
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
  const items = activeFinancialItems(itemsQuery.data?.items ?? [], knowledgeBaseId).filter((item) =>
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
        <span className="flex items-center gap-2"><BookOpen size={15} aria-hidden="true" />{zh ? "财报资料" : "Report library"}</span>
        <VButton variant="ghost" aria-label={zh ? "刷新财报资料" : "Refresh reports"} isDisabled={!readable || itemsQuery.isFetching} onPress={() => {
          void itemsQuery.refetch();
          if (selected) void traceQuery.refetch();
          if (source) void bodyQuery.refetch();
        }}><RefreshCw size={14} /></VButton>
      </div>
      <p className={styles.small}>{zh ? "库内资料 · 本次引用见研究回答" : "Library sources · citations appear in the answer"}</p>
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
                {sources.length > 1 ? <div className={styles.sourceList}>{sources.map((row) => <VButton key={row.sourceArtifactId} variant="ghost" className={styles.link} aria-pressed={row.sourceArtifactId === source.sourceArtifactId} onPress={() => setSourceId(row.sourceArtifactId)}>{row.title}</VButton>)}</div> : null}
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
                {metadata?.url ? <VRouteLinkButton to={metadata.url} target="_blank" rel="noopener noreferrer" reloadDocument className={styles.link}><ExternalLink size={14} aria-hidden="true" />{zh ? "查看原始财报" : "Open original report"}</VRouteLinkButton> : null}
              </>}
          </section> : null}
        </>}
    </div>
  );
}
