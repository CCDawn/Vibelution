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

const PAGE_DEFINITIONS: Record<ConfigSettingsGroupId, readonly PageDefinition[]> = {
  "overview-apply": [
    { id: "overview-save", zh: "总览与保存", en: "Overview & save", members: ["overview", "diagnostics"] },
  ],
  "workbench-interface": [
    { id: "workbench-interface", zh: "工作台与界面", en: "Workbench & interface", members: ["shell", "ui"] },
  ],
  "avatar-pet": [
    { id: "identity-profile", zh: "个人资料与陪伴体", en: "Profile & companion", members: ["user-profile", "avatar", "pet"] },
  ],
  "models-profiles": [
    { id: "model-connection", zh: "模型连接", en: "Connections", members: ["models"] },
    { id: "model-discovery", zh: "模型发现", en: "Discovery", members: ["llm-discovery"] },
  ],
  "runtime-context": [
    { id: "runtime-context", zh: "上下文与分析", en: "Context & analysis", members: ["context-compression", "analysis"] },
  ],
  "tooling-diagnostics": [
    { id: "tooling-access", zh: "日常工具", en: "Everyday tools", members: ["security", "network", "parser"] },
    { id: "tooling-health", zh: "排障中心", en: "Troubleshooting", members: ["health-diagnostics", "log", "debug"] },
    { id: "tooling-git", zh: "高级维护", en: "Advanced maintenance", members: ["git-commit-model", "git-commit-prompt", "draft"] },
  ],
};

export function buildConfigSettingsGroups(
  sections: ConfigSummary["sections"],
  groupCopy: ConfigSettingsGroupCopy,
  language: ConfigSettingsLanguage,
): ConfigSettingsGroup[] {
  const sectionMap = new Map(sections.map((section) => [section.id, section]));
  return GROUP_ORDER.map((groupId) => {
    const pages = PAGE_DEFINITIONS[groupId].map((definition) => {
      const memberSectionIds = definition.members.filter((sectionId) => sectionMap.has(sectionId));
      const members = memberSectionIds.map((sectionId) => sectionMap.get(sectionId)).filter(Boolean);
      return {
        id: definition.id,
        title: language === "zh" ? definition.zh : definition.en,
        summary: members.length === 1
          ? members[0]?.summary ?? ""
          : members.map((section) => section?.title).filter(Boolean).join(language === "zh" ? "、" : ", "),
        memberSectionIds,
      } satisfies ConfigSettingsPage;
    }).filter((page) => page.memberSectionIds.length > 0);
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
  onNavigate?: (groupId: ConfigSettingsGroupId, pageId: string) => void;
  searchDocuments?: ConfigSettingsSearchDocument[];
  headerAction?: ReactNode;
};

export function ConfigSettingsSidebar({
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
      onNavigate(hit.groupId, hit.pageId);
    } else {
      onSelectGroup(hit.groupId);
    }
  }

  return (
    <aside className={styles.sidebar} data-vui-region="config-settings-nav">
      <VPanelHeader
        className={styles.sidebarHeader}
        eyebrow={language === "zh" ? "设置" : "Settings"}
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
                key={`${hit.groupId}:${hit.pageId}:${hit.sectionId ?? ""}:${hit.title}`}
                className={styles.searchHit}
                contentLayout="plain"
                variant="ghost"
                onPress={() => selectHit(hit)}
              >
                <span>{hit.title}</span>
                <small>{hit.detail}</small>
              </VButton>
            ))}
          </nav>
        ) : null}
      </div>
      <div className={styles.status} role="status">
        <span>{language === "zh" ? "配置状态" : "Config status"}</span>
        <strong className={styles.statusValue}>{statusLabel}</strong>
      </div>
      <nav className={styles.groupNav} aria-label={language === "zh" ? "设置分区" : "Settings groups"}>
        {groups.map((group) => (
          <VButton
            key={group.id}
            className={group.id === activeGroupId ? `${styles.groupButton} ${styles.groupButtonActive}` : styles.groupButton}
            contentLayout="plain"
            variant={group.id === activeGroupId ? "primary" : "ghost"}
            tooltip={group.summary}
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
          tooltip={page.summary}
          aria-current={page.id === activePageId ? "page" : undefined}
          onPress={() => onSelectPage(page.id)}
        >
          {page.title}
        </VButton>
      ))}
    </nav>
  );
}
