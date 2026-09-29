// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ConfigCatalogModel } from "../api/types";
import {
  ConfigProviderRegistryPanel,
  modelTestRecoveryHint,
  ProviderModelsTab,
  type ConfigProviderRegistryPanelProps,
} from "./ConfigProviderRegistryPanel";
import panelSourceRaw from "./ConfigProviderRegistryPanel.tsx?raw";
import configCopyRaw from "./config/configCopy.ts?raw";
import { CONFIG_COPY } from "./config/configCopy";

/** Panel source + shared bilingual copy table (wave 4): UI strings live in configCopy. */
const panelSource = `${panelSourceRaw}
${configCopyRaw}`;
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
    enabled: true,
    models,
  };
}

function panelProps(
  models: ConfigCatalogModel[],
  overrides: Record<string, unknown> = {},
): ConfigProviderRegistryPanelProps {
  return {
    copy: CONFIG_COPY.zh,
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
      copy={CONFIG_COPY.zh}
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

let mountedRoots: Root[] = [];
afterEach(async () => {
  for (const root of mountedRoots) await act(async () => root.unmount());
  mountedRoots = [];
  document.body.innerHTML = "";
});

async function renderModelDetails(models: ConfigCatalogModel[], options: {liveReferences?: Record<string, number>; imageCapabilityBusy?: boolean; onTestModel?: (modelRef: string) => void} = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoots.push(root);
  await act(async () => root.render(<ProviderModelsTab copy={CONFIG_COPY.zh} provider={provider(models)} disabled={false}
    modelQuery="" modelFilter="all" liveReferenceCountByModelRef={options.liveReferences ?? {}}
    onQueryChange={() => {}} onFilterChange={() => {}} onPin={() => {}} onUnpin={() => {}}
    onTestModel={options.onTestModel ?? (() => {})} onProbeImageInput={() => {}} imageCapabilityBusy={options.imageCapabilityBusy} />));
  // P1 list/detail split: clicking the model row opens the detail pane (no dialog).
  const row = container.querySelector<HTMLButtonElement>('[data-model-row] button');
  expect(row).not.toBeNull();
  await act(async () => row!.click());
  return container.querySelector<HTMLElement>('[data-vui-region="config-models-detail"]')!.outerHTML;
}

describe("ConfigProviderRegistryPanel", () => {
  it.each([
    ["auth_failed", "API Key"], ["network", "网络"], ["timeout", "服务负载"],
    ["rate_limited", "额度"], ["service_unavailable", "切换服务"], ["not_found", "模型名称"],
  ])("gives an actionable recovery hint for %s", (kind, hint) => {
    expect(modelTestRecoveryHint(kind, CONFIG_COPY.zh)).toContain(hint);
  });
  it("adds only discovered models matching the current search", async () => {
    const models = [model("alpha", "observed"), model("beta", "observed")];
    const onPin = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);
    await act(async () => root.render(<ProviderModelsTab copy={CONFIG_COPY.zh} provider={provider(models)} disabled={false}
      modelQuery="alpha" modelFilter="discovered" liveReferenceCountByModelRef={{}}
      onQueryChange={() => {}} onFilterChange={() => {}} onPin={onPin} onUnpin={() => {}}
      onTestModel={() => {}} onProbeImageInput={() => {}} />));
    const bulk = container.querySelector<HTMLButtonElement>('[data-model-action="pin-all"]');
    expect(bulk?.textContent).toContain("添加当前结果（1）");
    await act(async () => bulk!.click());
    expect(onPin).toHaveBeenCalledWith("relay_a", [models[0]]);
  });

  it("edits connection and context directly in the selected supplier page", async () => {
    const onSaveContextWindow = vi.fn();
    const onEditRoute = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);
    await act(async () => root.render(<ConfigProviderRegistryPanel {...panelProps([], { onSaveContextWindow, onEditRoute })} />));
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    const connection = container.querySelector('[data-vui-region="config-provider-connection"]');
    expect(connection?.textContent).toContain("https://relay.example/v1");
    expect(container.querySelector('[data-vui="split-aside"]')).toBeNull();
    const save = Array.from(connection!.querySelectorAll("button")).find((button) => button.textContent?.includes("保存上下文窗口"));
    await act(async () => save!.click());
    expect(onSaveContextWindow).toHaveBeenCalledWith("relay_a", 128000);
    await act(async () => connection!.querySelector<HTMLButtonElement>('[data-provider-action="route"]')!.click());
    expect(onEditRoute).toHaveBeenCalledWith("relay_a");
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    await act(async () => container.querySelector<HTMLButtonElement>('[data-provider-action="edit-asset"]')!.click());
    expect(document.body.querySelector('[role="dialog"]')?.textContent).toContain("高级管理 · Relay A");
  });

  it("renders a searchable model toolbar with status counts", () => {
    const models = [
      model("pinned", "pinned"),
      model("observed", "observed"),
      model("disabled", "disabled"),
    ];

    const markup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps(models)} />);

    expect(markup).toContain('aria-label="搜索模型"');
    expect(markup).toContain("搜索模型名称或 ID");
    expect(markup).toContain("全部 3");
    expect(markup).toContain("已添加 1");
    expect(markup).toContain("添加模型 1");
    expect(markup).not.toContain("不可用 1");
    expect(markup).toContain('aria-pressed="true"');
  });

  it("renders pin controls for discovered models and bulk pin banner", async () => {
    const observedMarkup = await renderModelDetails([model("observed", "observed")]);
    expect(observedMarkup).toContain("添加到模型库");
    expect(renderModels([model("observed", "observed")], { filter: "discovered" })).toContain("添加当前结果");
    expect(observedMarkup).toContain('data-model-action="pin"');
    expect(renderModels([model("observed", "observed")], { filter: "discovered" })).toContain('data-model-action="pin-all"');
    expect(renderModels([model("observed", "observed")], { filter: "pinned" })).not.toContain('data-model-action="pin-all"');
    expect(observedMarkup).not.toContain("从模型库移除");
    expect(observedMarkup).not.toContain("测试调用");
    expect(observedMarkup).toContain("验证推理 low / high");

    const pinned = model("pinned", "pinned");
    const inUseMarkup = await renderModelDetails([pinned], { liveReferences: { [pinned.modelRef]: 2 } });
    expect(inUseMarkup).toContain("使用中 · 2 个引用");
    expect(inUseMarkup).not.toContain("从模型库移除");

    // P1: actions moved into the detail pane; the row no longer carries test words.
    expect(await renderModelDetails([pinned])).toContain("测试调用");
    expect(renderModels([pinned])).not.toContain("测试调用");
    expect(await renderModelDetails([pinned])).toContain("从模型库移除");
    // Availability words live on the detail chip and dot tooltips, never as row text.
    expect(await renderModelDetails([model("disabled", "disabled")])).toContain("已禁用");
    expect(renderModels([model("disabled", "disabled")]).replace(/<[^>]+>/g, "|")).not.toContain("已禁用");
    expect(renderModels([model("disabled", "disabled")])).not.toContain("从模型库移除");
    expect(observedMarkup).not.toContain("发现 1 个可固定模型");
  });

  it("keeps model rows to dot + name + in-use badge with no status phrases", () => {
    const pinned = model("luna", "pinned");
    const markup = renderModels(
      [pinned, model("observed", "observed"), model("disabled", "disabled")],
      { liveReferences: { [pinned.modelRef]: 1 } },
    );
    const listRegion = markup.slice(
      markup.indexOf('data-vui-region="config-models-split"'),
      markup.indexOf('data-vui-region="config-models-detail"'),
    );
    expect(listRegion).toContain("luna");
    expect(listRegion).toContain('data-model-dot="ok"');
    expect(listRegion).toContain('data-model-dot="idle"');
    expect(listRegion).toContain('data-model-dot="off"');
    expect(listRegion).toContain('data-model-inuse="true"');
    expect(listRegion).toContain("使用中");
    // Negative (九产品共识): status/error words never render as row text —
    // they may only live in tooltip attributes (dot title) and the detail pane.
    const listText = listRegion.replace(/<[^>]+>/g, "|");
    for (const phrase of ["已添加", "已发现", "已禁用", "最新目录未收录", "测试通过", "测试失败", "未测试", "上游 ID"]) {
      expect(listText).not.toContain(phrase);
    }
    expect(listRegion).toContain('title="已添加"');
    expect(listRegion).toContain('title="已禁用"');
    expect(listRegion).not.toContain('data-model-action');
    expect(listRegion).not.toContain('data-term-help');
    expect(listRegion).not.toContain(">详情<");
    // ≤5 words per row: text tokens are the name plus at most the in-use badge.
    const rows = Array.from(listRegion.matchAll(/data-model-row="[^"]+"[\s\S]*?<\/div>/g)).map((match) => match[0]);
    expect(rows).toHaveLength(3);
    for (const row of rows) {
      const tokens = row.replace(/<[^>]+>/g, "\n").split("\n").flatMap((line) => line.trim().split(/\s+/)).filter(Boolean);
      expect(tokens.length).toBeLessThanOrEqual(5);
    }
  });

  it("opens model details from the row click and parks actions in the pane", async () => {
    const onPin = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);
    const observed = model("observed", "observed");
    await act(async () => root.render(<ProviderModelsTab copy={CONFIG_COPY.zh} provider={provider([observed])} disabled={false}
      modelQuery="" modelFilter="all" liveReferenceCountByModelRef={{}}
      onQueryChange={() => {}} onFilterChange={() => {}} onPin={onPin} onUnpin={() => {}}
      onTestModel={() => {}} onProbeImageInput={() => {}} />));
    // Before the click the pane is an empty invitation, rows carry no actions.
    expect(container.querySelector('[data-vui-region="config-models-detail"]')!.textContent).toContain("选择模型");
    expect(container.innerHTML).not.toContain('data-model-action="pin"');
    const row = container.querySelector<HTMLButtonElement>('[data-model-row] button');
    await act(async () => row!.click());
    const detailPane = container.querySelector('[data-vui-region="config-models-detail"]')!;
    expect(detailPane.querySelector('[data-model-detail="relay_a/observed"]')).not.toBeNull();
    const pinButton = detailPane.querySelector<HTMLButtonElement>('[data-model-action="pin"]');
    expect(pinButton?.textContent).toContain("添加到模型库");
    // Rows still carry no action buttons after selection (list pane only).
    const listPane = container.querySelector('[class*="modelListPane"]')!;
    expect(listPane.innerHTML).not.toContain('data-model-action');
    await act(async () => pinButton!.click());
    expect(onPin).toHaveBeenCalledWith("relay_a", [observed]);
  });

  it("converges model-domain buttons to one primary weight, ghost filters, and a single danger", async () => {
    // Discovered model: the only primary weight is 添加 (banner bulk + detail pin),
    // probes/test are secondary, filters stay ghost even when pressed.
    const observed = model("observed", "observed");
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);
    await act(async () => root.render(<ProviderModelsTab copy={CONFIG_COPY.zh} provider={provider([observed])} disabled={false}
      modelQuery="" modelFilter="discovered" liveReferenceCountByModelRef={{}}
      onQueryChange={() => {}} onFilterChange={() => {}} onPin={() => {}} onUnpin={() => {}}
      onTestModel={() => {}} onProbeImageInput={() => {}} />));
    const row = container.querySelector<HTMLButtonElement>('[data-model-row] button');
    await act(async () => row!.click());
    const html = container.innerHTML;

    const pressedButtons = html.match(/<button[^>]*aria-pressed="true"[^>]*>/g) ?? [];
    expect(pressedButtons.length).toBeGreaterThanOrEqual(2);
    for (const tag of pressedButtons) {
      // P1: selection states never borrow the primary weight.
      expect(tag).toContain('data-variant="ghost"');
    }
    const primaryTags = html.match(/<button[^>]*data-variant="primary"[^>]*>/g) ?? [];
    expect(primaryTags.length).toBe(2);
    for (const tag of primaryTags) {
      expect(tag.includes('data-model-action="pin"') || tag.includes('data-model-action="pin-all"')).toBe(true);
    }
    expect(html).toContain('data-variant="secondary"');
    expect(html.match(/<button[^>]*data-variant="danger"/g) ?? []).toHaveLength(0);

    // Pinned model detail: the single danger is 移除; no primary remains.
    const pinned = model("luna", "pinned");
    const pinnedMarkup = await renderModelDetails([pinned]);
    expect(pinnedMarkup.match(/<button[^>]*data-variant="danger"/g) ?? []).toHaveLength(1);
    expect(pinnedMarkup.match(/data-variant="primary"/g) ?? []).toHaveLength(0);
  });

  it("explains domain jargon through ? tooltips with bilingual short copy", async () => {
    const reasoningModel = {
      ...model("luna", "pinned"),
      reasoningEffortValues: ["low", "high"],
      reasoningVerificationStatus: "verified",
    };
    const detail = await renderModelDetails([reasoningModel]);
    expect((detail.match(/data-term-help="true"/g) ?? []).length).toBe(3);
    expect(detail).toContain('aria-label="最近测试 说明"');
    expect(detail).toContain('aria-label="能力来源 说明"');
    expect(detail).toContain('aria-label="思考深度 说明"');
    for (const key of ["termVerificationHelp", "termCapabilitiesHelp", "termReasoningHelp", "termContextWindowHelp"] as const) {
      const zh = CONFIG_COPY.zh[key];
      const en = CONFIG_COPY.en[key];
      expect(zh.length).toBeLessThanOrEqual(15);
      expect(en.length).toBeGreaterThan(0);
      expect(en).not.toBe(zh);
    }
    // The connection domain carries the context-window term on its setting row.
    const panelMarkup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps([])} />);
    expect(panelMarkup).toContain('aria-label="默认上下文上限 说明"');
  });

  it("exposes a per-model image input capability probe with current-state copy", async () => {
    const unknownMarkup = await renderModelDetails([model("terra", "observed")]);
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
    const supportedMarkup = await renderModelDetails([supportedModel]);
    const busyMarkup = await renderModelDetails([supportedModel], { imageCapabilityBusy: true });

    expect(unknownMarkup).toContain('data-model-capability-action="image_input"');
    expect(unknownMarkup).toContain("验证图片输入");
    expect(supportedMarkup).toContain("重新验证图片");
    expect(busyMarkup).toContain("验证图片中…");
  });

  it("shows verified reasoning efforts as maintained model capability", async () => {
    const reasoningModel = {
      ...model("reasoning", "observed"),
      reasoningEffortValues: ["low", "high"],
      reasoningVerificationStatus: "verified",
    };

    const markup = await renderModelDetails([reasoningModel]);

    expect(markup).toContain("推理 low / high 已验证");
    expect(markup).not.toContain("验证推理 low / high");
    expect(panelSource).toContain("testConfigLlm(");
    expect(panelSource).toContain('capability: "reasoning_effort"');
    expect(configCopyRaw).toContain("一期探测仅验证 low/high");
    expect(panelSource).toContain("reasoningProbeHint");
  });

  it("shows operator-declared reasoning contract without requiring probe", async () => {
    const declared = {
      ...model("luna", "pinned"),
      reasoningEffortValues: ["low", "medium", "high"],
      reasoningVerificationStatus: "declared",
      reasoningCapabilitySource: "operator_override",
      defaultReasoningEffort: "medium",
      reasoningAdapter: "reasoning_object",
    };
    const markup = await renderModelDetails([declared]);
    expect(markup).toContain("协议已声明 low / medium / high");
    expect(markup).toContain("思考深度: low/medium/high");
    expect(markup).not.toContain("验证推理 low / high");
  });

  it("keeps the real model test callback in details", async () => {
    const onTestModel = vi.fn();
    await renderModelDetails([model("luna", "pinned")], { onTestModel });
    const detailPane = document.querySelector('[data-vui-region="config-models-detail"]');
    const action = Array.from(detailPane!.querySelectorAll<HTMLButtonElement>("button")).find(button => button.textContent?.trim() === "测试调用");
    expect(action).toBeTruthy();
    await act(async () => action!.click());
    expect(onTestModel).toHaveBeenCalledWith("relay_a/luna");
  });

  it("distinguishes an empty directory from filtered no results", () => {
    expect(renderModels([])).toContain("还没有模型目录");
    expect(renderModels([model("alpha", "observed")], { query: "missing" })).toContain("没有匹配的模型");
  });

  it("uses low-emphasis copy for unobserved capabilities and a sticky internal scroll region", () => {
    const markup = renderModels([model("observed", "observed")]);

    // Observed (not pinned) must not spam "thinking not declared" warnings.
    expect(markup).not.toContain("思考深度: 未配置");
    expect(markup).not.toContain("reasoning: 未声明");
    // P1: the detail pane hosts everything the rows used to; the empty pane
    // invites selection instead of a per-row「详情」button.
    expect(markup).toContain('data-vui-region="config-models-detail"');
    expect(markup).toContain("选择模型");
    expect(markup).not.toContain("unknown · 未观测");
    expect(panelStyles.tableScroll).toContain("min-h-0");
    expect(panelStyles.tableScroll).not.toContain("max-h-[calc(100dvh-33rem)]");
    expect(panelStyles.tableScroll).toContain("overflow-auto");
    expect(panelStyles.modelList).toContain("overflow-y-auto");
    const heroUiImportToken = ["@heroui", "react"].join("/");
    expect(panelSource).not.toContain(heroUiImportToken);
  });

  it("only warns about missing reasoning contracts on pinned models", async () => {
    const pinned = {
      ...model("luna", "pinned"),
      reasoningEffortValues: [],
    };
    const markup = await renderModelDetails([pinned]);
    expect(markup).toContain("思考深度: 未配置");
  });

  it("fills the desktop workspace with compact Provider rows and a bottom danger zone", () => {
    expect(panelStyles.sectionSurface).toContain("h-full");
    expect(panelSource).toContain("defaultWidth: 224");
    expect(panelStyles.providerList).toContain("min-h-0");
    expect(panelStyles.providerButton).toContain("!min-h-9");
    expect(panelStyles.providerButton).toContain("!flex-row");
    expect(panelStyles.providerDot).toContain("h-2 w-2");
    expect(panelStyles.providerDotOk).toContain("state-success");
    expect(panelStyles.providerDotWarn).toContain("state-warning");
    expect(panelStyles.providerLabel).toContain("truncate");
    expect(panelStyles.providerInUseBadge).toContain("rounded-full");
    expect(panelStyles.providerAddRow).toContain("border-dashed");
    expect(panelStyles.inspectorPanel).toContain("max-h-[72vh]");
    expect(panelStyles.modelsColumn).toContain("overflow-y-auto");
    expect(panelSource).toContain('data-provider-action="edit-asset"');
    expect(panelSource).toContain('data-provider-danger-zone="true"');
    expect(panelSource).toContain("openInspector");
    expect(panelSource).not.toContain("mobileActionGroup");
  });

  it("keeps selected provider cards readable and parks help copy on hover", () => {
    expect(panelSource).not.toContain('variant={selected ? "primary" : "ghost"}');
    expect(panelSource).toContain('variant="ghost"');
    expect(panelSource).not.toContain("styles.workspaceLead");
    expect(panelSource).not.toContain("styles.connectionLead");
    expect(panelSource).not.toContain("styles.pinBannerCopy");
    expect(panelSource).not.toContain("styles.modelFilterHint");
  });

  it("resets local model tools from the actual rendered Provider identity", () => {
    expect(panelSource).toContain("}, [provider?.providerId]);");
    expect(panelSource).not.toContain("}, [selectedProviderId]);");
  });

  it("offers a preview-first merge only for an exact-contract duplicate", () => {
    expect(configCopyRaw).toContain("合并重复 Provider（高级）");
    expect(configCopyRaw).toContain("日常中转站不需要");
    expect(panelSource).toContain("mergeSectionTitle");
    expect(panelSource).toContain("mergeSectionMeta");
    expect(panelSource).toContain("previewProviderMerge(");
    expect(panelSource).toContain("applyProviderMerge(");
    expect(panelSource).toContain("confirmed: true");
  });

  it("keeps API Key and context window in setting rows above the model list", () => {
    expect(configCopyRaw).toContain("此供应商下的模型共用一把密钥");
    expect(configCopyRaw).toContain("默认上下文上限");
    expect(panelSource).toContain("apiKeySharedHint");
    expect(panelSource).toContain("contextLimitRowLabel");
    expect(panelSource).toContain("<VDialog");
    expect(configCopyRaw).toContain("保存上下文窗口");
    expect(panelSource).toContain("saveContextWindow");
    expect(panelSource).toContain("config-asset-inspector");
    const markup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([])} />,
    );
    expect(markup).toContain("更新 API Key");
    expect(markup).toContain('data-vui="settings-row"');
    expect(markup.indexOf('config-provider-connection')).toBeLessThan(markup.indexOf('data-provider-tab="models"'));
    expect(markup).toContain("已配置服务");
  });

  it("lists abnormal providers in one rail with a warn dot and no status words", () => {
    const healthy = provider([model("luna", "pinned")]);
    const broken = {
      ...provider([]),
      providerId: "relay_bad",
      label: "Broken Relay",
      status: "auth_failed" as const,
    };
    const markup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([], { rows: [healthy, broken] })} />,
    );
    expect(markup).toContain("已配置服务");
    expect(markup).toContain("Broken Relay");
    expect(markup).toContain('data-provider-dot="warn"');
    expect(markup).toContain('data-provider-dot="ok"');
    // P0 consensus: status/error words never render as row text (tooltip only).
    expect(markup).not.toContain("需要处理");
    expect(markup).not.toContain(">认证失败<");
    expect(markup).toContain('title="认证失败"');
    expect(panelSource).not.toContain("abnormalSection");
    expect(panelSource).not.toContain("showAbnormalAssets");

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
    // savePrompt must not steal the 1fr row from the workspace when present
    expect(panelStyles.sectionSurface).toContain("[&:has(>_.savePrompt)]:grid-rows-[auto_minmax(0,1fr)]");
    expect(panelStyles.savePrompt).toContain("shrink-0");
  });

  it("keeps the dot on availability only: stale catalog still shows a green dot", () => {
    const stale = { ...provider([]), status: "stale" as const, refreshDue: true };
    const markup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([], { rows: [stale] })} />,
    );
    expect(markup).toContain('data-provider-dot="ok"');
    // Freshness moved into one detail line, not the row.
    expect(markup).toContain('data-provider-freshness="stale"');
    expect(markup).toContain("模型目录已过期");
    const freshMarkup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([])} />,
    );
    expect(freshMarkup).toContain('data-provider-freshness="fresh"');
    expect(freshMarkup).toContain("模型目录已同步");
  });

  it("pins in-use providers to the top with a badge and no extra words", () => {
    const idle = { ...provider([]), providerId: "relay_idle", label: "Idle Relay" };
    const busy = { ...provider([model("luna", "pinned")]), providerId: "relay_busy", label: "Busy Relay" };
    const markup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel
        {...panelProps([], {
          rows: [idle, busy],
          liveReferenceCountByModelRef: { "relay_a/luna": 2 },
        })}
      />,
    );
    expect(markup).toContain('data-provider-inuse="true"');
    expect(markup).toContain("使用中");
    const busyIndex = markup.indexOf("Busy Relay");
    const idleIndex = markup.indexOf("Idle Relay");
    expect(busyIndex).toBeGreaterThan(-1);
    expect(idleIndex).toBeGreaterThan(busyIndex);
  });

  it("renders the inline enable switch per row and toggles through the draft callback", async () => {
    const onToggleEnabled = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);
    await act(async () => root.render(
      <ConfigProviderRegistryPanel {...panelProps([], { onToggleEnabled })} />,
    ));
    const switchInput = container.querySelector<HTMLInputElement>('input[data-vui="switch"], input[role="switch"]');
    expect(switchInput).not.toBeNull();
    expect(switchInput!.checked).toBe(true);
    expect(switchInput!.getAttribute("aria-label")).toContain("Relay A");
    await act(async () => switchInput!.click());
    expect(onToggleEnabled).toHaveBeenCalledWith("relay_a", false);
  });

  it("hides the switch when no toggle callback is wired (legacy embeds)", () => {
    const markup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps([])} />);
    expect(markup).not.toContain('data-provider-switch="true"');
  });

  it("marks disabled providers with an off dot, the 已停用 tooltip, and last position", () => {
    const off = { ...provider([]), providerId: "relay_off", label: "Off Relay", enabled: false };
    const ok = { ...provider([]), providerId: "relay_ok", label: "Ok Relay", enabled: true };
    const markup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([], { rows: [off, ok], onToggleEnabled: () => undefined })} />,
    );
    expect(markup).toContain('data-provider-dot="off"');
    expect(markup).toContain('data-provider-enabled="false"');
    expect(markup).toContain('data-provider-switch="true"');
    // Off tooltip comes from the shared providerDotOff copy.
    expect(markup).toContain("已停用");
    const offIndex = markup.indexOf("Off Relay");
    const okIndex = markup.indexOf("Ok Relay");
    expect(okIndex).toBeGreaterThan(-1);
    expect(offIndex).toBeGreaterThan(okIndex);
  });

  it("adds providers from a bottom light row that opens the existing quick setup", async () => {
    const onAddConnection = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);
    await act(async () => root.render(
      <ConfigProviderRegistryPanel {...panelProps([], { onAddConnection })} />,
    ));
    const addRow = container.querySelector<HTMLButtonElement>('[data-provider-action="add-provider"]');
    expect(addRow?.textContent).toContain("添加供应商");
    await act(async () => addRow!.click());
    expect(onAddConnection).toHaveBeenCalledTimes(1);
    expect(panelSource).not.toContain("批量停用");
  });

  it("runs one-shot health detection from the detail header", async () => {
    const onDiscover = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);
    await act(async () => root.render(
      <ConfigProviderRegistryPanel {...panelProps([], { onDiscover })} />,
    ));
    const detect = container.querySelector<HTMLButtonElement>('[data-provider-action="detect"]');
    expect(detect?.textContent).toContain("检测");
    await act(async () => detect!.click());
    expect(onDiscover).toHaveBeenCalledWith("relay_a");

    const busyMarkup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps([], {
      actionFeedback: {
        kind: "discover",
        providerId: "relay_a",
        phase: "busy",
        message: "正在检测连通与认证…",
      },
    })} />);
    expect(busyMarkup).toContain("检测中…");
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

    expect(busyMarkup).toContain("检测中…");
    expect(busyMarkup).toContain('data-provider-action="edit-asset"');
    expect(busyMarkup).toContain('data-provider-action="detect"');
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
    expect(configCopyRaw).toContain("最近失败原因");
    expect(configCopyRaw).toContain("请求超时");
    expect(panelSource).toContain("factLastFailure");
    expect(panelSource).toContain("discoveryErrTimeout");
    expect(panelSource).toContain("function DiagnosticsTab");
    const timedOut = { ...provider([]), status: "discovery_failed" as const, lastErrorType: "timeout" };
    const markup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([], { rows: [timedOut] })} />,
    );
    expect(markup).toContain("discovery_failed");
    expect(markup).toContain("修改地址与协议");
  });
});
