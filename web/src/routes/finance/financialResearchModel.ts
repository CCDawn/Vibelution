import type { KnowledgeItem, KnowledgeSourceArtifact } from "../../api/types/knowledge";
import type { SessionSummary } from "../../api/types";
import { isSessionDeleteTombstoned } from "../sessionDeleteTombstone";

export type FinancialResearchKind = "financial" | "events" | "risk";

export function financialResearchPrompt(company: string, period: string, kind: FinancialResearchKind, zh: boolean) {
  const target = company.trim();
  if (!target) return "";
  const scope = period.trim();
  if (!zh) {
    const task = { financial: "Analyze the financial statements, earnings quality and cash flow", events: "Review recent material events and verify the news sources", risk: "Assess valuation, financial and business risks" }[kind];
    return `${task} for ${target}${scope ? ` (${scope})` : ""}. Cite sources and report dates/pages; separate facts from judgments and identify missing evidence.`;
  }
  const task = { financial: "分析财报、盈利质量与现金流", events: "梳理近期重大事件，核对新闻来源与影响", risk: "检查估值、财务和经营风险" }[kind];
  return `请研究 ${target}${scope ? `，报告期 ${scope}` : ""}：${task}。注明资料来源、日期和页码，区分事实与判断，并列出缺失的证据。`;
}

export function isFinancialSession(row: SessionSummary, agentId: string) {
  return row.agentId === agentId && !row.hiddenFromIndex && row.archiveState?.status !== "archived" && !isSessionDeleteTombstoned(row.id);
}

export function activeFinancialItems(items: KnowledgeItem[], knowledgeBaseId: string) {
  return items.filter((item) => financialItemMatchesLibrary(item, knowledgeBaseId)
    && (!item.knowledgeState || item.knowledgeState === "active")
    && item.stability !== "deprecated");
}

function financialItemMatchesLibrary(item: KnowledgeItem, knowledgeBaseId: string) {
  if (item.knowledgeBaseId === knowledgeBaseId) return true;
  // The API returns local item ids for an Agent-scoped request. Require its owner
  // before accepting a local id, since other Agents can have identically named libraries.
  const scoped = /^agent:([^:]+):([^:]+)$/.exec(knowledgeBaseId);
  return Boolean(scoped && item.knowledgeBaseId === scoped[2]
    && item.ownerType === "agent" && item.ownerId === scoped[1]
    && (!item.agentId || item.agentId === scoped[1]));
}

function textField(value: unknown) {
  return typeof value === "string" ? value.trim().slice(0, 500) : "";
}

export function safeFinancialSourceUrl(value: unknown) {
  const raw = textField(value);
  if (!raw) return "";
  try {
    const url = new URL(raw);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : "";
  } catch { return ""; }
}

export function activeFinancialSources(item: KnowledgeItem, sources: KnowledgeSourceArtifact[], now = Date.now()) {
  return sources.filter((source) => {
    const evidence = source.sourceRef?.financialEvidence;
    const metadata = evidence && typeof evidence === "object" && !Array.isArray(evidence) ? evidence as Record<string, unknown> : {};
    return source.knowledgeBaseId === item.knowledgeBaseId
      && (!item.ownerId || (source.ownerType === item.ownerType && source.ownerId === item.ownerId))
      && (!item.agentId || !source.agentId || source.agentId === item.agentId)
      && item.sourceArtifactIds.includes(source.sourceArtifactId)
      && source.sourceType === "pdf_refinement"
      && (!source.status || source.status === "active")
      && ![source.expiresAt, metadata.expiresAt].some((value) => typeof value === "string" && value && Date.parse(value) <= now);
  });
}

/** Read provenance fields; free-form titles and summaries are never scope evidence. */
export function financialSourceMetadata(source: KnowledgeSourceArtifact) {
  const raw = source.sourceRef?.financialEvidence;
  const meta = raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : {};
  const page = typeof meta.page === "number" ? String(meta.page) : textField(meta.page);
  return {
    company: textField(meta.company),
    ticker: textField(meta.ticker),
    period: textField(meta.reportPeriod),
    version: textField(meta.reportVersion),
    publishedAt: textField(meta.publishedAt),
    page: /^[1-9]\d{0,5}(?:[-–][1-9]\d{0,5})?$/.test(page) ? page : "",
    url: safeFinancialSourceUrl(meta.sourceUrl),
  };
}
