import type { ReactNode } from "react";

import type { ConfigSummary } from "../api/types";
import { VButton } from "../components/vui";
import styles from "./ConfigSettingsNavigation.styles";

export type ConfigSettingsLanguage = "zh" | "en";

export type ConfigSettingsGroupId =
  | "overview-apply"
  | "workbench-interface"
  | "avatar-pet"
  | "models-profiles"
  | "runtime-context"
  | "tooling-diagnostics";

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
  "overview-apply",
  "workbench-interface",
  "avatar-pet",
  "models-profiles",
  "runtime-context",
  "tooling-diagnostics",
];

const PAGE_DEFINITIONS: Record<ConfigSettingsGroupId, readonly PageDefinition[]> = {
  "overview-apply": [
    { id: "overview-status", zh: "状态总览", en: "Status", members: ["overview"] },
    { id: "overview-changes", zh: "变更与保存", en: "Changes", members: ["diagnostics"] },
  ],
  "workbench-interface": [
    { id: "workbench-behavior", zh: "工作台行为", en: "Workbench", members: ["shell"] },
    { id: "workbench-ui", zh: "界面显示", en: "Interface", members: ["ui"] },
  ],
  "avatar-pet": [
    { id: "identity-user", zh: "用户资料", en: "User profile", members: ["user-profile"] },
    { id: "identity-avatar", zh: "终端形象", en: "Avatar", members: ["avatar"] },
    { id: "identity-pet", zh: "陪伴体", en: "Companion", members: ["pet"] },
  ],
  "models-profiles": [
    { id: "model-connection", zh: "模型连接", en: "Connections", members: ["models"] },
    { id: "model-discovery", zh: "模型发现", en: "Discovery", members: ["llm-discovery"] },
  ],
  "runtime-context": [
    { id: "runtime-context", zh: "上下文压缩", en: "Context", members: ["context-compression"] },
    { id: "runtime-analysis", zh: "分析", en: "Analysis", members: ["analysis"] },
  ],
  "tooling-diagnostics": [
    { id: "tooling-access", zh: "工具与权限", en: "Tools & access", members: ["security", "network", "parser"] },
    { id: "tooling-logs", zh: "日志与调试", en: "Logs & debug", members: ["log", "debug"] },
    { id: "tooling-git", zh: "Git 提交", en: "Git commits", members: ["git-commit-model", "git-commit-prompt"] },
    { id: "tooling-health", zh: "健康诊断", en: "Health", members: ["health-diagnostics"] },
    { id: "tooling-raw", zh: "原始配置", en: "Raw config", members: ["draft"] },
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
  const group = groups.find((candidate) => candidate.id === requestedGroupId) ?? groups[0] ?? null;
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
  headerAction,
}: ConfigSettingsSidebarProps) {
  return (
    <aside className={styles.sidebar}>
      <header className={styles.sidebarHeader}>
        <p className={styles.eyebrow}>{language === "zh" ? "设置" : "Settings"}</p>
        <h2 className={styles.title}>{title}</h2>
        <p className={styles.subtitle} title={subtitleHint}>{subtitle}</p>
        {headerAction}
      </header>
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
  if (!group) return null;
  return (
    <nav className={styles.pageTabs} aria-label={language === "zh" ? "当前分区页面" : "Current settings pages"}>
      {group.pages.map((page) => (
        <VButton
          key={page.id}
          className={page.id === activePageId ? `${styles.pageButton} ${styles.pageButtonActive}` : styles.pageButton}
          variant={page.id === activePageId ? "primary" : "ghost"}
          aria-current={page.id === activePageId ? "page" : undefined}
          onPress={() => onSelectPage(page.id)}
        >
          {page.title}
        </VButton>
      ))}
    </nav>
  );
}
