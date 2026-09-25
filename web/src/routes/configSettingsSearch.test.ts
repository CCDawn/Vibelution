import { describe, expect, it } from "vitest";

import type { ConfigEditorSection } from "../api/types";

import { buildConfigSettingsGroups, type ConfigSettingsGroupCopy } from "./ConfigSettingsNavigation";
import {
  buildConfigSettingsNavigationSearch,
  buildConfigSettingsSearchIndex,
  resolveConfigSettingsFocus,
  searchConfigSettings,
} from "./configSettingsSearch";

const sections = [
  { id: "overview", title: "配置源", summary: "配置状态" },
  { id: "diagnostics", title: "诊断", summary: "保存前诊断" },
  { id: "shell", title: "工作台默认项", summary: "工作台行为" },
  { id: "ui", title: "界面", summary: "界面显示" },
  { id: "user-profile", title: "用户信息", summary: "用户资料" },
  { id: "avatar", title: "终端形象", summary: "终端形象" },
  { id: "pet", title: "宠物", summary: "陪伴体" },
  { id: "models", title: "模型库", summary: "模型连接" },
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

const baseEditorMeta = {
  "ui.workbench_theme": { path: "ui.workbench_theme", label: "工作台主题", hint: "工作台外观", kind: "select", badge: "Option", options: [] },
  "pet.name": { path: "pet.name", label: "陪伴体名称", hint: "显示名", kind: "text", badge: "Text", options: [] },
} as const;

describe("configSettingsSearch", () => {
  it("resets focus de-duplication when navigation leaves a focused section", () => {
    const focused = resolveConfigSettingsFocus("", "runtime-context", "runtime-context", "context-compression");
    expect(focused.shouldFocus).toBe(true);
    const cleared = resolveConfigSettingsFocus(focused.nextKey, "models-profiles", "model-connection", "");
    expect(cleared).toEqual({ nextKey: "", shouldFocus: false });
    const revisited = resolveConfigSettingsFocus(cleared.nextKey, "runtime-context", "runtime-context", "context-compression");
    expect(revisited.shouldFocus).toBe(true);
  });

  it("preserves return context while writing the selected page and focus section", () => {
    const search = buildConfigSettingsNavigationSearch(
      "returnTo=%2Fagents%3Fpane%3Dconfig&returnLabel=agents&focus=old",
      "runtime-context",
      "runtime-context",
      "context-compression",
    );
    const params = new URLSearchParams(search);
    expect(params.get("section")).toBe("runtime-context");
    expect(params.get("page")).toBe("runtime-context");
    expect(params.get("focus")).toBe("context-compression");
    expect(params.get("returnLabel")).toBe("agents");

    const withoutFocus = new URLSearchParams(buildConfigSettingsNavigationSearch(params, "models-profiles", "model-connection"));
    expect(withoutFocus.get("focus")).toBeNull();
    expect(withoutFocus.get("returnTo")).toBe("/agents?pane=config");
  });

  it("jumps API Key and background queries to the owning settings page", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const documents = buildConfigSettingsSearchIndex({
      groups,
      editorSections,
      editorMeta: baseEditorMeta,
    });

    // 字段行在设置页展示前端双语文案（configSectionFieldCopy 优先于后端 label），
    // 搜索结果标题与行标题保持一致；后端 label 仍留在 haystack 内可命中。
    expect(searchConfigSettings(documents, "主题")[0]).toEqual(
      expect.objectContaining({ groupId: "workbench-interface", pageId: "workbench-interface", title: "工作台背景", fieldId: "ui.workbench_theme" }),
    );
    expect(searchConfigSettings(documents, "模型")[0]).toEqual(
      expect.objectContaining({ groupId: "models-profiles" }),
    );
    expect(searchConfigSettings(documents, "陪伴")[0]).toEqual(
      expect.objectContaining({ groupId: "avatar-pet", pageId: "identity-profile" }),
    );
    expect(searchConfigSettings(documents, "")).toEqual([]);
  });

  it("builds field-level documents with fieldId, breadcrumb and safe value summary", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const wideEditorSections: ConfigEditorSection[] = [
      ...editorSections,
      { id: "models", path: "models", title: "模型库", summary: "模型连接", fieldCount: 3 },
      { id: "network", path: "network", title: "网络", summary: "网络设置", fieldCount: 2 },
    ];
    const documents = buildConfigSettingsSearchIndex({
      groups,
      editorSections: wideEditorSections,
      editorMeta: {
        ...baseEditorMeta,
        "pet.heart.active_rate": {
          path: "pet.heart.active_rate", label: "活跃心跳频率", hint: "活跃心跳", kind: "number", badge: "Seconds", options: [],
        },
        "pet.gene": { path: "pet.gene", label: "基础能力", hint: "继承", kind: "object", badge: "Object", options: [] },
        "models.main.api_key": {
          path: "models.main.api_key", label: "API Key", hint: "模型密钥", kind: "secret", badge: "Secret", options: [],
        },
        "network.proxy_url": {
          path: "network.proxy_url", label: "代理地址", hint: "HTTP 代理", kind: "url", badge: "URL", options: [],
        },
      },
      configValues: {
        ui: { workbench_theme: "midnight" },
        pet: { name: "团子", heart: { active_rate: 12 }, gene: { inherit_from_model: true } },
        models: { main: { api_key: "sk-super-secret-value" } },
        network: { proxy_url: "http://127.0.0.1:7890" },
      },
      language: "zh",
    });

    // 叶子字段：fieldId + 面包屑 + 值摘要。
    const theme = documents.find((doc) => doc.fieldId === "ui.workbench_theme");
    expect(theme).toEqual(
      expect.objectContaining({ groupId: "workbench-interface", sectionId: "ui", title: "工作台背景" }),
    );
    expect(theme?.detail).toContain("界面与工作台");
    expect(theme?.detail).toContain("工作台与界面");
    expect(theme?.detail).toContain("界面");
    expect(theme?.valueSummary).toBe("midnight");

    const activeRate = documents.find((doc) => doc.fieldId === "pet.heart.active_rate");
    expect(activeRate?.valueSummary).toBe("12");

    // object 类 meta 不生成字段级 fieldId（跳分区顶部）。
    expect(documents.find((doc) => doc.fieldId === "pet.gene")).toBeUndefined();

    // 红线：secret 字段值绝不进索引，也没有值摘要。
    const secret = documents.find((doc) => doc.fieldId === "models.main.api_key");
    expect(secret).toBeDefined();
    expect(secret?.valueSummary ?? "").toBe("");
    expect(secret?.haystack).not.toContain("sk-super-secret-value");
    expect(secret?.valueHaystack).toBe("");

    // 双语：en label 也进 haystack，中查英/英查中都能命中同一字段。
    const proxy = documents.find((doc) => doc.fieldId === "network.proxy_url");
    expect(searchConfigSettings(documents, "proxy")[0]?.fieldId).toBe("network.proxy_url");
    expect(searchConfigSettings(documents, "代理")[0]?.fieldId).toBe("network.proxy_url");
    expect(proxy?.valueSummary).toBe("http://127.0.0.1:7890");
  });

  it("omits or truncates unsafe and long values in field summaries", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const documents = buildConfigSettingsSearchIndex({
      groups,
      editorSections: [
        ...editorSections,
        { id: "security", path: "security", title: "安全", summary: "安全限制", fieldCount: 2 },
        { id: "network", path: "network", title: "网络", summary: "网络设置", fieldCount: 2 },
      ],
      editorMeta: {
        "pet.name": { path: "pet.name", label: "陪伴体名称", hint: "显示名", kind: "text", badge: "Text", options: [] },
        "security.allowed_directories": {
          path: "security.allowed_directories", label: "允许目录", hint: "目录", kind: "string_list", badge: "List", options: [],
        },
        "network.timeout": { path: "network.timeout", label: "请求超时", hint: "超时", kind: "number", badge: "Seconds", options: [] },
      },
      configValues: {
        pet: { name: "一".repeat(50) },
        security: { allowed_directories: ["C:/workspace"] },
        network: { timeout: 30 },
      },
      language: "zh",
    });
    const name = documents.find((doc) => doc.fieldId === "pet.name");
    expect(name?.valueSummary).toBe(`${"一".repeat(32)}…`);
    expect(name?.haystack).not.toContain("一".repeat(50));
    // string_list 不给值摘要。
    expect(documents.find((doc) => doc.fieldId === "security.allowed_directories")?.valueSummary ?? "").toBe("");
    expect(documents.find((doc) => doc.fieldId === "network.timeout")?.valueSummary).toBe("30");
  });

  it("ranks field-name hits above value hits above description hits within the widened limit", () => {
    const groups = buildConfigSettingsGroups(sections, groupCopy, "zh");
    const documents = buildConfigSettingsSearchIndex({
      groups,
      editorSections,
      editorMeta: {
        "pet.name": { path: "pet.name", label: "陪伴体名称", hint: "显示名", kind: "text", badge: "Text", options: [] },
        "ui.language": { path: "ui.language", label: "界面语言", hint: "工作台语言", kind: "select", badge: "Option", options: [{ value: "zh", label: "中文" }] },
      },
      configValues: { pet: { name: "语言学习助手" }, ui: { language: "zh" } },
      language: "zh",
    });

    // 「语言」同时命中字段名（ui.language 标题）与字段值（pet.name 的值）：
    // 字段名命中 > 值命中。
    const hits = searchConfigSettings(documents, "语言", 12);
    expect(hits[0]?.fieldId).toBe("ui.language");
    expect(hits[0]?.valueSummary).toBe("中文");
    const nameHit = hits.find((hit) => hit.fieldId === "pet.name");
    expect(nameHit?.valueSummary).toBe("语言学习助手");
    expect(hits.indexOf(nameHit!)).toBeGreaterThan(0);

    // 上限放宽到 12：12 条同层命中全部返回。
    const many = Array.from({ length: 12 }, (_, index) => [
      `pet.sound.field_${index}`,
      {
        path: `pet.sound.field_${index}`,
        label: `特殊标记字段${index}`,
        hint: "",
        kind: "text",
        badge: "Text",
        options: [],
      },
    ] as const);
    const wideDocuments = buildConfigSettingsSearchIndex({
      groups,
      editorSections,
      editorMeta: Object.fromEntries(many),
      language: "zh",
    });
    expect(searchConfigSettings(wideDocuments, "特殊标记", 12)).toHaveLength(12);
    expect(searchConfigSettings(wideDocuments, "特殊标记", 12)[0]?.fieldId).toBe("pet.sound.field_0");
  });

  it("carries an optional field deep-link parameter in the navigation search", () => {
    const search = buildConfigSettingsNavigationSearch(
      "",
      "workbench-interface",
      "workbench-interface",
      "ui",
      "ui.workbench_theme",
    );
    const params = new URLSearchParams(search);
    expect(params.get("section")).toBe("workbench-interface");
    expect(params.get("focus")).toBe("ui");
    expect(params.get("field")).toBe("ui.workbench_theme");

    const withoutField = new URLSearchParams(buildConfigSettingsNavigationSearch(params, "workbench-interface", "workbench-shortcuts", "shortcuts"));
    expect(withoutField.get("field")).toBeNull();
    const sectionOnly = new URLSearchParams(buildConfigSettingsNavigationSearch("", "avatar-pet", "identity-profile", "pet", "pet.name"));
    // 有 field 必须同时有 focus（字段依附分区）；只给 field 不给 focus 时不写 field。
    const orphanField = new URLSearchParams(buildConfigSettingsNavigationSearch("", "avatar-pet", "identity-profile", "", "pet.name"));
    expect(sectionOnly.get("field")).toBe("pet.name");
    expect(orphanField.get("field")).toBeNull();
  });
});
