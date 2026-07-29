import type { DataProcessingRecord, TeamWorkflowCandidate } from "../../../api/types";

import {
  sourceCollectionNonNegativeCount,
  sourceCollectionStageUserSummary,
  type SourceCollectionStageCardProjection,
} from "./stageProjection";

export type SourceCollectionCandidateWithSource = TeamWorkflowCandidate & {
  sourcePath?: string;
  sourceRef?: string;
  sourceUrl?: string;
};

export type SourceCollectionCandidateVersionFamilyPresentation = {
  isVersioned: boolean;
  isCurrent: boolean;
  isSuperseded: boolean;
  statusLabel: string;
  chainLabel: string;
  evidenceLabel: string;
  reviewDisabledReason: string;
};

export type SourceCollectionCandidateProvenance = {
  kind: "doi" | "file" | "missing" | "ref" | "search_evidence" | "url";
  label: string;
  value: string;
  href: string;
};

export type SourceCollectionEvidenceLedgerSummary = {
  status: string;
  missingAnchor: boolean;
  sourceRefCount: number;
  evidenceRefCount: number;
  claimCount: number;
  keyFindingCount: number;
  citationCount: number;
  limitations: string[];
  uncertainty: string[];
  riskFlags: string[];
  supportLevel: string;
  nextAction: string;
  claims: unknown[];
  keyFindings: unknown[];
  citations: unknown[];
  sourceRefs: unknown[];
  evidenceRefs: unknown[];
};

export type SourceCollectionSourceFilter = "all" | "pdf" | "paper_web" | "dataset" | "local_file" | "missing";

export const SOURCE_COLLECTION_SOURCE_FILTERS: SourceCollectionSourceFilter[] = [
  "all",
  "pdf",
  "paper_web",
  "dataset",
  "local_file",
  "missing",
];

export type SourceCollectionCandidateTrace = {
  assignmentId: string;
  query: string;
  queryId: string;
  rawLocation: string;
  recordId: string;
  runId: string;
  searchProvider: string;
  searchUrl: string;
  sourceRef: string;
};

export type SourceCollectionEvidenceTone = "ready" | "warning";

export type SourceCollectionExcludedRecoveryInput = {
  lang: "zh" | "en";
  excludedCount: number;
  missingCount: number;
  importFailedCount: number;
  importPendingRecordCount: number;
};

export type SourceCollectionExcludedRecoveryState = {
  blockedByExcludedSources: boolean;
  excludedCount: number;
  panelTitle: string;
  panelAriaLabel: string;
  statusLabel: string;
  failedLabel: string;
  recoverLabel: string;
  tone: "danger" | "progressable";
  summary: string;
  recoverText: string;
  primaryActionText: string;
  primaryActionTitle: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function metadataString(metadata: Record<string, unknown>, key: string) {
  const value = metadata[key];
  return typeof value === "string" ? value.trim() : "";
}

export function sourceCollectionSourceTypeLabel(value: string | undefined | null, lang: "zh" | "en") {
  const normalized = String(value || "").trim().toLowerCase();
  const zh: Record<string, string> = {
    dataset: "数据集",
    file: "本地文件",
    manual: "手工记录",
    note: "笔记",
    paper: "论文",
    review: "综述",
    url: "网页",
  };
  const en: Record<string, string> = {
    dataset: "dataset",
    file: "file",
    manual: "manual",
    note: "note",
    paper: "paper",
    review: "review",
    url: "url",
  };
  return (lang === "zh" ? zh : en)[normalized] ?? (value || "-");
}

export function sourceCollectionSourceFilterLabel(value: SourceCollectionSourceFilter, lang: "zh" | "en") {
  const zh: Record<SourceCollectionSourceFilter, string> = {
    all: "全部",
    dataset: "数据集",
    local_file: "本地文件",
    missing: "缺少来源",
    paper_web: "论文网页/DOI",
    pdf: "PDF",
  };
  const en: Record<SourceCollectionSourceFilter, string> = {
    all: "All",
    dataset: "Datasets",
    local_file: "Local files",
    missing: "Missing source",
    paper_web: "Paper page/DOI",
    pdf: "PDF",
  };
  return (lang === "zh" ? zh : en)[value];
}

function sourceCollectionLooksLikePdf(...values: Array<string | undefined | null>) {
  return values.some((value) => {
    const text = String(value || "").trim().toLowerCase();
    return Boolean(text) && (/\.pdf(?:$|[?#\s])/i.test(text) || text.endsWith(".pdf") || text.includes("application/pdf"));
  });
}

function sourceCollectionSourceCategoryFromProvenance(
  sourceType: string | undefined | null,
  provenance: SourceCollectionCandidateProvenance,
  ...extraRefs: Array<string | undefined | null>
): SourceCollectionSourceFilter {
  const normalizedSourceType = String(sourceType || "").trim().toLowerCase();
  const refText = [provenance.value, ...extraRefs].join(" ").toLowerCase();
  if (provenance.kind === "missing" || provenance.kind === "search_evidence") {
    return "missing";
  }
  if (normalizedSourceType.includes("dataset")) {
    return "dataset";
  }
  if (normalizedSourceType.includes("pdf") || sourceCollectionLooksLikePdf(provenance.value, ...extraRefs)) {
    return "pdf";
  }
  if (provenance.kind === "file" || ["file", "manual", "note"].includes(normalizedSourceType)) {
    return "local_file";
  }
  if (
    provenance.kind === "doi"
    || provenance.kind === "url"
    || ["paper", "review", "url", "journal-article", "proceedings-article"].some((type) => normalizedSourceType.includes(type))
    || /\bdoi\b|doi\.org|\/abs\/|\/pdf\//i.test(refText)
  ) {
    return "paper_web";
  }
  return "missing";
}

export function sourceCollectionFilterMatches(
  activeFilter: SourceCollectionSourceFilter,
  itemFilter: SourceCollectionSourceFilter,
) {
  return activeFilter === "all" || activeFilter === itemFilter;
}

export function sourceCollectionFilterCounts(kinds: SourceCollectionSourceFilter[]) {
  const counts = SOURCE_COLLECTION_SOURCE_FILTERS.reduce((current, filter) => {
    current[filter] = 0;
    return current;
  }, {} as Record<SourceCollectionSourceFilter, number>);
  counts.all = kinds.length;
  kinds.forEach((kind) => {
    counts[kind] += 1;
  });
  return counts;
}

function evidenceLedgerArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function evidenceLedgerText(value: unknown) {
  if (typeof value === "string" || typeof value === "number") {
    return String(value).trim();
  }
  if (!isRecord(value)) {
    return "";
  }
  const primary = [
    value.claim,
    value.finding,
    value.citation,
    value.text,
    value.title,
    value.label,
    value.id,
  ]
    .map((item) => (typeof item === "string" || typeof item === "number" ? String(item).trim() : ""))
    .find(Boolean);
  const anchors = [
    typeof value.sourceRef === "string" ? value.sourceRef.trim() : "",
    typeof value.page === "string" || typeof value.page === "number" ? `p.${String(value.page).trim()}` : "",
    typeof value.evidenceRef === "string" ? value.evidenceRef.trim() : "",
  ].filter(Boolean);
  return [primary, anchors.length ? anchors.join(" · ") : ""].filter(Boolean).join(" · ");
}

function evidenceLedgerTextList(value: unknown): string[] {
  return evidenceLedgerArray(value)
    .map((item) => evidenceLedgerText(item))
    .filter(Boolean)
    .slice(0, 12);
}

export function sourceCollectionEvidenceLedgerSummary(
  candidate: TeamWorkflowCandidate,
): SourceCollectionEvidenceLedgerSummary | null {
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const extraction = isRecord(metadata.contentExtraction) ? metadata.contentExtraction : {};
  const ledger = isRecord(extraction.evidenceLedger) ? extraction.evidenceLedger : null;
  if (!ledger) {
    return null;
  }
  const claims = evidenceLedgerArray(ledger.claims);
  const keyFindings = evidenceLedgerArray(ledger.keyFindings);
  const citations = evidenceLedgerArray(ledger.citations);
  const sourceRefs = evidenceLedgerArray(ledger.sourceRefs);
  const evidenceRefs = evidenceLedgerArray(ledger.evidenceRefs);
  const status = String(ledger.status || extraction.evidenceStatus || "").trim() || "evidence_ready";
  return {
    status,
    missingAnchor: status === "missing_evidence_anchor",
    sourceRefCount: sourceRefs.length,
    evidenceRefCount: evidenceRefs.length,
    claimCount: claims.length,
    keyFindingCount: keyFindings.length,
    citationCount: citations.length,
    limitations: evidenceLedgerTextList(ledger.limitations),
    uncertainty: evidenceLedgerTextList(ledger.uncertainty),
    riskFlags: evidenceLedgerTextList(ledger.riskFlags),
    supportLevel: typeof ledger.supportLevel === "string" ? ledger.supportLevel.trim() : "",
    nextAction: typeof ledger.nextAction === "string" ? ledger.nextAction.trim() : "",
    claims,
    keyFindings,
    citations,
    sourceRefs,
    evidenceRefs,
  };
}

export function sourceCollectionEvidenceLedgerCardLabel(
  summary: SourceCollectionEvidenceLedgerSummary,
  lang: "zh" | "en",
) {
  const contentCount = summary.claimCount + summary.keyFindingCount + summary.citationCount;
  const countLabel = lang === "zh" ? `${contentCount} 条` : `${contentCount} items`;
  return `Evidence Ledger ${summary.status} · ${countLabel}`;
}

export function sourceCollectionEvidenceLedgerActionLabel(
  summary: SourceCollectionEvidenceLedgerSummary,
  lang: "zh" | "en",
) {
  if (summary.missingAnchor) {
    return lang === "zh" ? "补证据锚点" : "add evidence anchor";
  }
  return lang === "zh" ? "证据可用" : "evidence ready";
}

export function sourceCollectionEvidenceLedgerTone(
  summary: SourceCollectionEvidenceLedgerSummary,
): SourceCollectionEvidenceTone {
  return summary.missingAnchor ? "warning" : "ready";
}

function normalizedDoi(value: string | undefined | null) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  const doiUrl = text.match(/^https?:\/\/(?:dx\.)?doi\.org\/(.+)$/i);
  const candidate = doiUrl ? doiUrl[1] : text.replace(/^doi:\s*/i, "");
  const match = candidate.match(/10\.\d{4,9}\/[^\s"'<>]+/i);
  return match ? match[0].replace(/[).,;]+$/, "") : "";
}

function compactSourceUrl(value: string) {
  try {
    const url = new URL(value);
    const pathname = url.pathname.length > 42 ? `${url.pathname.slice(0, 39)}...` : url.pathname;
    return `${url.hostname}${pathname}`;
  } catch {
    return value;
  }
}

function sourceCollectionIsMachineEvidenceUrl(value: string) {
  if (!/^https?:\/\//i.test(value)) {
    return false;
  }
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    const pathname = url.pathname.toLowerCase();
    return (
      hostname === "api.crossref.org"
      || hostname === "api.openalex.org"
      || hostname === "api.semanticscholar.org"
      || hostname === "api.unpaywall.org"
      || hostname === "export.arxiv.org"
      || pathname.startsWith("/api/")
    );
  } catch {
    return false;
  }
}

export function sourceCollectionCandidateProvenance(
  candidate: TeamWorkflowCandidate,
  lang: "zh" | "en",
): SourceCollectionCandidateProvenance {
  const sourceCandidate = candidate as SourceCollectionCandidateWithSource;
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const sourceUrl =
    String(sourceCandidate.sourceUrl || "").trim()
    || metadataString(metadata, "sourceUrl")
    || metadataString(metadata, "sourceRef")
    || metadataString(metadata, "url");
  const sourcePath =
    String(sourceCandidate.sourcePath || "").trim()
    || metadataString(metadata, "sourcePath")
    || metadataString(metadata, "path");
  const doi =
    normalizedDoi(metadataString(metadata, "doi"))
    || normalizedDoi(sourceCandidate.sourceRef)
    || normalizedDoi(sourceUrl);

  if (doi) {
    return {
      kind: "doi",
      label: "DOI",
      value: doi,
      href: `https://doi.org/${doi}`,
    };
  }

  if (/^https?:\/\//i.test(sourceUrl) && sourceCollectionIsMachineEvidenceUrl(sourceUrl)) {
    return {
      kind: "search_evidence",
      label: lang === "zh" ? "仅搜索记录" : "Search evidence only",
      value: compactSourceUrl(sourceUrl),
      href: "",
    };
  }

  if (/^https?:\/\//i.test(sourceUrl)) {
    return {
      kind: "url",
      label: lang === "zh" ? "网页链接" : "Web link",
      value: compactSourceUrl(sourceUrl),
      href: sourceUrl,
    };
  }

  if (sourcePath) {
    return {
      kind: "file",
      label: lang === "zh" ? "本地文件" : "Local file",
      value: sourcePath,
      href: "",
    };
  }

  if (sourceUrl) {
    return {
      kind: "ref",
      label: lang === "zh" ? "来源标识" : "Source ref",
      value: sourceUrl,
      href: "",
    };
  }

  return {
    kind: "missing",
    label: lang === "zh" ? "缺少来源" : "Missing source",
    value: lang === "zh" ? "没有 sourceUrl/sourcePath/DOI" : "No sourceUrl/sourcePath/DOI",
    href: "",
  };
}

export function sourceCollectionCandidateVersionFamily(
  candidate: TeamWorkflowCandidate,
  lang: "zh" | "en",
): SourceCollectionCandidateVersionFamilyPresentation | null {
  const family = candidate.sourceVersionFamily;
  if (!family || family.sourceKind !== "research_square_preprint" || !family.versionLabel) {
    return null;
  }
  const isCurrent = family.state === "current";
  const isSuperseded = family.state === "superseded";
  const versionCount = Math.max(1, Number(family.familySize) || 1);
  const currentVersion = family.currentVersionLabel || family.versionLabel;
  if (lang === "zh") {
    return {
      isVersioned: true,
      isCurrent,
      isSuperseded,
      statusLabel: isSuperseded ? `历史版本 ${family.versionLabel}` : `当前版本 ${family.versionLabel}`,
      chainLabel: isCurrent
        ? `版本链 ${versionCount} 个版本 · 采用最新版`
        : `版本链 ${versionCount} 个版本 · 当前 ${currentVersion}`,
      evidenceLabel: "预印本 · 仅用于假设生成",
      reviewDisabledReason: isSuperseded
        ? `该记录已由 ${currentVersion} 取代，仅保留审计；请审核当前版本。`
        : "",
    };
  }
  return {
    isVersioned: true,
    isCurrent,
    isSuperseded,
    statusLabel: isSuperseded ? `Historical ${family.versionLabel}` : `Current ${family.versionLabel}`,
    chainLabel: isCurrent
      ? `${versionCount}-version chain · latest selected`
      : `${versionCount}-version chain · current ${currentVersion}`,
    evidenceLabel: "Preprint · hypothesis generation only",
    reviewDisabledReason: isSuperseded
      ? `Superseded by ${currentVersion}; retained for audit. Review the current version instead.`
      : "",
  };
}

export function sourceCollectionIndependentSourceCount(
  candidates: TeamWorkflowCandidate[],
) {
  return candidates.reduce((count, candidate) => {
    const family = candidate.sourceVersionFamily;
    if (!family || family.countsAsIndependentSource) {
      return count + 1;
    }
    return count;
  }, 0);
}

export function sourceCollectionRecordProvenance(
  record: DataProcessingRecord,
  lang: "zh" | "en",
): SourceCollectionCandidateProvenance {
  const metadata = isRecord(record.metadata) ? record.metadata : {};
  const sourceRef =
    String(record.sourceRef || "").trim()
    || metadataString(metadata, "sourceRef")
    || metadataString(metadata, "sourceUrl")
    || metadataString(metadata, "url");
  const rawLocation =
    String(record.rawLocation || "").trim()
    || metadataString(metadata, "rawLocation")
    || metadataString(metadata, "sourcePath")
    || metadataString(metadata, "path");
  const doi =
    normalizedDoi(metadataString(metadata, "doi"))
    || normalizedDoi(sourceRef)
    || normalizedDoi(rawLocation);

  if (doi) {
    return {
      kind: "doi",
      label: "DOI",
      value: doi,
      href: `https://doi.org/${doi}`,
    };
  }

  if (/^https?:\/\//i.test(sourceRef) && !sourceCollectionIsMachineEvidenceUrl(sourceRef)) {
    return {
      kind: "url",
      label: lang === "zh" ? "网页链接" : "Web link",
      value: compactSourceUrl(sourceRef),
      href: sourceRef,
    };
  }

  if (/^https?:\/\//i.test(rawLocation) && !sourceCollectionIsMachineEvidenceUrl(rawLocation)) {
    return {
      kind: "url",
      label: lang === "zh" ? "网页链接" : "Web link",
      value: compactSourceUrl(rawLocation),
      href: rawLocation,
    };
  }

  if (/^https?:\/\//i.test(sourceRef) || /^https?:\/\//i.test(rawLocation)) {
    const evidenceUrl = /^https?:\/\//i.test(sourceRef) ? sourceRef : rawLocation;
    return {
      kind: "search_evidence",
      label: lang === "zh" ? "搜索证据" : "Search evidence",
      value: compactSourceUrl(evidenceUrl),
      href: "",
    };
  }

  if (rawLocation) {
    return {
      kind: "file",
      label: lang === "zh" ? "本地文件" : "Local file",
      value: rawLocation,
      href: "",
    };
  }

  if (sourceRef) {
    return {
      kind: "ref",
      label: lang === "zh" ? "来源标识" : "Source ref",
      value: sourceRef,
      href: "",
    };
  }

  return {
    kind: "missing",
    label: lang === "zh" ? "缺少来源" : "Missing source",
    value: lang === "zh" ? "没有 DOI、链接或本地文件" : "No DOI, URL, or local file",
    href: "",
  };
}

export function sourceCollectionRecordSourceCategory(record: DataProcessingRecord, lang: "zh" | "en") {
  const metadata = isRecord(record.metadata) ? record.metadata : {};
  const provenance = sourceCollectionRecordProvenance(record, lang);
  return sourceCollectionSourceCategoryFromProvenance(
    record.sourceType,
    provenance,
    record.sourceRef,
    record.rawLocation,
    metadataString(metadata, "sourceType"),
    metadataString(metadata, "contentType"),
  );
}

export function sourceCollectionCandidateSourceCategory(
  candidate: TeamWorkflowCandidate,
  lang: "zh" | "en",
) {
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const sourceCandidate = candidate as SourceCollectionCandidateWithSource;
  const normalizedCategory = metadataString(metadata, "sourceCategory") as SourceCollectionSourceFilter;
  if (SOURCE_COLLECTION_SOURCE_FILTERS.includes(normalizedCategory)) {
    return normalizedCategory;
  }
  const provenance = sourceCollectionCandidateProvenance(candidate, lang);
  return sourceCollectionSourceCategoryFromProvenance(
    sourceCandidate.sourceKind || candidate.sourceKind || metadataString(metadata, "sourceType") || candidate.candidateType,
    provenance,
    sourceCandidate.sourceRef,
    sourceCandidate.sourceUrl,
    sourceCandidate.sourcePath,
    metadataString(metadata, "contentType"),
  );
}

export function sourceCollectionCandidateOpenLabel(
  provenance: SourceCollectionCandidateProvenance,
  lang: "zh" | "en",
) {
  if (provenance.kind === "doi") {
    return lang === "zh" ? "打开论文 DOI" : "Open DOI";
  }
  if (provenance.kind === "url") {
    return lang === "zh" ? "打开网页来源" : "Open source page";
  }
  if (provenance.kind === "file") {
    return lang === "zh" ? "打开本地文件" : "Open local file";
  }
  if (provenance.kind === "search_evidence") {
    return lang === "zh" ? "查看搜索证据" : "View search evidence";
  }
  if (provenance.kind === "missing") {
    return lang === "zh" ? "缺少来源" : "Missing source";
  }
  return lang === "zh" ? "查看来源标识" : "View source ref";
}

function sourceCollectionCandidateEvidenceRefs(candidate: TeamWorkflowCandidate) {
  const refs = (candidate as TeamWorkflowCandidate & { evidenceRefs?: unknown }).evidenceRefs;
  return Array.isArray(refs) ? refs.filter(isRecord) : [];
}

export function sourceCollectionCandidateTrace(candidate: TeamWorkflowCandidate): SourceCollectionCandidateTrace {
  const sourceCandidate = candidate as SourceCollectionCandidateWithSource;
  const metadata = isRecord(candidate.metadata) ? candidate.metadata : {};
  const recordMetadata = isRecord(metadata.dataProcessingRecordMetadata) ? metadata.dataProcessingRecordMetadata : {};
  const sourceTraceFromRecord = isRecord(recordMetadata.sourceCollectionTrace) ? recordMetadata.sourceCollectionTrace : {};
  const sourceTrace = Object.keys(sourceTraceFromRecord).length
    ? sourceTraceFromRecord
    : isRecord(metadata.sourceCollectionTrace)
      ? metadata.sourceCollectionTrace
      : {};
  const importedRecord = isRecord(metadata.importedFromDataRecord) ? metadata.importedFromDataRecord : {};
  const collectionTrace = isRecord(metadata.dataProcessingCollectionTrace) ? metadata.dataProcessingCollectionTrace : {};
  const evidenceRefs = sourceCollectionCandidateEvidenceRefs(candidate);
  const dataRecordRef = evidenceRefs.find((ref) => String(ref.type || "") === "data_record");
  const runRef = evidenceRefs.find((ref) => String(ref.type || "") === "data_processing_run");
  return {
    assignmentId: String(metadata.assignmentId || sourceTrace.assignmentId || collectionTrace.assignmentId || ""),
    query: String(metadata.query || sourceTrace.query || ""),
    queryId: String(metadata.queryId || sourceTrace.queryId || ""),
    rawLocation: String(importedRecord.rawLocation || sourceTrace.rawLocation || sourceCandidate.sourcePath || ""),
    recordId: String(metadata.sourceRecordId || importedRecord.recordId || dataRecordRef?.id || ""),
    runId: String(metadata.sourceRunId || sourceTrace.runId || importedRecord.runId || runRef?.id || ""),
    searchProvider: String(metadata.searchProvider || sourceTrace.searchProvider || recordMetadata.searchProvider || ""),
    searchUrl: String(metadata.searchUrl || sourceTrace.searchUrl || recordMetadata.searchUrl || ""),
    sourceRef: String(metadata.sourceRef || importedRecord.sourceRef || sourceCandidate.sourceRef || sourceCandidate.sourceUrl || metadataString(metadata, "sourceRef")),
  };
}

export function sourceCollectionCandidateEmptyStateText(input: {
  lang: "zh" | "en";
  loading: boolean;
  awaitingRefresh: boolean;
  displayedCandidateCount: number;
  filteredCandidateCount: number;
  rawRecordCount: number;
  projection?: SourceCollectionStageCardProjection | null;
}) {
  if (input.loading) {
    return input.lang === "zh" ? "正在加载资料提炼结果..." : "Loading extracted sources...";
  }
  if (input.awaitingRefresh) {
    return input.lang === "zh"
      ? `Agent 已生成 ${input.displayedCandidateCount} 条候选资料，列表正在同步；请刷新或稍候。`
      : `Agent produced ${input.displayedCandidateCount} candidates; the list is syncing. Refresh or wait a moment.`;
  }
  if (input.displayedCandidateCount > 0) {
    return input.lang === "zh" ? "当前过滤条件下没有候选资料。" : "No candidates match this filter.";
  }
  const projectionSummary = sourceCollectionStageUserSummary(input.projection, input.lang);
  if (projectionSummary) {
    return projectionSummary;
  }
  if (input.rawRecordCount > 0) {
    return input.lang === "zh"
      ? `已收到 ${input.rawRecordCount} 条原始资料，但本轮还没有生成候选资料。建议：继续补全提炼。`
      : `${input.rawRecordCount} source records exist, but no candidate sources have been generated for this run yet.`;
  }
  return input.lang === "zh" ? "本轮还没有可提炼的资料。" : "No sources are ready for extraction in this run yet.";
}

export function deriveSourceCollectionExcludedRecoveryState(
  input: SourceCollectionExcludedRecoveryInput,
): SourceCollectionExcludedRecoveryState {
  const excludedCount = sourceCollectionNonNegativeCount(input.excludedCount);
  const remainingGapCount = Math.max(
    sourceCollectionNonNegativeCount(input.missingCount),
    sourceCollectionNonNegativeCount(input.importFailedCount),
    sourceCollectionNonNegativeCount(input.importPendingRecordCount),
  );
  const blockedByExcludedSources = excludedCount > 0 && remainingGapCount > 0 && excludedCount >= remainingGapCount;
  if (!blockedByExcludedSources) {
    const zh = input.lang === "zh";
    return {
      blockedByExcludedSources: false,
      excludedCount,
      panelTitle: zh ? "提炼失败恢复" : "Extraction recovery",
      panelAriaLabel: zh ? "资料提炼失败恢复工作台" : "Source extraction recovery panel",
      statusLabel: "",
      failedLabel: zh ? "提炼失败" : "failed extraction",
      recoverLabel: zh ? "待补提炼" : "to recover",
      tone: "danger",
      summary: "",
      recoverText: "",
      primaryActionText: "",
      primaryActionTitle: "",
    };
  }
  const zh = input.lang === "zh";
  return {
    blockedByExcludedSources: true,
    excludedCount,
    panelTitle: zh ? "提炼排除项确认" : "Extraction exclusions review",
    panelAriaLabel: zh ? "资料提炼排除项确认工作台" : "Source extraction exclusions review panel",
    statusLabel: zh ? "可继续推进" : "Ready to continue",
    failedLabel: zh ? "缺口处理" : "gap handling",
    recoverLabel: zh ? "已排除" : "excluded",
    tone: "progressable",
    summary: zh
      ? `剩余 ${remainingGapCount} 条资料已被排除，不会再次导入候选；可进入 Agent 私聊查看排除原因，或返回资料寻找补充新来源。`
      : `${remainingGapCount} remaining sources are already excluded, so they will not be imported again. Open the Agent chat to inspect the reasons or search for new sources.`,
    recoverText: zh ? `已排除 ${excludedCount}` : `${excludedCount} excluded`,
    primaryActionText: zh ? "查看排除原因" : "Inspect exclusions",
    primaryActionTitle: zh
      ? "剩余资料已被排除，打开资料提炼 Agent 私聊查看原因"
      : "Remaining sources are excluded; open the source extraction Agent chat to inspect why",
  };
}
