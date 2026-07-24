import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConfigCatalogModel } from "../api/types";
import {
  ConfigProviderRegistryPanel,
  ProviderModelsTab,
  type ConfigProviderRegistryPanelProps,
} from "./ConfigProviderRegistryPanel";
import panelSource from "./ConfigProviderRegistryPanel.tsx?raw";
import panelStyles from "./ConfigProviderRegistryPanel.styles";
import type { ProviderModelFilter, ProviderRegistryRow } from "./configProviderLogic";

function model(
  key: string,
  availability: ConfigCatalogModel["availability"],
  label = key,
): ConfigCatalogModel {
  return {
    availability,
    label,
    modelKey: key,
    modelRef: `relay_a/${key}`,
    status: availability,
    upstreamId: `${key}-upstream`,
    capabilities: {},
  };
}

function provider(models: ConfigCatalogModel[]): ProviderRegistryRow {
  return {
    providerId: "relay_a",
    label: "Relay A",
    serviceClass: "relay",
    vendor: "multi_model",
    driver: "openai",
    runtimeFramework: "",
    artifactPath: "",
    baseUrl: "https://relay.example/v1",
    credentialState: "configured",
    contextWindow: 128000,
    defaultProtocol: "responses",
    pinnedCount: models.filter((item) => ["pinned", "missing_remote"].includes(item.availability)).length,
    status: "reachable",
    lastAttemptAt: "2026-07-12T00:00:00Z",
    lastSuccessAt: "2026-07-12T00:00:00Z",
    refreshDue: false,
    models,
  };
}

function panelProps(
  models: ConfigCatalogModel[],
  overrides: Record<string, unknown> = {},
): ConfigProviderRegistryPanelProps {
  return {
    rows: [provider(models)],
    selectedProviderId: "relay_a",
    selectedTab: "models",
    disabled: false,
    activeCredentialProviderId: "",
    activeRouteProviderId: "",
    imageCapabilityBusy: false,
    actionFeedback: null,
    liveReferenceCountByModelRef: {},
    onSelectProvider: () => undefined,
    onSelectTab: () => undefined,
    onDiscover: () => undefined,
    onEditCredential: () => undefined,
    credentialValue: "",
    onCredentialValueChange: () => undefined,
    onCancelCredential: () => undefined,
    onSaveCredential: () => undefined,
    onSaveContextWindow: () => undefined,
    onEditRoute: () => undefined,
    onPin: () => undefined,
    onUnpin: () => undefined,
    onTestModel: () => undefined,
    onProbeImageInput: () => undefined,
    onDeleteProvider: () => undefined,
    ...overrides,
  };
}

function renderModels(
  models: ConfigCatalogModel[],
  options: {
    query?: string;
    filter?: ProviderModelFilter;
    liveReferences?: Record<string, number>;
  } = {},
) {
  return renderToStaticMarkup(
    <ProviderModelsTab
      provider={provider(models)}
      disabled={false}
      modelQuery={options.query ?? ""}
      modelFilter={options.filter ?? "all"}
      liveReferenceCountByModelRef={options.liveReferences ?? {}}
      onQueryChange={() => undefined}
      onFilterChange={() => undefined}
      onPin={() => undefined}
      onUnpin={() => undefined}
      onTestModel={() => undefined}
      onProbeImageInput={() => undefined}
    />,
  );
}

describe("ConfigProviderRegistryPanel", () => {
  it("renders a searchable model toolbar with status counts", () => {
    const models = [
      model("pinned", "pinned"),
      model("observed", "observed"),
      model("disabled", "disabled"),
    ];

    const markup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps(models)} />);

    expect(markup).toContain('aria-label="搜索模型"');
    expect(markup).toContain("搜索 modelRef、Upstream ID 或名称");
    expect(markup).toContain("全部 3");
    expect(markup).toContain("已固定 1");
    expect(markup).toContain("已发现 1");
    expect(markup).toContain("不可用 1");
    expect(markup).toContain('aria-pressed="true"');
  });

  it("renders pin controls for discovered models and bulk pin banner", () => {
    const observedMarkup = renderModels([model("observed", "observed")]);
    expect(observedMarkup).toContain("固定到配置");
    expect(observedMarkup).toContain("固定全部已发现");
    expect(observedMarkup).toContain('data-model-action="pin"');
    expect(observedMarkup).toContain('data-model-action="pin-all"');
    expect(observedMarkup).not.toContain("取消固定");
    expect(observedMarkup).not.toContain("测试调用");
    expect(observedMarkup).toContain("验证推理 low / high");
    expect(renderModels([model("disabled", "disabled")])).toContain("不可用");
    expect(renderModels([model("disabled", "disabled")])).not.toContain("取消固定");

    const pinned = model("pinned", "pinned");
    const inUseMarkup = renderModels([pinned], { liveReferences: { [pinned.modelRef]: 2 } });
    expect(inUseMarkup).toContain("使用中 · 2 个引用");
    expect(inUseMarkup).not.toContain("取消固定");

    expect(renderModels([pinned])).toContain("测试调用");
    expect(renderModels([pinned])).toContain("取消固定");
  });

  it("exposes a per-model image input capability probe with current-state copy", () => {
    const unknownMarkup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([model("terra", "observed")])} />,
    );
    const supportedModel = {
      ...model("terra", "observed"),
      capabilities: {
        image_input: {
          value: "supported" as const,
          source: "runtime_probe" as const,
          confidence: "",
          checked_at: "2026-07-19T12:38:58Z",
        },
      },
    };
    const supportedMarkup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([supportedModel])} />,
    );
    const busyMarkup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([supportedModel], { imageCapabilityBusy: true })} />,
    );

    expect(unknownMarkup).toContain('data-model-capability-action="image_input"');
    expect(unknownMarkup).toContain("验证图片输入");
    expect(supportedMarkup).toContain("重新验证图片");
    expect(busyMarkup).toContain("验证图片中…");
  });

  it("shows verified reasoning efforts as maintained model capability", () => {
    const reasoningModel = {
      ...model("reasoning", "observed"),
      reasoningEffortValues: ["low", "high"],
      reasoningVerificationStatus: "verified",
    };

    const markup = renderModels([reasoningModel]);

    expect(markup).toContain("推理 low / high 已验证");
    expect(markup).not.toContain("验证推理 low / high");
    expect(panelSource).toContain('"/api/config/test-llm"');
    expect(panelSource).toContain('capability: "reasoning_effort"');
    expect(panelSource).toContain("一期探测仅验证 low/high");
  });

  it("shows operator-declared reasoning contract without requiring probe", () => {
    const declared = {
      ...model("luna", "pinned"),
      reasoningEffortValues: ["low", "medium", "high"],
      reasoningVerificationStatus: "declared",
      reasoningCapabilitySource: "operator_override",
      defaultReasoningEffort: "medium",
      reasoningAdapter: "reasoning_object",
    };
    const markup = renderModels([declared]);
    expect(markup).toContain("协议已声明 low / medium / high");
    expect(markup).toContain("思考深度: low/medium/high");
    expect(markup).not.toContain("验证推理 low / high");
  });

  it("distinguishes an empty directory from filtered no results", () => {
    expect(renderModels([])).toContain("该 Provider 暂无模型");
    expect(renderModels([model("alpha", "observed")], { query: "missing" })).toContain("没有匹配的模型");
  });

  it("uses low-emphasis copy for unobserved capabilities and a sticky internal scroll region", () => {
    const markup = renderModels([model("observed", "observed")]);

    // Observed (not pinned) must not spam "thinking not declared" warnings.
    expect(markup).not.toContain("思考深度: 未配置");
    expect(markup).not.toContain("reasoning: 未声明");
    expect(markup).toContain("—");
    expect(markup).not.toContain("unknown · 未观测");
    expect(panelStyles.tableScroll).toContain("h-full");
    expect(panelStyles.tableScroll).not.toContain("max-h-[calc(100dvh-33rem)]");
    expect(panelStyles.tableScroll).toContain("overflow-auto");
    expect(panelStyles.table).toContain("min-w-[820px]");
    expect(panelStyles.table).toContain("[&amp;_thead]:sticky".replace("&amp;", "&"));
    const heroUiImportToken = ["@heroui", "react"].join("/");
    expect(panelSource).not.toContain(heroUiImportToken);
  });

  it("only warns about missing reasoning contracts on pinned models", () => {
    const pinned = {
      ...model("luna", "pinned"),
      reasoningEffortValues: [],
    };
    const markup = renderModels([pinned]);
    expect(markup).toContain("思考深度: 未配置");
  });

  it("fills the desktop workspace with large Provider rows and a bottom danger zone", () => {
    expect(panelStyles.sectionSurface).toContain("h-full");
    expect(panelStyles.registryWorkspace).toContain("[--vui-workspace-sidebar:clamp(18rem,24vw,22rem)]");
    expect(panelStyles.providerList).toContain("h-full");
    expect(panelStyles.providerButton).toContain("!min-h-[3.5rem]");
    expect(panelStyles.providerLabel).toContain("whitespace-normal");
    expect(panelStyles.providerLabel).toContain("break-words");
    expect(panelStyles.inspectorPanel).toContain("h-full");
    expect(panelStyles.detailBody).toContain("min-h-0");
    expect(panelSource).toContain('data-provider-action="edit-asset"');
    expect(panelSource).toContain('data-provider-danger-zone="true"');
    expect(panelSource).toContain("openInspector");
    expect(panelSource).not.toContain("mobileActionGroup");
  });

  it("resets local model tools from the actual rendered Provider identity", () => {
    expect(panelSource).toContain("}, [provider?.providerId]);");
    expect(panelSource).not.toContain("}, [selectedProviderId]);");
  });

  it("offers a preview-first merge only for an exact-contract duplicate", () => {
    expect(panelSource).toContain("合并重复 Provider（高级）");
    expect(panelSource).toContain("日常中转站不需要");
    expect(panelSource).toContain("/api/config/migration/providers/merge/preview");
    expect(panelSource).toContain("/api/config/migration/providers/merge/apply");
    expect(panelSource).toContain("confirmed: true");
  });

  it("keeps API Key and context window in the right-side asset inspector", () => {
    expect(panelSource).toContain("一个中转站 / Provider = 一把 API Key");
    expect(panelSource).toContain("2 · 上下文窗口");
    expect(panelSource).toContain("context_window");
    expect(panelSource).toContain("保存上下文窗口到草稿");
    expect(panelSource).toContain("config-asset-inspector");
    const markup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([])} />,
    );
    expect(markup).toContain("编辑");
    expect(markup).toContain("已配置的连接与模型");
  });

  it("collapses abnormal services and surfaces a strong save prompt when draft is dirty", () => {
    const healthy = provider([model("luna", "pinned")]);
    const broken = {
      ...provider([]),
      providerId: "relay_bad",
      label: "Broken Relay",
      status: "auth_failed" as const,
    };
    const collapsed = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([], { rows: [healthy, broken] })} />,
    );
    expect(collapsed).toContain("可用服务");
    expect(collapsed).toContain("异常服务 · 1");
    expect(collapsed).toContain('data-abnormal-expanded="false"');
    expect(collapsed).toContain("Relay A");
    expect(collapsed).not.toContain("Broken Relay");

    const dirty = renderToStaticMarkup(
      <ConfigProviderRegistryPanel
        {...panelProps([model("luna", "pinned")], {
          hasPendingApply: true,
          canSaveConfig: true,
          onSaveExternal: () => undefined,
        })}
      />,
    );
    expect(dirty).toContain('data-save-prompt="pending"');
    expect(dirty).toContain("有未保存的模型配置");
    expect(dirty).toContain("保存到外部配置");
    expect(dirty).toContain("有未保存修改");
  });

  it("aligns Provider action labels, active states, and nearby feedback", () => {
    const models = [model("observed", "observed")];
    const busyMarkup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps(models, {
      activeCredentialProviderId: "relay_a",
      activeRouteProviderId: "",
      actionFeedback: {
        kind: "discover",
        providerId: "relay_a",
        phase: "busy",
        message: "正在发现模型…",
      },
    })} />);

    expect(busyMarkup).toContain("发现中…");
    expect(busyMarkup).toContain('data-provider-action="edit-asset"');
    expect(busyMarkup).toContain('data-provider-action="discover"');
    expect(busyMarkup).toContain('aria-live="polite"');
    expect(busyMarkup).toContain("正在发现模型…");

    const successMarkup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps(models, {
      activeCredentialProviderId: "",
      activeRouteProviderId: "relay_a",
      actionFeedback: {
        kind: "route",
        providerId: "relay_a",
        phase: "success",
        message: "路由预览已生成",
      },
    })} />);
    expect(successMarkup).toContain("路由预览已生成");
    expect(panelSource).toContain('data-provider-action="route"');

    const errorMarkup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps(models, {
      activeCredentialProviderId: "",
      activeRouteProviderId: "",
      actionFeedback: {
        kind: "credential",
        providerId: "relay_a",
        phase: "error",
        message: "API Key 更新失败",
      },
    })} />);
    expect(errorMarkup).toContain('role="alert"');
    expect(errorMarkup).toContain("API Key 更新失败");
  });
  it("keeps the latest safe discovery failure on the selected Provider diagnostics", () => {
    expect(panelSource).toContain("最近失败原因");
    expect(panelSource).toContain("请求超时");
    expect(panelSource).toContain("function DiagnosticsTab");
    const timedOut = { ...provider([]), status: "discovery_failed" as const, lastErrorType: "timeout" };
    const markup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([], { rows: [timedOut] })} />,
    );
    expect(markup).toContain("discovery_failed");
    expect(markup).toContain("编辑");
  });
});
