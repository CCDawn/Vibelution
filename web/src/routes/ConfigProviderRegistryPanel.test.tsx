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
    onEditRoute: () => undefined,
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

  it("renders neutral action labels instead of inapplicable danger buttons", () => {
    const observedMarkup = renderModels([model("observed", "observed")]);
    expect(observedMarkup).toContain("未固定");
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
  });

  it("distinguishes an empty directory from filtered no results", () => {
    expect(renderModels([])).toContain("该 Provider 暂无模型");
    expect(renderModels([model("alpha", "observed")], { query: "missing" })).toContain("没有匹配的模型");
  });

  it("uses low-emphasis copy for unobserved capabilities and a sticky internal scroll region", () => {
    const markup = renderModels([model("observed", "observed")]);

    expect(markup).toContain("未观测");
    expect(markup).not.toContain("unknown · 未观测");
    expect(panelStyles.tableScroll).toContain("h-full");
    expect(panelStyles.tableScroll).not.toContain("max-h-[calc(100dvh-33rem)]");
    expect(panelStyles.tableScroll).toContain("overflow-auto");
    expect(panelStyles.table).toContain("min-w-[820px]");
    expect(panelStyles.table).toContain("[&amp;_thead]:sticky".replace("&amp;", "&"));
    const heroUiImportToken = ["@heroui", "react"].join("/");
    expect(panelSource).not.toContain(heroUiImportToken);
  });

  it("fills the desktop workspace with large Provider rows and a bottom danger zone", () => {
    expect(panelStyles.sectionSurface).toContain("h-full");
    expect(panelStyles.registryWorkspace).toContain("[--vui-workspace-sidebar:clamp(22rem,28%,28rem)]");
    expect(panelStyles.providerList).toContain("h-full");
    expect(panelStyles.providerButton).toContain("!min-h-[58px]");
    expect(panelStyles.detailSurface).toContain("[grid-template-rows:auto_auto_auto_minmax(0,1fr)_auto_auto]");
    expect(panelStyles.detailSurface).toContain("overflow-y-auto");
    expect(panelStyles.detailSurface).not.toContain("overflow-hidden");
    expect(panelStyles.detailBody).toContain("min-h-0");
    expect(panelSource).toContain('data-provider-tab={selectedTab}');
    expect(panelSource).toContain('data-provider-danger-zone="true"');
    expect(panelSource).not.toContain("mobileActionGroup");
  });

  it("resets local model tools from the actual rendered Provider identity", () => {
    expect(panelSource).toContain("}, [provider?.providerId]);");
    expect(panelSource).not.toContain("}, [selectedProviderId]);");
  });

  it("offers a preview-first merge only for an exact-contract duplicate", () => {
    const duplicate = { ...provider([]), providerId: "relay_b", label: "Relay B" };
    const markup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([], { rows: [provider([]), duplicate] })} />,
    );

    expect(markup).toContain("合并重复 Provider");
    expect(markup).toContain("生成合并预览");
    expect(markup).toContain("历史记录不改写");
    expect(markup).not.toContain("应用合并");
    expect(panelSource).toContain("/api/config/migration/providers/merge/preview");
    expect(panelSource).toContain("/api/config/migration/providers/merge/apply");
    expect(panelSource).toContain("confirmed: true");
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
    expect(busyMarkup).toContain('data-provider-action="credential"');
    expect(busyMarkup).toMatch(/data-provider-action="credential"[^>]*aria-pressed="true"/);
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
    expect(successMarkup).toMatch(/data-provider-action="route"[^>]*aria-pressed="true"/);
    expect(successMarkup).toContain("路由预览已生成");

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
});
