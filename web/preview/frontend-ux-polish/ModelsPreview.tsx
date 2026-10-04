import { useState } from "react";

import type { ConfigCatalogModel } from "../../src/api/types";
import { WORKBENCH_LAYOUT_IDS } from "../../src/components/layout/workbenchLayoutIds";
import { VButton, VSettingsFormPage, VSplitWorkspace } from "../../src/components/vui";
import { ConfigProviderRegistryPanel, type ConfigProviderRegistryPanelProps } from "../../src/routes/ConfigProviderRegistryPanel";
import type { ProviderRegistryRow } from "../../src/routes/configProviderLogic";
import { useConfigSettingsNavigationCollapse } from "../../src/routes/ConfigRoute";
import { ConfigSettingsSidebar, type ConfigSettingsGroup } from "../../src/routes/ConfigSettingsNavigation";
import { CONFIG_COPY } from "../../src/routes/config/configCopy";
import routeStyles from "../../src/routes/ConfigRoute.styles";

const copy = CONFIG_COPY.zh;

const settingsGroups: ConfigSettingsGroup[] = [{
  id: "models-profiles",
  title: "模型与配置",
  summary: "管理模型供应商与模型目录",
  pages: [{
    id: "model-connection",
    title: "模型连接",
    summary: "模型供应商与目录",
    memberSectionIds: ["models"],
  }],
}];

function createPreviewModel(providerId: string, index: number): ConfigCatalogModel {
  const suffix = String(index + 1).padStart(2, "0");
  const modelKey = `preview-long-context-model-with-a-long-identifier-${suffix}`;
  const label = `模拟长名称模型 Preview Long Context ${suffix} · 256K context`;
  return {
    availability: "pinned",
    label,
    modelKey,
    modelRef: `${providerId}/${modelKey}`,
    status: "pinned",
    upstreamId: `preview-upstream-${suffix}`,
    capabilities: {},
    reasoningEffortValues: ["low", "medium", "high"],
    defaultReasoningEffort: "medium",
    reasoningCapabilitySource: "operator_override",
    reasoningVerificationStatus: "declared",
    draftEntry: {
      upstream_id: `preview-upstream-${suffix}`,
      label,
      enabled: true,
      context_window: 262144,
      wire_protocol: "responses",
      interaction_contract: "tool_chat",
      defaults: {
        reasoning_effort_values: ["low", "medium", "high"],
        reasoning_effort_adapter: "reasoning_object",
        default_reasoning_effort: "medium",
      },
    },
  };
}

function createPreviewProvider(
  providerId: string,
  label: string,
  baseUrl: string,
  models: ConfigCatalogModel[] = [],
): ProviderRegistryRow {
  return {
    providerId,
    label,
    serviceClass: "preview",
    vendor: "preview",
    driver: "openai",
    runtimeFramework: "",
    artifactPath: "",
    baseUrl,
    credentialState: "configured",
    contextWindow: 262144,
    defaultProtocol: "responses",
    pinnedCount: models.length,
    status: "configured",
    lastAttemptAt: "",
    lastSuccessAt: "",
    refreshDue: false,
    enabled: true,
    models,
  };
}

function createPreviewProviders(): ProviderRegistryRow[] {
  const longModelRows = Array.from({ length: 20 }, (_, index) => createPreviewModel("anthropic_relay_preview", index));
  return [
    createPreviewProvider("anthropic_relay_preview", "Anthropic", "https://anthropic-relay.example/v1", longModelRows),
    createPreviewProvider("anthropic_direct_preview", "Anthropic", "https://anthropic-direct.example/v1"),
    createPreviewProvider("xiaomi_relay_preview", "Xiaomi", "https://xiaomi-relay.example/v1"),
    createPreviewProvider("xiaomi_direct_preview", "Xiaomi", "https://xiaomi-direct.example/v1"),
  ];
}

/** Static, offline fixture for reviewing the 1024px model-library layout. */
export function ModelsPreview() {
  const [rows, setRows] = useState(createPreviewProviders);
  const [selectedProviderId, setSelectedProviderId] = useState("anthropic_relay_preview");
  const [selectedTab, setSelectedTab] = useState<ConfigProviderRegistryPanelProps["selectedTab"]>("models");
  const [hasPendingApply, setHasPendingApply] = useState(true);
  const [saveMessage, setSaveMessage] = useState("");
  const [actionMessage, setActionMessage] = useState("所有供应商、模型和保存动作均为本地演示数据。");
  const [credentialProviderId, setCredentialProviderId] = useState("");
  const [credentialValue, setCredentialValue] = useState("");
  const settingsNavCollapse = useConfigSettingsNavigationCollapse(true, "models-profiles:model-connection");

  function markPending(message: string) {
    setHasPendingApply(true);
    setSaveMessage("");
    setActionMessage(message);
  }

  function saveLocally() {
    setHasPendingApply(false);
    setSaveMessage("已模拟保存；没有写入配置或调用服务。");
  }

  return (
    <div
      data-model-library-preview="true"
      className="model-library-preview"
    >
      <aside
        data-model-preview-main-nav="true"
        aria-label="主导航预览"
        style={{
          display: "grid",
          gridTemplateRows: "auto minmax(0, 1fr)",
          gap: 8,
          minWidth: 0,
          overflow: "hidden",
          padding: 12,
          borderRight: "1px solid var(--vui-border-subtle)",
          background: "var(--vui-surface-panel)",
        }}
      >
        <strong>Vibelution</strong>
        <nav aria-label="主导航" style={{ display: "grid", alignContent: "start", gap: 4 }}>
          {["对话", "Agent", "工作流", "模型库", "设置"].map((item) => (
            <VButton
              key={item}
              contentLayout="plain"
              variant={item === "设置" ? "primary" : "ghost"}
              style={{ width: "100%", justifyContent: "flex-start" }}
              onPress={() => undefined}
            >
              {item}
            </VButton>
          ))}
        </nav>
      </aside>

      <VSplitWorkspace
        className={routeStyles.settingsSplit}
        data-vui-region="config-settings-split"
        style={{ minHeight: 0 }}
        resize={{
          layoutId: WORKBENCH_LAYOUT_IDS.configSettings,
          sidebar: { defaultWidth: 220, minWidth: 220, maxWidth: 360 },
          collapse: {
            sidebar: {
              separatorLabel: copy.navResizeSeparator,
              collapseLabel: copy.navCollapse,
              expandLabel: copy.navExpand,
              collapsed: settingsNavCollapse.collapsed,
              onCollapsedChange: settingsNavCollapse.onCollapsedChange,
            },
          },
        }}
        sidebar={(
          <ConfigSettingsSidebar
            language="zh"
            title="设置"
            subtitle="模型连接预览"
            statusLabel="本地预览"
            groups={settingsGroups}
            activeGroupId="models-profiles"
            onShowAll={() => undefined}
            onSelectGroup={() => undefined}
            onNavigate={() => undefined}
            searchDocuments={[]}
          />
        )}
        main={(
          <VSettingsFormPage
            ariaLabel="模型连接预览"
            className={routeStyles.content}
            headerClassName={routeStyles.configHeader}
            bodyClassName="!gap-0 !overflow-hidden !content-stretch"
            title="模型连接"
            actions={(
              <div className={routeStyles.configStatusActions}>
                <VButton variant="ghost" onPress={() => setActionMessage("高级设置仅为本地预览。")}>高级设置</VButton>
                <VButton variant="ghost" onPress={() => setActionMessage("目录刷新未调用任何服务。")}>刷新</VButton>
                <VButton variant="primary" onPress={saveLocally}>保存设置</VButton>
              </div>
            )}
            banner={(
              <div role="status" style={{ padding: "6px 12px", color: "var(--vui-fg-secondary)" }}>
                {saveMessage || actionMessage}
              </div>
            )}
          >
            <ConfigProviderRegistryPanel
              copy={copy}
              rows={rows}
              selectedProviderId={selectedProviderId}
              selectedTab={selectedTab}
              disabled={false}
              activeCredentialProviderId={credentialProviderId}
              credentialValue={credentialValue}
              activeRouteProviderId=""
              imageCapabilityBusy={false}
              actionFeedback={null}
              liveReferenceCountByModelRef={{}}
              hasPendingApply={hasPendingApply}
              canSaveConfig={true}
              onSaveExternal={saveLocally}
              onSelectProvider={setSelectedProviderId}
              onSelectTab={setSelectedTab}
              onDiscover={() => setActionMessage("模型检测未向服务发起请求。")}
              onEditCredential={(providerId) => {
                setCredentialProviderId(providerId);
                setCredentialValue("");
                setSelectedTab("connection");
              }}
              onCredentialValueChange={setCredentialValue}
              onCancelCredential={() => {
                setCredentialProviderId("");
                setCredentialValue("");
              }}
              onSaveCredential={() => markPending("凭据保存动作仅更新本地演示状态。")}
              onSaveContextWindow={() => markPending("上下文窗口保存动作仅更新本地演示状态。")}
              onEditRoute={() => setActionMessage("路由编辑仅为本地预览。")}
              onCancelRoute={() => undefined}
              onPin={() => markPending("模型添加动作仅更新本地演示状态。")}
              onUnpin={() => markPending("模型移除动作仅更新本地演示状态。")}
              onTestModel={() => setActionMessage("模型测试未发起请求。")}
              onProbeImageInput={() => setActionMessage("图片能力检测未发起请求。")}
              onDeleteProvider={() => setActionMessage("删除动作未执行。")}
              onAddConnection={() => setActionMessage("供应商创建仅为本地预览。")}
              onToggleEnabled={(providerId, enabled) => {
                setRows((current) => current.map((row) => row.providerId === providerId ? { ...row, enabled } : row));
                markPending("启停状态只保存在当前预览中。 ");
              }}
              onUpdateModel={(providerId, modelKey, edits) => {
                setRows((current) => current.map((row) => row.providerId === providerId
                  ? {
                    ...row,
                    models: row.models.map((model) => model.modelKey === modelKey
                      ? { ...model, draftEntry: { ...(model.draftEntry ?? {}), ...edits } }
                      : model),
                  }
                  : row));
                markPending("模型编辑保留在当前预览中。 ");
              }}
            />
          </VSettingsFormPage>
        )}
      />
    </div>
  );
}
