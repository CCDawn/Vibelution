// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  { id: "shortcuts", title: "快捷键", summary: "全局快捷键" },
  { id: "ui", title: "界面", summary: "界面显示" },
  { id: "user-profile", title: "用户信息", summary: "用户资料" },
  { id: "avatar", title: "终端形象", summary: "终端形象" },
  { id: "pet", title: "宠物", summary: "陪伴体" },
  { id: "models", title: "模型库", summary: "模型连接" },
  { id: "context-compression", title: "上下文压缩", summary: "上下文压缩" },
  { id: "session-recovery", title: "会话恢复", summary: "恢复设置" },
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
  it("projects registered sections into the approved categories while retaining group IDs", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");

    expect(groups).toHaveLength(6);
    expect(groups.map((group) => group.id)).toEqual([
      "models-profiles",
      "workbench-interface",
      "avatar-pet",
      "runtime-context",
      "tooling-diagnostics",
      "overview-apply",
    ]);
    expect(groups.find((group) => group.id === "overview-apply")?.pages).toEqual([
      expect.objectContaining({ id: "overview-save", memberSectionIds: ["overview", "diagnostics"] }),
    ]);
    expect(groups.find((group) => group.id === "workbench-interface")?.pages).toEqual([
      expect.objectContaining({ id: "workbench-interface", memberSectionIds: ["shell", "ui"] }),
      expect.objectContaining({ id: "workbench-shortcuts", memberSectionIds: ["shortcuts"] }),
    ]);
    expect(groups.find((group) => group.id === "avatar-pet")?.pages).toEqual([
      expect.objectContaining({ id: "identity-profile", memberSectionIds: ["user-profile"] }),
      expect.objectContaining({ id: "personal-assistant", memberSectionIds: ["avatar", "pet"] }),
    ]);
    expect(groups.find((group) => group.id === "runtime-context")?.pages).toEqual([
      expect.objectContaining({ id: "runtime-context", memberSectionIds: ["context-compression", "session-recovery"] }),
    ]);
    expect(groups.find((group) => group.id === "tooling-diagnostics")?.pages).toEqual(
      [
        expect.objectContaining({ id: "tooling-network", memberSectionIds: ["network", "parser"] }),
        expect.objectContaining({ id: "tooling-security", memberSectionIds: ["security"] }),
        expect.objectContaining({ id: "tooling-health", memberSectionIds: ["health-diagnostics", "log", "debug"] }),
        expect.objectContaining({ id: "tooling-git", memberSectionIds: ["git-commit-model", "git-commit-prompt", "analysis", "draft"] }),
      ],
    );
  });

  it("omits redundant page tabs when a settings group has one combined page", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const modelsGroup = groups.find((group) => group.id === "models-profiles") ?? null;
    const modelsMarkup = renderToStaticMarkup(
      <ConfigSettingsPageTabs
        language="zh"
        group={modelsGroup}
        activePageId="model-connection"
        onSelectPage={() => undefined}
      />,
    );

    expect(modelsMarkup).toBe("");

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

    const overviewGroup = groups.find((group) => group.id === "overview-apply") ?? null;
    const overviewMarkup = renderToStaticMarkup(
      <ConfigSettingsPageTabs
        language="zh"
        group={overviewGroup}
        activePageId="overview-save"
        onSelectPage={() => undefined}
      />,
    );

    expect(overviewMarkup).toBe("");
  });

  it("shows page tabs with the shortcuts page when the workbench group has two pages", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const workbenchGroup = groups.find((group) => group.id === "workbench-interface") ?? null;
    const markup = renderToStaticMarkup(
      <ConfigSettingsPageTabs
        language="zh"
        group={workbenchGroup}
        activePageId="workbench-shortcuts"
        onSelectPage={() => undefined}
      />,
    );

    expect(markup).toContain("外观与交互");
    expect(markup).toContain("快捷键");
    expect(markup).toContain('aria-current="page"');
  });

  it("falls back to the requested group's first page", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const selection = resolveConfigSettingsSelection(groups, "models-profiles", "missing");

    expect(selection.group?.id).toBe("models-profiles");
    expect(selection.page?.id).toBe("model-connection");
  });

  it("defaults an empty selection to model connections", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const selection = resolveConfigSettingsSelection(groups, "", "");

    expect(selection.group?.id).toBe("models-profiles");
    expect(selection.page?.id).toBe("model-connection");
  });

  it("renders direct category entries, a VUI mobile selector and one current page", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const activeGroup = groups.find((group) => group.id === "tooling-diagnostics") ?? null;
    const sidebarMarkup = renderToStaticMarkup(
      <ConfigSettingsSidebar
        language="zh"
        title="设置"
        subtitle="统一配置工作台"
        subtitleHint="配置按使用场景分组，修改后统一保存"
        statusLabel="已同步"
        groups={groups}
        activeGroupId="tooling-diagnostics"
        activePageId="tooling-health"
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

    expect(sidebarMarkup).toContain("配置管理");
    expect(sidebarMarkup).toContain("个人资料");
    expect(sidebarMarkup).toContain("个人助理");
    expect(sidebarMarkup).toContain("搜索设置");
    expect(sidebarMarkup).toContain('data-vui="contextual-hint"');
    expect(sidebarMarkup).toContain('role="combobox"');
    expect(sidebarMarkup).toContain('aria-label="设置分类"');
    expect(sidebarMarkup).toContain('data-vui-select-trigger="true"');
    expect(sidebarMarkup).not.toContain('title="配置按使用场景分组，修改后统一保存"');
    // Plain native titles keep pointer entry from remounting a navigation target.
    expect(componentSource).toContain("title={page.summary}");
    expect(componentSource).not.toContain("tooltip={page.summary}");
    expect(sidebarMarkup.match(/data-vui="button"/g)?.length ?? 0).toBe(groups.flatMap((group) => group.pages).length);
    expect(sidebarMarkup.match(/aria-current="page"/g)).toHaveLength(1);
    expect(sidebarMarkup).toMatch(/aria-current="page"[^>]*>.*?<span>日志与诊断<\/span>/);
    expect(tabsMarkup).toContain("网络与解析");
    expect(tabsMarkup).toContain("安全保护");
    expect(tabsMarkup).toContain("日志与诊断");
    expect(tabsMarkup).toContain("高级维护");
    expect(tabsMarkup).toContain('aria-current="page"');
    expect(tabsMarkup.match(/data-vui="button"/g)?.length ?? 0).toBe(activeGroup?.pages.length ?? 0);
    expect(styles.groupButton).toContain("!min-h-9");
    expect(styles.pageButton).not.toContain("min-h-10");
    expect(styles.sidebar).toContain("w-full");
    expect(styles.groupNav).toContain("max-[720px]:hidden");
    expect(styles.mobileCategory).toContain("max-[720px]:grid");
    expect(styles.pageTabs).toContain("overflow-x-auto");
    expect(componentSource).not.toContain(["@heroui", "react"].join("/"));
  });

  it("resolves legacy category URLs and section focus to the new owner", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    expect(resolveConfigSettingsSelection(groups, "tooling-diagnostics", "tooling-access").page?.id).toBe("tooling-network");
    expect(resolveConfigSettingsSelection(groups, "tooling-diagnostics", "tooling-access", "security").page?.id).toBe("tooling-security");
    expect(resolveConfigSettingsSelection(groups, "avatar-pet", "identity-profile", "pet").page?.id).toBe("personal-assistant");
    const analysis = resolveConfigSettingsSelection(groups, "runtime-context", "runtime-context", "analysis");
    expect(analysis.group?.id).toBe("tooling-diagnostics");
    expect(analysis.page?.id).toBe("tooling-git");
    expect(resolveConfigSettingsSelection([], "", "")).toEqual({ group: null, page: null });
  });
});

let root: Root | undefined;
let container: HTMLDivElement;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  container = document.createElement("div");
  document.body.append(container);
});
afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  container.remove();
  vi.unstubAllGlobals();
});

async function mountSidebar(onNavigate = vi.fn(), onShowAll = vi.fn()) {
  await act(async () => {
    root = createRoot(container);
    root.render(<ConfigSettingsSidebar
      language="zh" title="设置" subtitle="配置" statusLabel="已同步"
      groups={buildConfigSettingsGroups(sections, groupCopy, "zh")}
      activeGroupId="workbench-interface" activePageId="workbench-shortcuts"
      onSelectGroup={vi.fn()} onNavigate={onNavigate} onShowAll={onShowAll}
      searchDocuments={[{
        groupId: "avatar-pet", pageId: "personal-assistant", sectionId: "pet", fieldId: "pet.name",
        title: "助理称呼", detail: "个人助理", haystack: "助理称呼", titleHaystack: "助理称呼", valueHaystack: "",
      }]}
    />);
  });
  return { onNavigate, onShowAll };
}

describe("direct settings category interactions", () => {
  it("opens each category with one click and keeps the full settings entry", async () => {
    const { onNavigate, onShowAll } = await mountSidebar();
    const nav = container.querySelector('nav[aria-label="设置分类"]')!;
    const button = Array.from(nav.querySelectorAll("button")).find((node) => node.textContent === "个人助理")!;
    await act(async () => button.click());
    expect(onNavigate).toHaveBeenCalledExactlyOnceWith("avatar-pet", "personal-assistant");
    expect(nav.querySelector('[aria-current="page"]')?.textContent).toBe("快捷键");
    const all = Array.from(nav.querySelectorAll("button")).at(-1)!;
    expect(all.textContent).toBe("全部设置");
    await act(async () => all.click());
    expect(onShowAll).toHaveBeenCalledOnce();
  });

  it("navigates directly from the VUI mobile category selector and keeps category context", async () => {
    const { onNavigate } = await mountSidebar();
    const select = container.querySelector<HTMLButtonElement>('[role="combobox"][aria-label="设置分类"]')!;
    expect(select.textContent).toContain("快捷键");
    await act(async () => select.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
    const options = [...document.querySelectorAll<HTMLElement>('[role="option"]')];
    expect(new Set(options.map((option) => option.getAttribute("title")).filter(Boolean))).toEqual(new Set(["工作台", "Agent", "系统"]));
    const option = options.find((item) => item.textContent?.includes("安全保护"))!;
    await act(async () => {
      option.click();
    });
    expect(onNavigate).toHaveBeenCalledExactlyOnceWith("tooling-diagnostics", "tooling-security");
  });

  it("keeps the empty all-settings option actionable in the mobile selector", async () => {
    const { onNavigate, onShowAll } = await mountSidebar();
    const select = container.querySelector<HTMLButtonElement>('[role="combobox"][aria-label="设置分类"]')!;
    await act(async () => select.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
    const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')]
      .find((item) => item.textContent?.trim() === "全部设置")!;
    await act(async () => option.click());
    expect(onShowAll).toHaveBeenCalledOnce();
    expect(onNavigate).not.toHaveBeenCalled();
  });

  it("preserves field-level search navigation across the category split", async () => {
    const { onNavigate } = await mountSidebar();
    const input = container.querySelector("input")!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(input, "助理称呼");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const hit = container.querySelector('nav[aria-label="搜索结果"] button') as HTMLButtonElement;
    expect(hit).not.toBeNull();
    await act(async () => hit.click());
    expect(onNavigate).toHaveBeenCalledExactlyOnceWith("avatar-pet", "personal-assistant", "pet", "pet.name");
  });
});
