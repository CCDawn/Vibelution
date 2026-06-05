import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import configRouteSource from "./src/routes/ConfigRoute.tsx?raw";

const configRouteCss = readFileSync(new URL("./src/routes/ConfigRoute.module.css", import.meta.url), "utf-8");

function cssRule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return configRouteCss.match(new RegExp(`${escaped}\\s*\\{[^}]*\\}`, "s"))?.[0] ?? "";
}

function cssBetween(start: string, end: string): string {
  const startIndex = configRouteCss.indexOf(start);
  const endIndex = end ? configRouteCss.indexOf(end, startIndex + start.length) : -1;
  if (startIndex < 0) {
    return "";
  }
  return configRouteCss.slice(startIndex, endIndex < 0 ? undefined : endIndex);
}

describe("ConfigRoute layout density contract", () => {
  it("uses separate compact view and edit field card classes", () => {
    expect(configRouteSource).toContain("styles.treeFieldCardView");
    expect(configRouteSource).toContain("styles.treeFieldCardEdit");
  });

  it("keeps read-only config fields in dense label-value rows on wide screens", () => {
    const treeGrid = cssRule(".treeGrid");
    const viewCard = cssRule(".treeFieldCardView");
    const overviewGrid = cssRule(".hashGrid");

    expect(overviewGrid).toContain("minmax(280px, 1.4fr) minmax(180px, 0.6fr)");
    expect(treeGrid).toContain("repeat(auto-fit, minmax(260px, 1fr))");
    expect(viewCard).toContain("grid-template-columns: minmax(124px, 0.25fr) minmax(0, 1fr)");
    expect(viewCard).toContain("min-height: 34px");
  });

  it("does not collapse the config tree to one column until phone width", () => {
    const tabletRules = cssBetween("@media (max-width: 1120px)", "@media (max-width: 720px)");
    const phoneRules = cssBetween("@media (max-width: 720px)", "");

    expect(tabletRules).toContain("repeat(auto-fit, minmax(210px, 1fr))");
    expect(tabletRules).not.toMatch(/\.treeGrid\s*{[^}]*grid-template-columns:\s*1fr/s);
    expect(phoneRules).toMatch(/\.treeGrid\s*{[^}]*grid-template-columns:\s*1fr/s);
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

  it("shows model edit failures inside the model editor instead of relying only on the page notice", () => {
    expect(configRouteSource).toContain("modelEditorError");
    expect(configRouteSource).toContain('role="alert"');
    expect(configRouteSource).toContain("styles.inlineFormError");
    expect(configRouteSource).toContain("setModelEditorError(markError(error))");
  });

  it("keeps model binding editing out of settings after moving it to Agent management", () => {
    expect(configRouteSource).toContain('modelsTitle: "模型库"');
    expect(configRouteSource).toContain("每个 Agent 的具体 LLM 槽位绑定请到 Agent 管理中维护");
    expect(configRouteSource).toContain('modelsTitle: "Model Library"');
    expect(configRouteSource).toContain("Edit each Agent's LLM slot bindings in Agent management");
    expect(configRouteSource).not.toContain('modelsTitle: "模型中心"');
    expect(configRouteSource).not.toContain('modelsTitle: "Model Center"');
    expect(configRouteSource).not.toContain("copy.profilesBody");
    expect(configRouteSource).not.toContain('id: "profile-bindings"');
    expect(configRouteSource).not.toContain('memberSectionIds: ["profiles"]');
    expect(configRouteSource).not.toContain("styles.profileCardGroups");
    expect(configRouteSource).not.toContain("handleApplySelectedProfileModels");
    expect(configRouteSource).not.toContain("handleAddProfile");
    expect(configRouteSource).not.toContain("handleTestProfile(");

    const modelsStart = configRouteSource.indexOf("copy.modelsBody");
    const modelEditorStart = configRouteSource.indexOf("modelEditor.mode", modelsStart);
    const modelsIntroSource = configRouteSource.slice(modelsStart, modelEditorStart);
    expect(modelsIntroSource).toContain("copy.modelCenterModels");
    expect(modelsIntroSource).toContain("copy.modelCenterAccounts");
    expect(modelsIntroSource).toContain("copy.modelCenterBindings");
    expect(modelsIntroSource).toContain("copy.modelCenterCapabilityIssues");
  });

  it("separates model assets and git model settings in the sidebar", () => {
    expect(configRouteSource).toContain('id: "models-profiles"');
    expect(configRouteSource).toContain('memberSectionIds: ["models", "llm-discovery"]');
    expect(configRouteSource).toContain(
      'memberSectionIds: ["health-diagnostics", "tools", "git-commit-profile", "git-commit-prompt", "security", "network", "log", "parser", "debug"]',
    );
    expect(configRouteSource).not.toContain('memberSectionIds: ["prompt"]');
    expect(configRouteSource).not.toContain('memberSectionIds: ["profiles", "models", "llm-profiles", "llm-discovery", "git-commit-profile"]');
  });

  it("keeps model-library advanced transport fields behind a disclosure", () => {
    expect(configRouteSource).toContain("styles.advancedEditorPanel");
    expect(configRouteSource).toContain("copy.modelEditorAdvancedTitle");

    const advancedPanelStart = configRouteSource.indexOf('className={styles.advancedEditorPanel}');
    const saveButtonStart = configRouteSource.indexOf("copy.saveModel", advancedPanelStart);
    const advancedPanelSource = configRouteSource.slice(advancedPanelStart, saveButtonStart);

    expect(advancedPanelSource).toContain("copy.transport");
    expect(advancedPanelSource).toContain("copy.contract");
    expect(advancedPanelSource).toContain("copy.timeout");
    expect(advancedPanelSource).toContain("MODEL_TRANSPORT_OPTIONS.map");
    expect(advancedPanelSource).toContain("MODEL_CONTRACT_OPTIONS.map");
    expect(advancedPanelSource).toContain("MODEL_TOOL_CALLING_MODE_OPTIONS.map");
    expect(advancedPanelSource).toContain("PROVIDER_COMPAT_MODE_OPTIONS.map");
    expect(advancedPanelSource).toContain("<select\n                        value={modelEditor.details.transport}");
    expect(advancedPanelSource).toContain("<select\n                        value={modelEditor.details.contract}");
    expect(advancedPanelSource).toContain("<select\n                        value={modelEditor.details.tool_calling_mode}");
  });

  it("treats model deletion as model-key cleanup in user-facing copy", () => {
    expect(configRouteSource).toContain("删除模型会同步清理该模型唯一绑定的环境密钥");
    expect(configRouteSource).toContain("Deleting a model also clears the unique environment key bound to that model");
    expect(configRouteSource).toContain("window.confirm(copy.deleteModelConfirm)");
    expect(configRouteSource).not.toContain("Deleting a model only removes the config entry");
  });

  it("guards model library action buttons against invalid or locked edits", () => {
    expect(configRouteSource).toContain("const modelEditorRequiredFieldsReady = Boolean(modelEditor.model.trim() && modelEditor.provider.base_url.trim())");
    expect(configRouteSource).toContain("const canSubmitModelEditor = !structuredActionsDisabled && modelEditorRequiredFieldsReady");
    expect(configRouteSource).toContain("disabled={!canSubmitModelEditor}");
    expect(configRouteSource).toContain("setModelEditorError(copy.modelRequiredFieldsMissing)");
    expect(configRouteSource).toContain("disabled={structuredActionsDisabled || !row.editable || !option}");
    expect(configRouteSource).toContain("disabled={structuredActionsDisabled}");
  });

  it("labels the bulk image capability check as saved-model scoped", () => {
    expect(configRouteSource).toContain("copy.checkSavedImageCapabilities");
    expect(configRouteSource).toContain('checkSavedImageCapabilities: "检测已保存模型图像输入"');
    expect(configRouteSource).toContain('checkSavedImageCapabilities: "Check saved models image input"');
  });

  it("uses one model-library test control for the selected model", () => {
    expect(configRouteSource).toContain("selectedModelTestId");
    expect(configRouteSource).toContain("handleTestSelectedLibraryModel");
    expect(configRouteSource).toContain("copy.modelTestSelect");
    expect(configRouteSource).toContain("copy.testSelectedLibraryModel");
    expect(configRouteSource).toContain("modelId: selectedModelTestId");
    expect(configRouteSource).toContain("styles.modelLibraryTestBar");

    const tableStart = configRouteSource.indexOf("styles.modelInventoryTable");
    const tableEnd = configRouteSource.indexOf("activeEditorSections.map", tableStart);
    const tableSource = configRouteSource.slice(tableStart, tableEnd);
    expect(tableSource).toContain("copy.modelCenterActions");
    expect(tableSource).not.toContain("copy.testConnection");
    expect(tableSource).not.toContain("handleTestSelectedLibraryModel");
  });

  it("keeps model-library rows free of usage-location details", () => {
    const tableStart = configRouteSource.indexOf("styles.modelInventoryTable");
    const tableEnd = configRouteSource.indexOf("activeEditorSections.map", tableStart);
    const tableSource = configRouteSource.slice(tableStart, tableEnd);

    expect(tableSource).not.toContain("copy.modelCenterUsage");
    expect(tableSource).not.toContain("copy.modelCenterUsageCount");
    expect(tableSource).not.toContain("row.usages");
    expect(tableSource).not.toContain("row.usageCount");
  });

  it("shows the model key environment variable as a read-only model-id binding", () => {
    expect(configRouteSource).toContain("copy.modelKeyEnv");
    expect(configRouteSource).toContain("模型密钥变量名由模型 ID 唯一生成");
    expect(configRouteSource).toContain('aria-readonly="true"');
    expect(configRouteSource).not.toContain("setModelEditor((current) => ({ ...current, api_key_env: event.target.value }))");
  });

  it("shows provider default variables as compatibility-only display instead of editable key inputs", () => {
    expect(configRouteSource).toContain("copy.providerKeyEnv");
    expect(configRouteSource).toContain("服务商默认变量仅作兼容来源展示");
    expect(configRouteSource).toContain("The provider default variable is compatibility-only display");
    expect(configRouteSource).not.toContain("provider: { ...current.provider, api_key_env: event.target.value }");
  });

  it("passes the model unique key binding to model discovery requests", () => {
    expect(configRouteSource).toContain("const discoveryModelId =");
    expect(configRouteSource).toContain("const discoveryApiKeyEnv =");
    expect(configRouteSource).toContain("modelId: discoveryModelId");
    expect(configRouteSource).toContain("apiKeyEnv: discoveryApiKeyEnv");
    expect(configRouteSource).toContain("defaultModelApiKeyEnv(discoveryModelId)");
  });

  it("keeps Agent editing out of the config page", () => {
    expect(configRouteSource).not.toContain('id="config-agent-center"');
    expect(configRouteSource).not.toContain('to="/agents"');
    expect(configRouteSource).not.toContain("copy.openAgentManagement");
    expect(configRouteSource).not.toContain("copy.agentConfigActive");
    expect(configRouteSource).not.toContain("copy.agentConfigCenterTitle");
    expect(configRouteSource).not.toContain('memberSectionIds: ["agent"');
    expect(configRouteSource).toContain('id: "runtime-context"');
    expect(configRouteSource).toContain('memberSectionIds: ["context-compression", "analysis"]');
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
    expect(configRouteCss).not.toContain("promptTemplateGrid");
    expect(configRouteCss).not.toContain("agentCardGrid");
    expect(configRouteCss).not.toContain("bindingCardGrid");
  });

  it("guards internal route changes when config changes have not been saved to disk", () => {
    expect(configRouteSource).toContain("useBlocker");
    expect(configRouteSource).toContain("shouldBlockConfigLeave");
    expect(configRouteSource).toContain('leaveBlocker.state === "blocked"');
    expect(configRouteSource).toContain("handleSaveAndLeave");
    expect(configRouteSource).toContain("copy.leaveGuardSave");
    expect(configRouteSource).toContain("copy.leaveGuardDiscard");
    expect(configRouteSource).toContain("copy.leaveGuardCancel");

    expect(configRouteCss).toContain(".leaveGuardOverlay");
    expect(configRouteCss).toContain(".leaveGuardPanel");
  });
});
