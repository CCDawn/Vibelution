import { useMemo, useState, type ReactNode } from "react";

import type { ConfigSummary } from "../api/types";
import { VButton, VNativeInput, VPanelHeader } from "../components/vui";
import styles from "./ConfigSettingsNavigation.styles";
import {
  searchConfigSettings,
  type ConfigSettingsSearchDocument,
  type ConfigSettingsSearchHit,
} from "./configSettingsSearch";

export type ConfigSettingsLanguage = "zh" | "en";

export type ConfigSettingsGroupId =
  | "overview-apply"
  | "workbench-interface"
  | "avatar-pet"
  | "models-profiles"
  | "runtime-context"
  | "tooling-diagnostics";

export const DEFAULT_CONFIG_SETTINGS_GROUP_ID: ConfigSettingsGroupId = "models-profiles";

export type ConfigSettingsPage = {
  id: string;
  title: string;
  summary: string;
  memberSectionIds: string[];
};

export type ConfigSettingsGroup = {
  id: ConfigSettingsGroupId;
  title: string;
  summary: string;
  pages: ConfigSettingsPage[];
};

export type ConfigSettingsGroupCopy = Record<ConfigSettingsGroupId, { title: string; summary: string }>;

type PageDefinition = {
  id: string;
  zh: string;
  en: string;
  members: readonly string[];
};

const GROUP_ORDER: ConfigSettingsGroupId[] = [
  "models-profiles",
  "workbench-interface",
  "avatar-pet",
  "runtime-context",
  "tooling-diagnostics",
  "overview-apply",
];

/**
 * Settings-align wave 3 — new-section registration single source of truth.
 *
 * The backend `_config_sections` (core/web/services/config_service.py) is the
 * only registration authority: every section it emits carries `group`/`page`
 * membership, and `buildConfigSettingsGroups` derives page members from it —
 * adding a backend section needs ZERO frontend edits. Adjudication notes:
 * - PAGE_DEFINITIONS below stays the frontend declaration of the group/page
 *   skeleton: ids, bilingual titles, and order. It is the smallest testable
 *   split (skeleton frontend-declared, membership backend-derived).
 * - The `members` arrays are a frozen legacy fallback kept only for payloads
 *   that predate backend membership (older fixtures/callers); annotated
 *   sections always win over the static table so backend re-grouping applies.
 * - Annotated sections whose (group, page) does not match any declared page
 *   land in the explicit fallback page below instead of being dropped.
 */
const FALLBACK_GROUP_ID: ConfigSettingsGroupId = "tooling-diagnostics";
const FALLBACK_PAGE_ID = "tooling-other";

const PAGE_DEFINITIONS: Record<ConfigSettingsGroupId, readonly PageDefinition[]> = {
  "overview-apply": [
    { id: "overview-save", zh: "总览与保存", en: "Overview & save", members: ["overview", "diagnostics"] },
  ],
  "workbench-interface": [
    { id: "workbench-interface", zh: "工作台与界面", en: "Workbench & interface", members: ["shell", "ui"] },
    { id: "workbench-shortcuts", zh: "快捷键", en: "Keyboard shortcuts", members: ["shortcuts"] },
  ],
  "avatar-pet": [
    { id: "identity-profile", zh: "个人资料与陪伴体", en: "Profile & companion", members: ["user-profile", "avatar", "pet"] },
  ],
  "models-profiles": [
    { id: "model-connection", zh: "模型连接", en: "Connections", members: ["models"] },
  ],
  "runtime-context": [
    { id: "runtime-context", zh: "上下文与分析", en: "Context & analysis", members: ["context-compression", "analysis"] },
  ],
  "tooling-diagnostics": [
    { id: "tooling-access", zh: "日常工具", en: "Everyday tools", members: ["security", "network", "parser"] },
    { id: "tooling-health", zh: "排障中心", en: "Troubleshooting", members: ["health-diagnostics", "log", "debug"] },
    { id: "tooling-git", zh: "高级维护", en: "Advanced maintenance", members: ["git-commit-model", "git-commit-prompt", "draft"] },
    { id: FALLBACK_PAGE_ID, zh: "其他设置", en: "Other settings", members: [] },
  ],
};

export function buildConfigSettingsGroups(
  sections: ConfigSummary["sections"],
  groupCopy: ConfigSettingsGroupCopy,
  language: ConfigSettingsLanguage,
): ConfigSettingsGroup[] {
  const sectionMap = new Map(sections.map((section) => [section.id, section]));
  // Annotated sections carry backend membership; they override the frozen
  // legacy member tables and drive newcomer placement.
  const annotated = sections.filter((section) => typeof section.group === "string" && typeof section.page === "string");
  const annotatedById = new Map(annotated.map((section) => [section.id, section]));
  const declaredPageKeys = new Set(
    GROUP_ORDER.flatMap((groupId) => PAGE_DEFINITIONS[groupId].map((definition) => `${groupId}::${definition.id}`)),
  );
  // Annotated sections whose (group, page) matches no declared page: collected
  // into the explicit fallback page instead of being silently dropped.
  const unplacedAnnotatedIds = annotated
    .filter((section) => !declaredPageKeys.has(`${section.group}::${section.page}`))
    .map((section) => section.id);

  function buildPage(groupId: ConfigSettingsGroupId, definition: PageDefinition): ConfigSettingsPage {
    const memberSectionIds = [
      // Frozen legacy member table: only still consulted for sections without
      // backend membership; an annotated section always follows its annotation.
      ...definition.members.filter((sectionId) => {
        if (!sectionMap.has(sectionId)) {
          return false;
        }
        const annotation = annotatedById.get(sectionId);
        return annotation ? annotation.group === groupId && annotation.page === definition.id : true;
      }),
      // Backend-registered members of this page (covers newcomers with zero
      // frontend edits), appended in backend order after legacy members.
      ...annotated
        .filter((section) => section.group === groupId && section.page === definition.id && !definition.members.includes(section.id))
        .map((section) => section.id),
    ];
    return summarizePage({
      id: definition.id,
      title: language === "zh" ? definition.zh : definition.en,
      summary: "",
      memberSectionIds,
    });
  }

  function summarizePage(page: ConfigSettingsPage): ConfigSettingsPage {
    const members = page.memberSectionIds.map((sectionId) => sectionMap.get(sectionId)).filter(Boolean);
    return {
      ...page,
      summary: members.length === 1
        ? members[0]?.summary ?? ""
        : members.map((section) => section?.title).filter(Boolean).join(language === "zh" ? "、" : ", "),
    };
  }

  return GROUP_ORDER.map((groupId) => {
    const pages = PAGE_DEFINITIONS[groupId]
      .map((definition) => buildPage(groupId, definition))
      .filter((page) => page.memberSectionIds.length > 0);
    // Explicit fallback page: annotated sections with an undeclared (group,
    // page) stay visible instead of being silently dropped.
    if (groupId === FALLBACK_GROUP_ID && unplacedAnnotatedIds.length > 0) {
      const definition = PAGE_DEFINITIONS[groupId].find((candidate) => candidate.id === FALLBACK_PAGE_ID);
      const fallbackPage: ConfigSettingsPage = summarizePage({
        id: FALLBACK_PAGE_ID,
        title: language === "zh" ? definition?.zh ?? "其他设置" : definition?.en ?? "Other settings",
        summary: "",
        memberSectionIds: unplacedAnnotatedIds,
      });
      const existingIndex = pages.findIndex((page) => page.id === FALLBACK_PAGE_ID);
      if (existingIndex >= 0) {
        pages[existingIndex] = {
          ...fallbackPage,
          memberSectionIds: [...pages[existingIndex].memberSectionIds, ...unplacedAnnotatedIds],
        };
        pages[existingIndex] = summarizePage(pages[existingIndex]);
      } else {
        pages.push(fallbackPage);
      }
    }
    return {
      id: groupId,
      title: groupCopy[groupId].title,
      summary: groupCopy[groupId].summary,
      pages,
    } satisfies ConfigSettingsGroup;
  }).filter((group) => group.pages.length > 0);
}

export function resolveConfigSettingsSelection(
  groups: ConfigSettingsGroup[],
  requestedGroupId: string,
  requestedPageId: string,
): { group: ConfigSettingsGroup | null; page: ConfigSettingsPage | null } {
  const group = groups.find((candidate) => candidate.id === requestedGroupId)
    ?? groups.find((candidate) => candidate.id === DEFAULT_CONFIG_SETTINGS_GROUP_ID)
    ?? groups[0]
    ?? null;
  const page = group?.pages.find((candidate) => candidate.id === requestedPageId) ?? group?.pages[0] ?? null;
  return { group, page };
}

type ConfigSettingsSidebarProps = {
  language: ConfigSettingsLanguage;
  title: string;
  subtitle: string;
  subtitleHint?: string;
  statusLabel: string;
  groups: ConfigSettingsGroup[];
  activeGroupId: string;
  onSelectGroup: (groupId: ConfigSettingsGroupId) => void;
  onNavigate?: (groupId: ConfigSettingsGroupId, pageId: string, sectionId?: string, fieldId?: string) => void;
  searchDocuments?: ConfigSettingsSearchDocument[];
  headerAction?: ReactNode;
  onShowAll?: () => void;
};

export function ConfigSettingsSidebar({
  onShowAll,
  language,
  title,
  subtitle,
  subtitleHint,
  statusLabel,
  groups,
  activeGroupId,
  onSelectGroup,
  onNavigate,
  searchDocuments = [],
  headerAction,
}: ConfigSettingsSidebarProps) {
  const sidebarHelp = subtitleHint || subtitle;
  const [searchQuery, setSearchQuery] = useState("");
  const searchHits = useMemo(
    () => searchConfigSettings(searchDocuments, searchQuery),
    [searchDocuments, searchQuery],
  );

  function selectHit(hit: ConfigSettingsSearchHit) {
    if (onNavigate) {
      onNavigate(hit.groupId, hit.pageId, hit.sectionId, hit.fieldId);
    } else {
      onSelectGroup(hit.groupId);
    }
  }

  return (
    <aside className={styles.sidebar} data-vui-region="config-settings-nav">
      <VPanelHeader
        className={styles.sidebarHeader}
        title={title}
        headingLevel={2}
        tooltip={sidebarHelp || undefined}
        tooltipLabel={language === "zh" ? "设置工作台说明" : "Settings workspace details"}
        actions={headerAction}
      />
      <div className={styles.searchStack}>
        <label className={styles.searchField}>
          <span className={styles.searchLabel}>{language === "zh" ? "搜索设置" : "Search settings"}</span>
          <VNativeInput
            type="search"
            value={searchQuery}
            placeholder={language === "zh" ? "主题、API Key、压缩…" : "Theme, API key, compression…"}
            aria-label={language === "zh" ? "搜索设置" : "Search settings"}
            onChange={(event) => setSearchQuery(event.target.value)}
          />
        </label>
        {searchHits.length > 0 ? (
          <nav className={styles.searchResults} aria-label={language === "zh" ? "搜索结果" : "Search results"}>
            {searchHits.map((hit) => (
              <VButton
                key={`${hit.groupId}:${hit.pageId}:${hit.sectionId ?? ""}:${hit.fieldId ?? ""}:${hit.title}`}
                className={styles.searchHit}
                contentLayout="plain"
                variant="ghost"
                onPress={() => selectHit(hit)}
              >
                <span>{hit.title}</span>
                {hit.valueSummary ? (
                  <small data-testid="config-search-hit-value">{hit.valueSummary}</small>
                ) : null}
                <small>{hit.detail}</small>
              </VButton>
            ))}
          </nav>
        ) : searchQuery.trim() ? (
          <div className={styles.searchResults} role="status">
            <span>{language === "zh" ? "没有匹配设置" : "No matching settings"}</span>
            <VButton variant="ghost" onPress={() => setSearchQuery("")}>
              {language === "zh" ? "清空搜索" : "Clear search"}
            </VButton>
          </div>
        ) : null}
      </div>
      <div className={styles.status} role="status">
        <span>{language === "zh" ? "配置状态" : "Config status"}</span>
        <strong className={styles.statusValue}>{statusLabel}</strong>
      </div>
      <nav className={styles.groupNav} aria-label={language === "zh" ? "设置分区" : "Settings groups"}>
        {onShowAll ? <VButton className={!activeGroupId ? `${styles.groupButton} ${styles.groupButtonActive}` : styles.groupButton}
          contentLayout="plain" variant="ghost" aria-pressed={!activeGroupId} onPress={onShowAll}>
          {language === "zh" ? "全部设置" : "All settings"}
        </VButton> : null}
        {groups.map((group) => (
          <VButton
            key={group.id}
            className={group.id === activeGroupId ? `${styles.groupButton} ${styles.groupButtonActive}` : styles.groupButton}
            contentLayout="plain"
            variant={group.id === activeGroupId ? "primary" : "ghost"}
            title={group.summary}
            aria-pressed={group.id === activeGroupId}
            onPress={() => onSelectGroup(group.id)}
          >
            <span>{group.title}</span>
          </VButton>
        ))}
      </nav>
    </aside>
  );
}

type ConfigSettingsPageTabsProps = {
  language: ConfigSettingsLanguage;
  group: ConfigSettingsGroup | null;
  activePageId: string;
  onSelectPage: (pageId: string) => void;
};

export function ConfigSettingsPageTabs({
  language,
  group,
  activePageId,
  onSelectPage,
}: ConfigSettingsPageTabsProps) {
  if (!group || group.pages.length <= 1) return null;
  return (
    <nav className={styles.pageTabs} aria-label={language === "zh" ? "当前分区页面" : "Current settings pages"}>
      {group.pages.map((page) => (
        <VButton
          key={page.id}
          className={page.id === activePageId ? `${styles.pageButton} ${styles.pageButtonActive}` : styles.pageButton}
          variant={page.id === activePageId ? "primary" : "ghost"}
          title={page.summary}
          aria-current={page.id === activePageId ? "page" : undefined}
          onPress={() => onSelectPage(page.id)}
        >
          {page.title}
        </VButton>
      ))}
    </nav>
  );
}
