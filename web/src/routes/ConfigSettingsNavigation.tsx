import { useMemo, useState, type ReactNode } from "react";
import { Activity, Bot, Braces, BrainCircuit, FileSliders, Globe, Keyboard, Palette, Plug, ShieldCheck, User } from "lucide-react";

import type { ConfigSummary } from "../api/types";
import { VButton, VNativeInput, VNativeSelect, VPanelHeader } from "../components/vui";
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

/** The backend registers sections; this table only projects registered IDs into
 * the approved frontend categories. Unknown sections still follow annotations. */
const FALLBACK_GROUP_ID: ConfigSettingsGroupId = "tooling-diagnostics";
const FALLBACK_PAGE_ID = "tooling-other";
const PAGE_DESCRIPTIONS: Record<string, readonly [string, string]> = {
  "workbench-interface": ["调整工作台的显示方式和默认审核习惯。", "Adjust workbench appearance and default review behavior."],
  "workbench-shortcuts": ["修改全局快捷键，保存在本机并立即生效。", "Customize global keyboard shortcuts on this device."],
  "identity-profile": ["管理显示信息，以及提供给 Agent 的背景与偏好。", "Manage your display information and context shared with Agents."],
  "personal-assistant": ["管理桌面显示、助理形象与陪伴偏好。", "Manage desktop visibility, appearance, and companion preferences."],
  "model-connection": ["连接服务商，管理密钥与可用模型。", "Connect providers and manage credentials and available models."],
  "runtime-context": ["控制上下文压缩和重启后的会话恢复。", "Configure context compression and session recovery after restart."],
  "tooling-network": ["管理代理、请求参数与模型响应解析。", "Manage proxy settings, requests, and model response parsing."],
  "tooling-security": ["管理文件和命令保护；工具授权在各 Agent 中配置。", "Protect files and commands. Configure tool permissions per Agent."],
  "tooling-health": ["查看运行状态、日志和排障信息。", "Inspect runtime health, logs, and diagnostic information."],
  "tooling-git": ["管理低频参数、Git 助手和完整配置。", "Manage advanced parameters, Git assistance, and the full configuration."],
  "overview-save": ["查看配置位置、检查问题和迁移兼容状态。", "Inspect configuration paths, issues, and migration compatibility."],
};

export function configSettingsPageDescription(page: ConfigSettingsPage | null, language: ConfigSettingsLanguage): string | undefined {
  return page ? PAGE_DESCRIPTIONS[page.id]?.[language === "zh" ? 0 : 1] ?? page.summary : undefined;
}

const PAGE_DEFINITIONS: Record<ConfigSettingsGroupId, readonly PageDefinition[]> = {
  "overview-apply": [
    { id: "overview-save", zh: "配置管理", en: "Configuration", members: ["overview", "diagnostics"] },
  ],
  "workbench-interface": [
    { id: "workbench-interface", zh: "外观与交互", en: "Appearance & interaction", members: ["shell", "ui"] },
    { id: "workbench-shortcuts", zh: "快捷键", en: "Keyboard shortcuts", members: ["shortcuts"] },
  ],
  "avatar-pet": [
    { id: "identity-profile", zh: "个人资料", en: "Personal profile", members: ["user-profile"] },
    { id: "personal-assistant", zh: "个人助理", en: "Personal assistant", members: ["avatar", "pet"] },
  ],
  "models-profiles": [
    { id: "model-connection", zh: "模型服务", en: "Model services", members: ["models"] },
  ],
  "runtime-context": [
    { id: "runtime-context", zh: "上下文与恢复", en: "Context & recovery", members: ["context-compression", "session-recovery"] },
  ],
  "tooling-diagnostics": [
    { id: "tooling-network", zh: "网络与解析", en: "Network & parsing", members: ["network", "parser"] },
    { id: "tooling-security", zh: "安全保护", en: "Security", members: ["security"] },
    { id: "tooling-health", zh: "日志与诊断", en: "Logs & diagnostics", members: ["health-diagnostics", "log", "debug"] },
    { id: "tooling-git", zh: "高级维护", en: "Advanced maintenance", members: ["git-commit-model", "git-commit-prompt", "analysis", "draft"] },
    { id: FALLBACK_PAGE_ID, zh: "其他设置", en: "Other settings", members: [] },
  ],
};

function projectedAnnotationPage(groupId: string | undefined, pageId: string | undefined): string | undefined {
  return groupId === "tooling-diagnostics" && pageId === "tooling-access" ? "tooling-network" : pageId;
}

export function buildConfigSettingsGroups(
  sections: ConfigSummary["sections"],
  groupCopy: ConfigSettingsGroupCopy,
  language: ConfigSettingsLanguage,
): ConfigSettingsGroup[] {
  const sectionMap = new Map(sections.map((section) => [section.id, section]));
  const placements = new Map<string, { groupId: ConfigSettingsGroupId; pageId: string }>();
  for (const groupId of GROUP_ORDER) {
    for (const page of PAGE_DEFINITIONS[groupId]) {
      for (const sectionId of page.members) placements.set(sectionId, { groupId, pageId: page.id });
    }
  }
  for (const section of sections) {
    if (placements.has(section.id)) continue;
    const groupId = GROUP_ORDER.find((candidate) => candidate === section.group);
    const pageId = projectedAnnotationPage(section.group, section.page);
    const hasDeclaredPage = groupId && PAGE_DEFINITIONS[groupId].some((page) => page.id === pageId);
    placements.set(section.id, hasDeclaredPage
      ? { groupId, pageId: pageId! }
      : { groupId: FALLBACK_GROUP_ID, pageId: FALLBACK_PAGE_ID });
  }

  return GROUP_ORDER.map((groupId) => ({
    id: groupId,
    title: groupCopy[groupId].title,
    summary: groupCopy[groupId].summary,
    pages: PAGE_DEFINITIONS[groupId].map((definition) => {
      // Keep familiar members in presentation order, append newcomers in backend order.
      const memberSectionIds = [
        ...definition.members.filter((id) => sectionMap.has(id)),
        ...sections.filter((section) => {
          const target = placements.get(section.id);
          return target?.groupId === groupId && target.pageId === definition.id && !definition.members.includes(section.id);
        }).map((section) => section.id),
      ];
      const members = memberSectionIds.map((id) => sectionMap.get(id)!);
      return {
        id: definition.id,
        title: language === "zh" ? definition.zh : definition.en,
        summary: members.length === 1 ? members[0].summary : members.map((section) => section.title).join(language === "zh" ? "、" : ", "),
        memberSectionIds,
      };
    }).filter((page) => page.memberSectionIds.length > 0),
  })).filter((group) => group.pages.length > 0);
}

export function resolveConfigSettingsSelection(
  groups: ConfigSettingsGroup[],
  requestedGroupId: string,
  requestedPageId: string,
  focusSectionId = "",
): { group: ConfigSettingsGroup | null; page: ConfigSettingsPage | null } {
  // Old deep links retain their section/field target after a category split.
  const focusedGroup = focusSectionId ? groups.find((candidate) => candidate.pages.some((page) => page.memberSectionIds.includes(focusSectionId))) : undefined;
  const group = focusedGroup ?? groups.find((candidate) => candidate.id === requestedGroupId)
    ?? groups.find((candidate) => candidate.id === DEFAULT_CONFIG_SETTINGS_GROUP_ID)
    ?? groups[0]
    ?? null;
  const pageId = projectedAnnotationPage(group?.id, requestedPageId);
  const page = group?.pages.find((candidate) => candidate.memberSectionIds.includes(focusSectionId))
    ?? group?.pages.find((candidate) => candidate.id === pageId) ?? group?.pages[0] ?? null;
  return { group, page };
}

const CATEGORY_ICONS: Record<string, typeof Palette> = {
  "workbench-interface": Palette,
  "workbench-shortcuts": Keyboard,
  "identity-profile": User,
  "personal-assistant": Bot,
  "model-connection": Plug,
  "runtime-context": BrainCircuit,
  "tooling-network": Globe,
  "tooling-security": ShieldCheck,
  "tooling-health": Activity,
  "tooling-git": Braces,
  "overview-save": FileSliders,
};

type ConfigSettingsSidebarProps = {
  language: ConfigSettingsLanguage;
  title: string;
  subtitle: string;
  subtitleHint?: string;
  statusLabel: string;
  groups: ConfigSettingsGroup[];
  activeGroupId: string;
  activePageId?: string;
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
  activePageId,
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

  const categories = [
    { title: language === "zh" ? "工作台" : "Workbench", pageIds: ["workbench-interface", "workbench-shortcuts", "identity-profile", "personal-assistant"] },
    { title: "Agent", pageIds: ["model-connection", "runtime-context", "tooling-network", "tooling-security"] },
    { title: language === "zh" ? "系统" : "System", pageIds: ["tooling-health", "tooling-git", "overview-save", "tooling-other"] },
  ].map((category) => ({
    ...category,
    entries: category.pageIds.flatMap((pageId) => groups.flatMap((group) => {
      const page = group.pages.find((candidate) => candidate.id === pageId);
      return page ? [{ group, page }] : [];
    })),
  })).filter((category) => category.entries.length > 0);
  const currentPageId = groups.find((group) => group.id === activeGroupId)?.pages.find((page) => page.id === activePageId)?.id
    ?? groups.find((group) => group.id === activeGroupId)?.pages[0]?.id ?? "";

  function navigateToPage(groupId: ConfigSettingsGroupId, pageId: string) {
    if (onNavigate) onNavigate(groupId, pageId);
    else onSelectGroup(groupId);
  }

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
      <label className={styles.mobileCategory}>
        <span className={styles.searchLabel}>{language === "zh" ? "设置分类" : "Settings category"}</span>
        <VNativeSelect
          aria-label={language === "zh" ? "设置分类" : "Settings category"}
          value={activeGroupId ? currentPageId : ""}
          onChange={(event) => {
            const pageId = event.target.value;
            if (!pageId) { onShowAll?.(); return; }
            const entry = categories.flatMap((category) => category.entries).find((candidate) => candidate.page.id === pageId);
            if (entry) navigateToPage(entry.group.id, entry.page.id);
          }}
        >
          {onShowAll ? <option value="">{language === "zh" ? "全部设置" : "All settings"}</option> : null}
          {categories.map((category) => (
            <optgroup key={category.title} label={category.title}>
              {category.entries.map(({ page }) => <option key={page.id} value={page.id}>{page.title}</option>)}
            </optgroup>
          ))}
        </VNativeSelect>
      </label>
      <nav className={styles.groupNav} aria-label={language === "zh" ? "设置分类" : "Settings categories"}>
        {categories.map((category) => (
          <div key={category.title} className={styles.categoryGroup}>
            <div className={styles.categoryLabel}>{category.title}</div>
            {category.entries.map(({ group, page }) => {
              const active = group.id === activeGroupId && page.id === currentPageId;
              const Icon = CATEGORY_ICONS[page.id];
              return (
                <VButton
                  key={page.id}
                  className={active ? `${styles.groupButton} ${styles.groupButtonActive}` : styles.groupButton}
                  contentLayout="plain"
                  variant="ghost"
                  title={page.summary}
                  aria-current={active ? "page" : undefined}
                  onPress={() => navigateToPage(group.id, page.id)}
                >
                  {Icon ? <Icon size={16} aria-hidden="true" /> : null}
                  <span>{page.title}</span>
                </VButton>
              );
            })}
          </div>
        ))}
        {onShowAll ? <VButton className={!activeGroupId ? `${styles.groupButton} ${styles.groupButtonActive}` : styles.groupButton}
          contentLayout="plain" variant="ghost" aria-current={!activeGroupId ? "page" : undefined} onPress={onShowAll}>
          <span>{language === "zh" ? "全部设置" : "All settings"}</span>
        </VButton> : null}
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
