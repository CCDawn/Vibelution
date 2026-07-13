import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import configRouteSource from "./src/routes/ConfigRoute.tsx?raw";
import configNavigationSource from "./src/routes/ConfigSettingsNavigation.tsx?raw";

const configRouteStylesSource = readFileSync(new URL("./src/routes/ConfigRoute.styles.ts", import.meta.url), "utf-8");

describe("ConfigRoute layout density contract", () => {
  it("uses separate compact view and edit field card classes", () => {
    expect(configRouteSource).toContain("styles.treeFieldCardView");
    expect(configRouteSource).toContain("styles.treeFieldCardEdit");
  });

  it("keeps read-only config fields in dense label-value rows on wide screens", () => {
    expect(configRouteStylesSource).toContain("hashGrid:");
    expect(configRouteStylesSource).toContain("treeGrid:");
    expect(configRouteStylesSource).toContain("[display:grid]");
    expect(configRouteStylesSource).toContain("[gap:7px]");
    expect(configRouteStylesSource).toContain("treeFieldCardView:");
    expect(configRouteSource).toContain("styles.treeFieldCardView");
  });

  it("does not collapse the config tree to one column until phone width", () => {
    expect(configRouteSource).toContain("styles.treeGrid");
    expect(configRouteStylesSource).toContain("[grid-template-columns:repeat(2,minmax(0,1fr))]");
    expect(configRouteStylesSource).toContain("max-[1120px]:[grid-template-columns:repeat(2,minmax(210px,1fr))]");
    expect(configRouteStylesSource).toContain("max-[720px]:[grid-template-columns:1fr]");
    expect(configRouteStylesSource).not.toContain("ConfigRoute.legacy.css");
  });
});

describe("ConfigRoute content experience contract", () => {
  it("frames the overview as save/apply status instead of an internal config source", () => {
    expect(configRouteSource).toContain('sourceTitle: "保存与生效"');
    expect(configRouteSource).toContain('sourceBody: "这里显示当前修改是否已经保存，以及哪些系统级设置需要重启后才会生效。"');
    expect(configRouteSource).not.toContain('sourceTitle: "配置源"');
  });

  it("keeps low-value field-type badges out of read-only config cards", () => {
    const viewStart = configRouteSource.indexOf("function renderFieldView");
    const editStart = configRouteSource.indexOf("function renderFieldEditor");
    const renderFieldViewSource = configRouteSource.slice(viewStart, editStart);

    expect(renderFieldViewSource).toContain("styles.treeFieldCardView");
    expect(renderFieldViewSource).not.toContain("meta?.badge");
  });

  it("keeps restart timing visible for workbench ports", () => {
    const schemaSource = readFileSync(new URL("../core/web/services/config_editor_schema.py", import.meta.url), "utf-8");

    expect(schemaSource).toContain("修改后下次启动或重启生效");
    expect(schemaSource).toContain("Restart the workbench after changing it");
  });

  it("keeps provider-first actions visible and does not restore the legacy model panel", () => {
    expect(configRouteSource).toContain("workspace.schemaVersion === 2");
    expect(configRouteSource).toContain("<ConfigProviderRegistryPanel");
    expect(configRouteSource).toContain("<ConfigProviderWizard");
    expect(configRouteSource).toContain("<ConfigModelMigrationPanel");
    expect(configRouteSource).toContain('providerActionError ? <p className={styles.noticeError} role="alert"');
    expect(configRouteSource).not.toContain('from "./ConfigModelLibraryPanel"');
  });

  it("keeps model binding editing out of settings after moving it to Agent management", () => {
    expect(configRouteSource).toContain('modelsTitle: "模型库"');
    expect(configRouteSource).toContain("每个 Agent 的具体模型选择请到 Agent 管理中维护");
    expect(configRouteSource).toContain('modelsTitle: "Model Library"');
    expect(configRouteSource).toContain("Edit each Agent's model choices in Agent management");
    expect(configRouteSource).not.toContain('modelsTitle: "模型中心"');
    expect(configRouteSource).not.toContain('modelsTitle: "Model Center"');
    expect(configRouteSource).not.toContain("copy.profilesBody");
    expect(configRouteSource).not.toContain('id: "profile-bindings"');
    expect(configRouteSource).not.toContain('memberSectionIds: ["profiles"]');
    expect(configRouteSource).not.toContain("styles.profileCardGroups");
    expect(configRouteSource).not.toContain("handleApplySelectedProfileModels");
    expect(configRouteSource).not.toContain("handleAddProfile");
    expect(configRouteSource).not.toContain("handleTestProfile(");
  });

  it("separates model assets and git model settings in the sidebar", () => {
    expect(configNavigationSource).toContain('"models-profiles"');
    expect(configNavigationSource).toContain('members: ["models"]');
    expect(configNavigationSource).toContain('members: ["llm-discovery"]');
    expect(configNavigationSource).toContain('id: "tooling-git"');
    expect(configNavigationSource).toContain('members: ["git-commit-model", "git-commit-prompt"]');
    expect(configNavigationSource).not.toContain('members: ["prompt"]');
    expect(configNavigationSource).not.toContain('members: ["profiles", "models", "llm-profiles"');
  });

  it("keeps Agent editing out of the config page", () => {
    expect(configRouteSource).not.toContain('id="config-agent-center"');
    expect(configRouteSource).not.toContain('to="/agents"');
    expect(configRouteSource).not.toContain("copy.openAgentManagement");
    expect(configRouteSource).not.toContain("copy.agentConfigActive");
    expect(configRouteSource).not.toContain("copy.agentConfigCenterTitle");
    expect(configRouteSource).not.toContain('memberSectionIds: ["agent"');
    expect(configNavigationSource).toContain('"runtime-context"');
    expect(configNavigationSource).toContain('members: ["context-compression"]');
    expect(configNavigationSource).toContain('members: ["analysis"]');
    expect(configRouteSource).toContain("copy.groupRuntimeContextTitle");
    expect(configRouteSource).not.toContain('memberSectionIds: ["agent", "context-compression", "memory", "strategy", "analysis", "evolution"]');
    expect(configRouteSource).not.toContain("saveResearchAgent");
    expect(configRouteSource).not.toContain("deleteResearchAgent");
    expect(configRouteSource).not.toContain("updateModeSlot");
    expect(configRouteSource).not.toContain("toggleResearchPoolAgent");
    expect(configRouteSource).not.toContain("toggleChatAvailableAgent");
    expect(configRouteSource).not.toContain("styles.agentConfigCard");
    expect(configRouteSource).not.toContain("styles.bindingCard");
    expect(configRouteSource).not.toContain("config-mode-bindings");
  });

  it("keeps Agent prompt management out of the config page", () => {
    expect(configRouteSource).not.toContain('id="config-prompt-templates"');
    expect(configRouteSource).not.toContain("PromptTemplateWorkspace");
    expect(configRouteSource).not.toContain("queryKeys.promptTemplates");
    expect(configRouteSource).not.toContain("copy.promptTemplateCenterTitle");
    expect(configRouteSource).not.toContain('to="/agents/prompts"');
    expect(configRouteSource).not.toContain('section.id !== "prompt"');
    expect(configRouteStylesSource).not.toContain("promptTemplateGrid");
    expect(configRouteStylesSource).not.toContain("agentCardGrid");
    expect(configRouteStylesSource).not.toContain("bindingCardGrid");
  });

  it("guards internal route changes when config changes have not been saved to disk", () => {
    expect(configRouteSource).toContain("useBlocker");
    expect(configRouteSource).toContain("shouldBlockConfigLeave");
    expect(configRouteSource).toContain('leaveBlocker.state === "blocked"');
    expect(configRouteSource).toContain("handleSaveAndLeave");
    expect(configRouteSource).toContain("copy.leaveGuardSave");
    expect(configRouteSource).toContain("copy.leaveGuardDiscard");
    expect(configRouteSource).toContain("copy.leaveGuardCancel");

    expect(configRouteSource).toContain("styles.leaveGuardOverlay");
    expect(configRouteSource).toContain("styles.leaveGuardPanel");
    expect(configRouteStylesSource).toContain("leaveGuardOverlay:");
    expect(configRouteStylesSource).toContain("leaveGuardPanel:");
  });
});
