import { describe, expect, it } from "vitest";

import type { ConfigEditorSection } from "../api/types";

import { buildConfigSettingsGroups, type ConfigSettingsGroupCopy } from "./ConfigSettingsNavigation";
import { buildConfigSettingsSearchIndex, searchConfigSettings } from "./configSettingsSearch";

const sections = [
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
  "models-profiles": { title: "模型连接", summary: "模型连接与发现" },
  "runtime-context": { title: "运行时与上下文", summary: "运行时设置" },
  "tooling-diagnostics": { title: "工具与诊断", summary: "工具和诊断" },
};

const editorSections: ConfigEditorSection[] = [
  { id: "ui", path: "ui", title: "界面", summary: "界面显示", fieldCount: 2 },
  { id: "pet", path: "pet", title: "宠物", summary: "陪伴体", fieldCount: 3 },
];

describe("configSettingsSearch", () => {
  it("jumps API Key and theme queries to the owning settings page", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const documents = buildConfigSettingsSearchIndex({
      groups,
      editorSections,
      editorMeta: {
        "ui.theme": { path: "ui.theme", label: "颜色主题", hint: "工作台外观", kind: "select", badge: "Option", options: [] },
        "pet.name": { path: "pet.name", label: "陪伴体名称", hint: "显示名", kind: "text", badge: "Text", options: [] },
      },
    });

    expect(searchConfigSettings(documents, "主题")[0]).toEqual(
      expect.objectContaining({ groupId: "workbench-interface", pageId: "workbench-interface", title: "颜色主题" }),
    );
    expect(searchConfigSettings(documents, "模型")[0]).toEqual(
      expect.objectContaining({ groupId: "models-profiles" }),
    );
    expect(searchConfigSettings(documents, "陪伴")[0]).toEqual(
      expect.objectContaining({ groupId: "avatar-pet", pageId: "identity-profile" }),
    );
    expect(searchConfigSettings(documents, "")).toEqual([]);
  });
});
