import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, CheckCircle2, Database, Eye, FileText, RefreshCw, Search, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { MemoryItem, MemoryOverview, MemorySection } from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./MemoryRoute.module.css";

type Copy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  refresh: string;
  loading: string;
  loadFailed: string;
  sections: string;
  items: string;
  agentVisible: string;
  runtimeInjected: string;
  sourcePath: string;
  sourceApi: string;
  visibility: string;
  agentVisibility: string;
  usedBy: string;
  summary: string;
  rawContent: string;
  noContent: string;
  searchPlaceholder: string;
  allSections: string;
  noMatches: string;
  yes: string;
  no: string;
  inPrompt: string;
  notInPrompt: string;
  canUse: string;
  manualOnly: string;
  missing: string;
  truncated: string;
  warnings: string;
  generatedAt: string;
  sectionCount: string;
  itemCount: string;
};

const COPY: Record<"zh" | "en", Copy> = {
  zh: {
    eyebrow: "Agent Memory",
    title: "记忆",
    subtitle: "按来源聚合 agent 记忆、运行证据和可感知入口，明确哪些内容会进入 prompt。",
    refresh: "刷新",
    loading: "正在整理记忆...",
    loadFailed: "记忆概览加载失败",
    sections: "来源分区",
    items: "记忆条目",
    agentVisible: "agent 可感知",
    runtimeInjected: "运行时注入",
    sourcePath: "路径",
    sourceApi: "接口",
    visibility: "可见性",
    agentVisibility: "Agent 口径",
    usedBy: "作用位置",
    summary: "摘要",
    rawContent: "原文",
    noContent: "没有可展示的原文。",
    searchPlaceholder: "搜索来源、路径、摘要或作用位置",
    allSections: "全部来源",
    noMatches: "没有匹配当前搜索的记忆。",
    yes: "是",
    no: "否",
    inPrompt: "进 prompt",
    notInPrompt: "不默认注入",
    canUse: "可使用",
    manualOnly: "显式读取",
    missing: "缺失",
    truncated: "已截断",
    warnings: "诊断提醒",
    generatedAt: "生成时间",
    sectionCount: "分区",
    itemCount: "条目",
  },
  en: {
    eyebrow: "Agent Memory",
    title: "Memory",
    subtitle: "Groups agent memory, runtime evidence, and visibility by source, including prompt injection status.",
    refresh: "Refresh",
    loading: "Loading memory...",
    loadFailed: "Memory overview failed to load",
    sections: "Sources",
    items: "Memory Items",
    agentVisible: "agent visible",
    runtimeInjected: "runtime injected",
    sourcePath: "Path",
    sourceApi: "API",
    visibility: "Visibility",
    agentVisibility: "Agent visibility",
    usedBy: "Used by",
    summary: "Summary",
    rawContent: "Raw content",
    noContent: "No raw content to show.",
    searchPlaceholder: "Search source, path, summary, or usage",
    allSections: "All sources",
    noMatches: "No memory matched the current search.",
    yes: "Yes",
    no: "No",
    inPrompt: "In prompt",
    notInPrompt: "Not injected",
    canUse: "Usable",
    manualOnly: "Explicit read",
    missing: "Missing",
    truncated: "Truncated",
    warnings: "Warnings",
    generatedAt: "Generated",
    sectionCount: "Sections",
    itemCount: "Items",
  },
};

function formatTimestamp(value: string, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text) {
    return "-";
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

function normalizeText(value: string) {
  return String(value || "").trim().toLowerCase();
}

function searchTarget(section: MemorySection, item: MemoryItem) {
  return normalizeText(
    [
      section.title,
      section.sourceKind,
      section.sourcePath,
      section.agentVisibility,
      item.title,
      item.kind,
      item.source,
      item.path,
      item.summary,
      item.usedBy.join(" "),
    ].join(" "),
  );
}

function filterSections(sections: MemorySection[], activeSectionId: string, searchText: string) {
  const query = normalizeText(searchText);
  return sections
    .filter((section) => !activeSectionId || section.id === activeSectionId)
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => !query || searchTarget(section, item).includes(query)),
    }))
    .filter((section) => section.items.length > 0 || !query);
}

function statusClassName(active: boolean, injected: boolean) {
  if (injected) {
    return `${styles.statusPill} ${styles.statusPillPrompt}`;
  }
  if (active) {
    return `${styles.statusPill} ${styles.statusPillVisible}`;
  }
  return `${styles.statusPill} ${styles.statusPillMuted}`;
}

function contentLanguage(contentType: string) {
  if (contentType === "json") {
    return "json";
  }
  if (contentType === "markdown") {
    return "markdown";
  }
  if (contentType === "html") {
    return "html";
  }
  return "text";
}

export function MemoryRoute() {
  const { lang } = useAppI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const [activeSectionId, setActiveSectionId] = useState("");
  const [activeItemId, setActiveItemId] = useState("");
  const [searchText, setSearchText] = useState("");

  const overviewQuery = useQuery({
    queryKey: queryKeys.memoryOverview(),
    queryFn: () => fetchJson<MemoryOverview>("/api/memory/overview"),
    refetchInterval: resolvePollingInterval(pageVisible, 30_000),
    refetchIntervalInBackground: false,
  });

  const overview = overviewQuery.data;
  const sections = overview?.sections ?? [];
  const visibleSections = useMemo(
    () => filterSections(sections, activeSectionId, searchText),
    [activeSectionId, searchText, sections],
  );
  const flatVisibleItems = useMemo(
    () =>
      visibleSections.flatMap((section) =>
        section.items.map((item) => ({
          section,
          item,
        })),
      ),
    [visibleSections],
  );
  const activePair =
    flatVisibleItems.find(({ item }) => item.id === activeItemId) ?? flatVisibleItems[0] ?? null;
  const activeItem = activePair?.item ?? null;
  const activeSection = activePair?.section ?? null;

  useEffect(() => {
    if (!sections.length) {
      return;
    }
    if (activeSectionId && !sections.some((section) => section.id === activeSectionId)) {
      setActiveSectionId("");
    }
  }, [activeSectionId, sections]);

  useEffect(() => {
    if (!activeItemId || flatVisibleItems.some(({ item }) => item.id === activeItemId)) {
      return;
    }
    setActiveItemId(flatVisibleItems[0]?.item.id ?? "");
  }, [activeItemId, flatVisibleItems]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
  };

  const selectedSection = sections.find((section) => section.id === activeSectionId) ?? null;
  const selectedSectionCount = selectedSection?.items.length ?? overview?.summary.itemCount ?? 0;
  const warningCount = overview?.summary.warnings.length ?? 0;

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>
        <button type="button" className={styles.refreshButton} onClick={refresh}>
          <RefreshCw size={16} />
          {copy.refresh}
        </button>
      </header>

      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.sectionCount}</span>
          <strong>{overview?.summary.sectionCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.itemCount}</span>
          <strong>{overview?.summary.itemCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.agentVisible}</span>
          <strong>{overview?.summary.agentVisibleCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.runtimeInjected}</span>
          <strong>{overview?.summary.runtimeInjectedCount ?? 0}</strong>
        </section>
      </div>

      {warningCount > 0 ? (
        <section className={styles.warningStrip} aria-label={copy.warnings}>
          <TriangleAlert size={16} />
          <strong>{copy.warnings}</strong>
          <span>{overview?.summary.warnings.join("；")}</span>
        </section>
      ) : null}

      <div className={styles.workspace}>
        <aside className={styles.sourcePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.sections}</p>
              <h2>{copy.allSections}</h2>
            </div>
            <span className={styles.countPill}>{selectedSectionCount}</span>
          </div>

          <label className={styles.searchBox}>
            <Search size={15} />
            <input
              value={searchText}
              placeholder={copy.searchPlaceholder}
              onChange={(event) => setSearchText(event.target.value)}
            />
          </label>

          <button
            type="button"
            className={!activeSectionId ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
            onClick={() => setActiveSectionId("")}
          >
            <span className={styles.sourceIcon}>
              <Database size={15} />
            </span>
            <span className={styles.sourceCopy}>
              <strong>{copy.allSections}</strong>
              <span>{copy.items}: {overview?.summary.itemCount ?? 0}</span>
            </span>
          </button>

          <nav className={styles.sourceList} aria-label={copy.sections}>
            {sections.map((section) => {
              const active = section.id === activeSectionId;
              const injectedCount = section.items.filter((item) => item.inPrompt).length;
              return (
                <button
                  key={section.id}
                  type="button"
                  className={active ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
                  onClick={() => setActiveSectionId(section.id)}
                  aria-pressed={active}
                >
                  <span className={styles.sourceIcon}>
                    <Brain size={15} />
                  </span>
                  <span className={styles.sourceCopy}>
                    <strong>{section.title}</strong>
                    <span>{section.sourcePath || section.sourceKind}</span>
                  </span>
                  <span className={styles.sourceStats}>
                    {section.items.length}
                    {injectedCount ? ` / ${injectedCount}` : ""}
                  </span>
                </button>
              );
            })}
          </nav>
        </aside>

        <main className={styles.itemPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.items}</p>
              <h2>{activeSection?.title ?? copy.allSections}</h2>
            </div>
            <span className={styles.countPill}>{flatVisibleItems.length}</span>
          </div>

          {overviewQuery.isPending && !overview ? (
            <div className={styles.emptyState}>{copy.loading}</div>
          ) : overviewQuery.isError ? (
            <div className={styles.emptyState}>
              {copy.loadFailed}: {overviewQuery.error instanceof Error ? overviewQuery.error.message : String(overviewQuery.error)}
            </div>
          ) : !flatVisibleItems.length ? (
            <div className={styles.emptyState}>{copy.noMatches}</div>
          ) : (
            <div className={styles.itemList}>
              {flatVisibleItems.map(({ section, item }) => {
                const active = item.id === activeItem?.id;
                return (
                  <button
                    key={`${section.id}:${item.id}`}
                    type="button"
                    className={active ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
                    onClick={() => setActiveItemId(item.id)}
                    aria-pressed={active}
                  >
                    <span className={styles.itemHeader}>
                      <strong>{item.title}</strong>
                      <span>{formatTimestamp(item.updatedAt, lang)}</span>
                    </span>
                    <span className={styles.itemPath}>{item.path || item.source}</span>
                    <span className={styles.itemSummary}>{item.summary}</span>
                    <span className={styles.itemBadges}>
                      <span className={statusClassName(item.agentVisible, item.inPrompt)}>
                        {item.inPrompt ? copy.inPrompt : item.agentVisible ? copy.canUse : copy.manualOnly}
                      </span>
                      {!item.exists ? <span className={styles.statusPill}>{copy.missing}</span> : null}
                      {item.contentTruncated ? <span className={styles.statusPill}>{copy.truncated}</span> : null}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </main>

        <aside className={styles.detailPanel}>
          {activeItem && activeSection ? (
            <>
              <section className={styles.detailHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{activeSection.title}</p>
                  <h2>{activeItem.title}</h2>
                  <p>{activeItem.summary}</p>
                </div>
                <span className={statusClassName(activeItem.agentVisible, activeItem.inPrompt)}>
                  {activeItem.inPrompt ? copy.inPrompt : activeItem.agentVisible ? copy.canUse : copy.manualOnly}
                </span>
              </section>

              <div className={styles.factGrid}>
                <section>
                  <span>{copy.sourcePath}</span>
                  <strong title={activeItem.path}>{activeItem.path || "-"}</strong>
                </section>
                <section>
                  <span>{copy.sourceApi}</span>
                  <strong title={activeSection.sourceApi}>{activeSection.sourceApi || "-"}</strong>
                </section>
                <section>
                  <span>{copy.agentVisible}</span>
                  <strong>{activeItem.agentVisible ? copy.yes : copy.no}</strong>
                </section>
                <section>
                  <span>{copy.runtimeInjected}</span>
                  <strong>{activeItem.inPrompt ? copy.yes : copy.no}</strong>
                </section>
              </div>

              <section className={styles.visibilityPanel}>
                <div className={styles.visibilityHeader}>
                  <Eye size={16} />
                  <div>
                    <strong>{copy.agentVisibility}</strong>
                    <p>{activeSection.agentVisibility}</p>
                  </div>
                </div>
                <div className={styles.usageList}>
                  {activeItem.usedBy.map((usage) => (
                    <span key={`${activeItem.id}:${usage}`}>
                      <CheckCircle2 size={13} />
                      {usage}
                    </span>
                  ))}
                </div>
              </section>

              <section className={styles.sectionPanel}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.summary}</p>
                    <h3>{activeSection.sourceKind}</h3>
                  </div>
                  <span className={styles.countPill}>{formatTimestamp(activeSection.updatedAt, lang)}</span>
                </div>
                <p>{activeSection.summary}</p>
              </section>

              <details className={styles.rawPanel} open>
                <summary>
                  <FileText size={15} />
                  <span>{copy.rawContent}</span>
                  <code>{activeItem.contentType}</code>
                </summary>
                {activeItem.content ? (
                  <pre data-language={contentLanguage(activeItem.contentType)}>{activeItem.content}</pre>
                ) : (
                  <p>{copy.noContent}</p>
                )}
              </details>
            </>
          ) : (
            <section className={styles.emptyDetail}>
              <Brain size={24} />
              <strong>{copy.title}</strong>
              <p>{overviewQuery.isPending ? copy.loading : copy.noMatches}</p>
            </section>
          )}

          {overview ? (
            <p className={styles.generatedAt}>
              {copy.generatedAt}: {formatTimestamp(overview.generatedAt, lang)}
            </p>
          ) : null}
        </aside>
      </div>
    </section>
  );
}
