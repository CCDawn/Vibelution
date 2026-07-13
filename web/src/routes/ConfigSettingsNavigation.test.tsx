import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConfigSummary } from "../api/types";
import {
  buildConfigSettingsGroups,
  ConfigSettingsPageTabs,
  ConfigSettingsSidebar,
  resolveConfigSettingsSelection,
  type ConfigSettingsGroupCopy,
} from "./ConfigSettingsNavigation";
import componentSource from "./ConfigSettingsNavigation.tsx?raw";
import styles from "./ConfigSettingsNavigation.styles";

const sections: ConfigSummary["sections"] = [
  { id: "overview", title: "配置源", summary: "配置状态" },
  { id: "diagnostics", title: "诊断", summary: "保存前诊断" },
  { id: "shell", title: "工作台默认项", summary: "工作台行为" },
  { id: "ui", title: "界面", summary: "界面显示" },
  { id: "user-profile", title: "用户信息", summary: "用户资料" },
  { id: "avatar", title: "终端形象", summary: "终端形象" },
  { id: "pet", title: "宠物", summary: "陪伴体" },
  { id: "models", title: "模型库", summary: "模型连接" },
  { id: "llm-discovery", title: "模型发现", summary: "模型发现" },
  { id: "context-compression", title: "上下文压缩", summary: "上下文压缩" },
  { id: "analysis", title: "分析", summary: "分析" },
  { id: "security", title: "安全", summary: "权限设置" },
  { id: "network", title: "网络", summary: "网络设置" },
  { id: "parser", title: "解析器", summary: "解析器设置" },
  { id: "log", title: "日志", summary: "日志设置" },
  { id: "debug", title: "调试", summary: "调试设置" },
  { id: "git-commit-model", title: "Git 提交模型", summary: "提交模型" },
  { id: "git-commit-prompt", title: "Git 提交提示词", summary: "提交提示词" },
  { id: "health-diagnostics", title: "健康诊断", summary: "运行诊断" },
  { id: "draft", title: "高级配置检查", summary: "原始配置" },
];

const groupCopy: ConfigSettingsGroupCopy = {
  "overview-apply": { title: "总览与保存", summary: "状态与保存" },
  "workbench-interface": { title: "界面与工作台", summary: "工作台与界面" },
  "avatar-pet": { title: "用户、终端形象与陪伴体", summary: "用户与形象" },
  "models-profiles": { title: "模型库", summary: "模型连接与发现" },
  "runtime-context": { title: "运行时与上下文", summary: "运行时设置" },
  "tooling-diagnostics": { title: "工具与诊断", summary: "工具和诊断" },
};

describe("ConfigSettingsNavigation", () => {
  it("builds six desktop groups and layers tooling into daily, troubleshooting, and advanced pages", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");

    expect(groups).toHaveLength(6);
    expect(groups.find((group) => group.id === "workbench-interface")?.pages).toEqual([
      expect.objectContaining({ id: "workbench-interface", memberSectionIds: ["shell", "ui"] }),
    ]);
    expect(groups.find((group) => group.id === "runtime-context")?.pages).toEqual([
      expect.objectContaining({ id: "runtime-context", memberSectionIds: ["context-compression", "analysis"] }),
    ]);
    expect(groups.find((group) => group.id === "tooling-diagnostics")?.pages).toEqual(
      [
        expect.objectContaining({ id: "tooling-access", memberSectionIds: ["security", "network", "parser"] }),
        expect.objectContaining({ id: "tooling-health", memberSectionIds: ["health-diagnostics", "log", "debug"] }),
        expect.objectContaining({ id: "tooling-git", memberSectionIds: ["git-commit-model", "git-commit-prompt", "draft"] }),
      ],
    );
  });

  it("omits redundant page tabs when a settings group has one combined page", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const workbenchGroup = groups.find((group) => group.id === "workbench-interface") ?? null;
    const markup = renderToStaticMarkup(
      <ConfigSettingsPageTabs
        language="zh"
        group={workbenchGroup}
        activePageId="workbench-interface"
        onSelectPage={() => undefined}
      />,
    );

    expect(markup).toBe("");

    const runtimeGroup = groups.find((group) => group.id === "runtime-context") ?? null;
    const runtimeMarkup = renderToStaticMarkup(
      <ConfigSettingsPageTabs
        language="zh"
        group={runtimeGroup}
        activePageId="runtime-context"
        onSelectPage={() => undefined}
      />,
    );

    expect(runtimeMarkup).toBe("");
  });

  it("falls back to the requested group's first page", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const selection = resolveConfigSettingsSelection(groups, "models-profiles", "missing");

    expect(selection.group?.id).toBe("models-profiles");
    expect(selection.page?.id).toBe("model-connection");
  });

  it("renders large group buttons and an accessible current page", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const activeGroup = groups.find((group) => group.id === "tooling-diagnostics") ?? null;
    const sidebarMarkup = renderToStaticMarkup(
      <ConfigSettingsSidebar
        language="zh"
        title="设置"
        subtitle="统一配置工作台"
        statusLabel="已同步"
        groups={groups}
        activeGroupId="tooling-diagnostics"
        onSelectGroup={() => undefined}
      />,
    );
    const tabsMarkup = renderToStaticMarkup(
      <ConfigSettingsPageTabs
        language="zh"
        group={activeGroup}
        activePageId="tooling-health"
        onSelectPage={() => undefined}
      />,
    );

    expect(sidebarMarkup).toContain("总览与保存");
    expect(sidebarMarkup).toContain("工具与诊断");
    expect(sidebarMarkup).toMatch(/aria-pressed="true"[^>]*><span>工具与诊断<\/span>/);
    expect(tabsMarkup).toContain("日常工具");
    expect(tabsMarkup).toContain("排障中心");
    expect(tabsMarkup).toContain("高级维护");
    expect(tabsMarkup).not.toContain("日志与调试");
    expect(tabsMarkup).not.toContain("原始配置");
    expect(tabsMarkup).toContain('aria-current="page"');
    expect(styles.groupButton).toContain("min-h-11");
    expect(styles.pageButton).toContain("min-h-10");
    expect(styles.sidebar).toContain("clamp(15.5rem,17vw,18rem)");
    expect(styles.pageTabs).toContain("overflow-x-auto");
    expect(componentSource).not.toContain(["@heroui", "react"].join("/"));
  });
});
