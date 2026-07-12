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

function panelProps(models: ConfigCatalogModel[]): ConfigProviderRegistryPanelProps {
  return {
    rows: [provider(models)],
    selectedProviderId: "relay_a",
    selectedTab: "models",
    disabled: false,
    liveReferenceCountByModelRef: {},
    onSelectProvider: () => undefined,
    onSelectTab: () => undefined,
    onDiscover: () => undefined,
    onEditCredential: () => undefined,
    onEditRoute: () => undefined,
    onUnpin: () => undefined,
    onTestModel: () => undefined,
    onDeleteProvider: () => undefined,
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
    expect(renderModels([model("observed", "observed")])).toContain("未固定");
    expect(renderModels([model("observed", "observed")])).not.toContain("取消固定");
    expect(renderModels([model("disabled", "disabled")])).toContain("不可用");
    expect(renderModels([model("disabled", "disabled")])).not.toContain("取消固定");

    const pinned = model("pinned", "pinned");
    const inUseMarkup = renderModels([pinned], { liveReferences: { [pinned.modelRef]: 2 } });
    expect(inUseMarkup).toContain("使用中 · 2 个引用");
    expect(inUseMarkup).not.toContain("取消固定");

    expect(renderModels([pinned])).toContain("取消固定");
  });

  it("distinguishes an empty directory from filtered no results", () => {
    expect(renderModels([])).toContain("该 Provider 暂无模型");
    expect(renderModels([model("alpha", "observed")], { query: "missing" })).toContain("没有匹配的模型");
  });

  it("uses low-emphasis copy for unobserved capabilities and a sticky internal scroll region", () => {
    const markup = renderModels([model("observed", "observed")]);

    expect(markup).toContain("未观测");
    expect(markup).not.toContain("unknown · 未观测");
    expect(panelStyles.tableScroll).toContain("max-h-[calc(100dvh-26rem)]");
    expect(panelStyles.tableScroll).toContain("overflow-auto");
    expect(panelStyles.table).toContain("[&amp;_thead]:sticky".replace("&amp;", "&"));
    expect(panelSource).not.toContain('@heroui/react');
  });
});
