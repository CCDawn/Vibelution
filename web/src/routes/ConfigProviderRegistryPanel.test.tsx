// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

vi.mock("./config/ChatGPTSubscriptionPanel", () => ({
  ChatGPTSubscriptionPanel: () => <div data-testid="chatgpt-subscription-panel">Mock ChatGPT subscription setup</div>,
}));

/** Panel source + shared bilingual copy table (wave 4): UI strings live in configCopy. */
const panelSource = `${panelSourceRaw}
${configCopyRaw}`;
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
beforeEach(() => vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true));
afterEach(async () => {
  for (const root of mountedRoots) await act(async () => root.unmount());
  mountedRoots = [];
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

async function renderModelDetails(models: ConfigCatalogModel[], options: {liveReferences?: Record<string, number>; imageCapabilityBusy?: boolean; onTestModel?: (modelRef: string) => void; onUpdateModel?: (providerId: string, modelKey: string, edits: Record<string, string | boolean>) => void; modelUpdateBusy?: boolean} = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoots.push(root);
  await act(async () => root.render(<ProviderModelsTab copy={CONFIG_COPY.zh} provider={provider(models)} disabled={false}
    modelQuery="" modelFilter="all" liveReferenceCountByModelRef={options.liveReferences ?? {}}
    onQueryChange={() => {}} onFilterChange={() => {}} onPin={() => {}} onUnpin={() => {}}
    onTestModel={options.onTestModel ?? (() => {})} onProbeImageInput={() => {}} imageCapabilityBusy={options.imageCapabilityBusy}
    onUpdateModel={options.onUpdateModel} modelUpdateBusy={options.modelUpdateBusy} />));
  // P1 list/detail split: clicking the model row opens the detail pane (no dialog).
  const row = container.querySelector<HTMLButtonElement>('[data-model-row] button');
  expect(row).not.toBeNull();
  await act(async () => row!.click());
  return container.querySelector<HTMLElement>('[data-vui-region="config-models-detail"]')!.outerHTML;
}

function buttonByText(container: ParentNode, text: string): HTMLButtonElement {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((item) => item.textContent?.trim() === text);
  if (!button) throw new Error(`Missing button: ${text}`);
  return button;
}

function buttonByLabel(container: ParentNode, label: string): HTMLButtonElement {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((item) => item.getAttribute("aria-label") === label);
  if (!button) throw new Error(`Missing button label: ${label}`);
  return button;
}

async function changeInput(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function activateTab(container: HTMLElement, label: string) {
  const tab = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
    .find((item) => item.textContent === label);
  if (!tab) throw new Error(`Missing tab: ${label}`);
  await act(async () => tab.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
}

function providerButton(container: HTMLElement, id: string) {
  const button = [...container.querySelectorAll<HTMLButtonElement>('[data-provider-enabled] button[aria-pressed]')]
    .find((item) => item.title.split("\n").at(-1) === id);
  if (!button) throw new Error(`Missing provider: ${id}`);
  return button;
}

async function mountWorkspace(initialProps: ConfigProviderRegistryPanelProps) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoots.push(root);
  function Harness({ currentProps }: { currentProps: ConfigProviderRegistryPanelProps }) {
    const [selected, setSelected] = React.useState(initialProps.selectedProviderId);
    const [tab, setTab] = React.useState(initialProps.selectedTab);
    const [drafts, setDrafts] = React.useState(initialProps.modelEditorDrafts ?? {});
    return <ConfigProviderRegistryPanel {...currentProps} selectedProviderId={selected} selectedTab={tab}
      modelEditorDrafts={currentProps.onModelEditorDraftChange ? drafts : currentProps.modelEditorDrafts}
      onModelEditorDraftChange={currentProps.onModelEditorDraftChange ? (modelRef, edits) => {
        currentProps.onModelEditorDraftChange?.(modelRef, edits);
        setDrafts((current) => ({ ...current, [modelRef]: edits }));
      } : undefined}
      onSelectProvider={(providerId) => { currentProps.onSelectProvider(providerId); setSelected(providerId); }}
      onSelectTab={(value) => { currentProps.onSelectTab(value); setTab(value); }} />;
  }
  async function rerender(props: ConfigProviderRegistryPanelProps) {
    await act(async () => root.render(<Harness currentProps={props} />));
  }
  await rerender(initialProps);
  return { container, rerender };
}

describe("direct model services workspace", () => {
  async function mount(props: ConfigProviderRegistryPanelProps) {
    return (await mountWorkspace(props)).container;
  }

  it("opens the service and model list directly with nearby real feedback", async () => {
    const onSelectProvider = vi.fn();
    const container = await mount(panelProps([model("pinned", "pinned")], {
      onSelectProvider,
      actionFeedback: { kind: "model", providerId: "relay_a", phase: "error", message: "真实调用失败" },
    }));
    expect(container.querySelector('[data-vui="split-sidebar"]')).not.toBeNull();
    expect(container.querySelector('[data-vui-region="config-models-main"]')?.textContent).toContain("Relay A");
    expect(container.querySelector('[data-model-row="relay_a/pinned"]')).not.toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("真实调用失败");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(onSelectProvider).not.toHaveBeenCalled();
  });

  it("shows enabled failures and disabled services together without changing selection", async () => {
    const onSelectProvider = vi.fn();
    const enabledError = { ...provider([]), providerId: "relay_broken", label: "Broken Relay", status: "auth_failed" };
    const disabled = { ...provider([]), providerId: "relay_off", label: "Off Relay", enabled: false };
    const container = await mount(panelProps([], { rows: [disabled, enabledError], selectedProviderId: "relay_broken", onSelectProvider }));
    expect(container.querySelector('[data-provider-status="auth_failed"] [data-provider-dot="warn"]')).not.toBeNull();
    expect(container.querySelectorAll('[data-provider-enabled]')).toHaveLength(2);
    expect(container.textContent).not.toContain("未启用的服务 (");
    expect(providerButton(container, "relay_off")).toBeDefined();
    expect(providerButton(container, "relay_broken").getAttribute("aria-pressed")).toBe("true");
    expect(onSelectProvider).not.toHaveBeenCalled();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("waits for saved enabled props and retains the selected service when it is restored", async () => {
    const onSelectProvider = vi.fn();
    const onToggleEnabled = vi.fn();
    const active = { ...provider([]), providerId: "relay_on", label: "Online Relay" };
    const restored = { ...provider([]), providerId: "relay_off_a", label: "Off Relay A", enabled: false };
    const remaining = { ...provider([]), providerId: "relay_off_b", label: "Off Relay B", enabled: false };
    const props = panelProps([], { rows: [active, restored, remaining], selectedProviderId: "relay_on", onSelectProvider, onToggleEnabled });
    const { container, rerender } = await mountWorkspace(props);
    await act(async () => providerButton(container, "relay_off_a").click());
    const selectedRow = providerButton(container, "relay_off_a").closest('[data-provider-enabled]')!;
    const toggle = selectedRow.querySelector<HTMLInputElement>('[role="switch"]')!;
    await act(async () => toggle.click());
    expect(onToggleEnabled).toHaveBeenCalledExactlyOnceWith("relay_off_a", true);
    expect(toggle.checked).toBe(false);
    await rerender({ ...props, rows: [active, { ...restored, enabled: true }, remaining] });
    expect(providerButton(container, "relay_off_a").getAttribute("aria-pressed")).toBe("true");
    expect(providerButton(container, "relay_off_a").closest('[data-provider-enabled]')?.getAttribute("data-provider-enabled")).toBe("true");
    expect(providerButton(container, "relay_off_b").closest('[data-provider-enabled]')?.getAttribute("data-provider-enabled")).toBe("false");
    expect(onSelectProvider).toHaveBeenCalledExactlyOnceWith("relay_off_a");
  });

  it("allows an all-disabled catalog to be recovered through the same workspace", async () => {
    const disabledA = { ...provider([]), providerId: "relay_off_a", label: "Off Relay A", enabled: false };
    const disabledB = { ...provider([]), providerId: "relay_off_b", label: "Off Relay B", enabled: false };
    const props = panelProps([], { rows: [disabledA, disabledB], selectedProviderId: "relay_off_a" });
    const { container, rerender } = await mountWorkspace(props);
    expect(container.querySelectorAll('[data-provider-enabled="false"]')).toHaveLength(2);
    await rerender({ ...props, rows: [{ ...disabledA, enabled: true }, { ...disabledB, enabled: true }] });
    expect(container.querySelectorAll('[data-provider-enabled="true"]')).toHaveLength(2);
    expect(container.textContent).not.toContain("未启用的服务 (");
    expect(providerButton(container, "relay_off_a").getAttribute("aria-pressed")).toBe("true");
  });

  it("keeps the current model and its text draft while provider search hides its row", async () => {
    const onSelectProvider = vi.fn();
    const onUpdateModel = vi.fn();
    const current = { ...model("luna", "pinned", "Luna"), draftEntry: { label: "Luna", upstream_id: "luna-upstream" } };
    const other = { ...provider([]), providerId: "relay_b", label: "Relay B" };
    const onModelEditorDraftChange = vi.fn();
    const container = await mount(panelProps([current], { rows: [provider([current]), other], onSelectProvider, onUpdateModel, onModelEditorDraftChange }));
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_a/luna"] button')!.click());
    const input = container.querySelector<HTMLInputElement>('[data-model-edit-field="label"] input')!;
    await changeInput(input, "Unsaved Luna");
    const search = container.querySelector<HTMLInputElement>('input[aria-label="搜索服务商"]')!;
    await changeInput(search, "Relay B");
    expect(container.querySelectorAll('[data-provider-enabled]')).toHaveLength(1);
    expect(providerButton(container, "relay_b")).toBeDefined();
    expect(container.querySelector('[data-model-detail="relay_a/luna"]')).not.toBeNull();
    expect(input.value).toBe("Unsaved Luna");
    expect(onSelectProvider).not.toHaveBeenCalled();
    expect(onUpdateModel).not.toHaveBeenCalled();
    expect(onModelEditorDraftChange).toHaveBeenCalledWith("relay_a/luna", { label: "Unsaved Luna" });
    expect(container.querySelector('[data-model-action="save-edit"]')).toBeNull();
    await changeInput(search, "");
    expect(providerButton(container, "relay_a").getAttribute("aria-pressed")).toBe("true");
    expect(input.value).toBe("Unsaved Luna");
  });

  it("retains controlled drafts by full model ref when switching same-name models across providers", async () => {
    const onUpdateModel = vi.fn();
    const onModelEditorDraftChange = vi.fn();
    const first = model("shared", "pinned", "Same model");
    const second = { ...first, modelRef: "relay_b/shared" };
    const rows = [provider([first]), { ...provider([second]), providerId: "relay_b", label: "Relay B" }];
    const container = await mount(panelProps([], { rows, onUpdateModel, onModelEditorDraftChange }));
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_a/shared"] button')!.click());
    await changeInput(container.querySelector<HTMLInputElement>('[data-model-edit-field="context_window"] input')!, "unfinished");
    await act(async () => providerButton(container, "relay_b").click());
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_b/shared"] button')!.click());
    const secondContext = container.querySelector<HTMLInputElement>('[data-model-edit-field="context_window"] input')!;
    expect(secondContext.value).not.toBe("unfinished");
    await changeInput(container.querySelector<HTMLInputElement>('[data-model-edit-field="label"] input')!, "Second draft");
    await act(async () => providerButton(container, "relay_a").click());
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_a/shared"] button')!.click());
    const firstContext = container.querySelector<HTMLInputElement>('[data-model-edit-field="context_window"] input')!;
    expect(firstContext.value).toBe("unfinished");
    expect(firstContext.getAttribute("aria-invalid")).toBe("true");
    expect(container.querySelector<HTMLInputElement>('[data-model-edit-field="label"] input')!.value).toBe("Same model");
    expect(onModelEditorDraftChange).toHaveBeenCalledWith("relay_a/shared", { context_window: "unfinished" });
    expect(onModelEditorDraftChange).toHaveBeenCalledWith("relay_b/shared", { label: "Second draft" });
    expect(onUpdateModel).not.toHaveBeenCalled();
    expect(container.querySelector('[data-model-action="save-edit"]')).toBeNull();
  });

  it("returns from a model to its list and restores that entity's draft when reopened", async () => {
    const onUpdateModel = vi.fn();
    const container = await mount(panelProps([model("first", "pinned"), model("second", "pinned")], { onUpdateModel }));
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_a/first"] button')!.click());
    const input = container.querySelector<HTMLInputElement>('[data-model-edit-field="label"] input')!;
    await changeInput(input, "First draft");
    await act(async () => buttonByLabel(container, "返回模型列表").click());
    expect(container.querySelector<HTMLElement>('[data-vui-region="config-models-detail"]')!.hidden).toBe(true);
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_a/second"] button')!.click());
    expect(container.querySelector<HTMLInputElement>('[data-model-edit-field="label"] input')!.value).toBe("second");
    await act(async () => buttonByLabel(container, "返回模型列表").click());
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_a/first"] button')!.click());
    expect(container.querySelector<HTMLInputElement>('[data-model-edit-field="label"] input')!.value).toBe("First draft");
  });

  it("hides model search and status filters while editing and restores them on return", async () => {
    const { container } = await mountWorkspace(panelProps([model("luna", "pinned")], { onUpdateModel: vi.fn() }));
    const search = container.querySelector<HTMLInputElement>(`input[aria-label="${CONFIG_COPY.zh.searchModelsAria}"]`)!;
    const filter = container.querySelector<HTMLButtonElement>(`[role="combobox"][aria-label="${CONFIG_COPY.zh.modelFiltersAria}"]`)!;
    expect(search.closest<HTMLElement>("[hidden]")).toBeNull();
    expect(filter.closest<HTMLElement>("[hidden]")).toBeNull();
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_a/luna"] button')!.click());
    expect(search.closest<HTMLElement>("[hidden]")?.hidden).toBe(true);
    expect(filter.closest<HTMLElement>("[hidden]")?.hidden).toBe(true);
    const back = buttonByLabel(container, "返回模型列表");
    expect(back.textContent?.trim()).toBe("");
    const details = container.querySelector<HTMLDetailsElement>('[data-model-detail] > details')!;
    expect(details.open).toBe(false);
    expect(details.querySelector('[data-model-resolved-route]')).not.toBeNull();
    expect(details.querySelector('[data-model-section="verification"]')).not.toBeNull();
    expect(details.querySelector('[data-model-section="capabilities"]')).not.toBeNull();
    expect(buttonByText(details, CONFIG_COPY.zh.unpinAction)).toBeDefined();
    expect(buttonByText(container, CONFIG_COPY.zh.testCall).closest("details")).toBeNull();
    expect(details.textContent).toContain("relay_a/luna");
    expect(container.querySelector('[data-model-detail]')!.textContent!.split("relay_a/luna")).toHaveLength(2);
    await act(async () => back.click());
    expect(search.closest<HTMLElement>("[hidden]")).toBeNull();
    expect(filter.closest<HTMLElement>("[hidden]")).toBeNull();
  });

  it.each([true, false])("stages only the model enabled whitelist field from the list switch without saving or selecting it (%s)", async (enabled) => {
    const onModelEditorDraftChange = vi.fn();
    const onUpdateModel = vi.fn();
    const current = { ...model("luna", "pinned"), draftEntry: { enabled, wire_protocol: "responses", label: "Luna" } };
    const { container } = await mountWorkspace(panelProps([current], { onModelEditorDraftChange, onUpdateModel }));
    const toggle = container.querySelector<HTMLInputElement>('[data-model-row="relay_a/luna"] [role="switch"]')!;
    expect(toggle.checked).toBe(enabled);
    await act(async () => toggle.click());
    expect(onModelEditorDraftChange).toHaveBeenCalledExactlyOnceWith("relay_a/luna", { enabled: !enabled });
    expect(toggle.checked).toBe(!enabled);
    expect(container.querySelector('[data-model-detail]')).toBeNull();
    expect(onUpdateModel).not.toHaveBeenCalled();
    await act(async () => toggle.click());
    expect(onModelEditorDraftChange).toHaveBeenLastCalledWith("relay_a/luna", {});
    expect(onUpdateModel).not.toHaveBeenCalled();
  });

  it.each([{ disabled: true, modelUpdateBusy: false }, { disabled: false, modelUpdateBusy: true }])(
    "prevents model switch draft changes while disabled or saving ($disabled, $modelUpdateBusy)",
    async ({ disabled, modelUpdateBusy }) => {
      const onModelEditorDraftChange = vi.fn();
      const current = { ...model("luna", "pinned"), draftEntry: { enabled: true } };
      const { container } = await mountWorkspace(panelProps([current], { disabled, modelUpdateBusy, onModelEditorDraftChange }));
      const toggle = container.querySelector<HTMLInputElement>('[data-model-row="relay_a/luna"] [role="switch"]')!;
      expect(toggle.disabled).toBe(true);
      await act(async () => toggle.click());
      expect(onModelEditorDraftChange).not.toHaveBeenCalled();
    },
  );

  it("tests the exact selected model ref and keeps other providers out of the call", async () => {
    const onTestModel = vi.fn();
    const onProbeImageInput = vi.fn();
    const onDiscover = vi.fn();
    const rows = [provider([model("first", "pinned")]), {
      ...provider([{ ...model("actual", "pinned"), modelRef: "relay_b/actual" }]), providerId: "relay_b", label: "Relay B",
    }];
    const container = await mount(panelProps([], { rows, onTestModel, onProbeImageInput, onDiscover }));
    await act(async () => providerButton(container, "relay_b").click());
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_b/actual"] button')!.click());
    await act(async () => buttonByText(container, CONFIG_COPY.zh.testCall).click());
    const advanced = container.querySelector<HTMLDetailsElement>('[data-model-detail] > details')!;
    await act(async () => advanced.querySelector<HTMLElement>("summary")!.click());
    expect(advanced.open).toBe(true);
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-capability-action="image_input"]')!.click());
    expect(onTestModel).toHaveBeenCalledExactlyOnceWith("relay_b/actual");
    expect(onProbeImageInput).toHaveBeenCalledExactlyOnceWith("relay_b/actual");
    expect(onDiscover).not.toHaveBeenCalled();
  });

  it("fetches the selected service catalog from connection settings without testing an unavailable model", async () => {
    const onDiscover = vi.fn();
    const onTestModel = vi.fn();
    const container = await mount(panelProps([model("seen", "observed"), model("missing", "missing_remote")], { onDiscover, onTestModel }));
    await activateTab(container, "连接");
    await act(async () => container.querySelector<HTMLButtonElement>('[data-provider-action="detect"]')!.click());
    expect(onDiscover).toHaveBeenCalledExactlyOnceWith("relay_a");
    expect(onTestModel).not.toHaveBeenCalled();
  });

  it("keeps busy model feedback visible and prevents duplicate calls", async () => {
    const onTestModel = vi.fn();
    const container = await mount(panelProps([model("pinned", "pinned")], {
      onTestModel,
      actionFeedback: { kind: "model", providerId: "relay_a", phase: "busy", message: "正在真实调用模型" },
    }));
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_a/pinned"] button')!.click());
    expect(container.querySelector('[role="status"]')?.textContent).toContain("正在真实调用模型");
    const test = buttonByText(container, CONFIG_COPY.zh.testCall);
    expect(test.disabled).toBe(true);
    await act(async () => test.click());
    expect(onTestModel).not.toHaveBeenCalled();
  });

  it.each([
    { enabled: true, retryEnabled: false },
    { enabled: false, retryEnabled: true },
  ])("retries an enabled-action failure toward the current opposite state ($enabled)", async ({ enabled, retryEnabled }) => {
    const onToggleEnabled = vi.fn();
    const row = { ...provider([]), enabled };
    const container = await mount(panelProps([], {
      rows: [row],
      actionFeedback: { kind: "enabled", providerId: "relay_a", phase: "error", message: "保存失败" },
      onToggleEnabled,
    }));
    const retry = container.querySelector<HTMLButtonElement>('[data-provider-retry-action="enabled"]')!;

    expect(retry.textContent).toBe(CONFIG_COPY.zh.retryAction);
    await act(async () => retry.click());
    expect(onToggleEnabled).toHaveBeenCalledExactlyOnceWith("relay_a", retryEnabled);
  });

  it("does not show the enabled retry for other feedback kinds or busy feedback", () => {
    const props = panelProps([], {
      actionFeedback: { kind: "model", providerId: "relay_a", phase: "error", message: "模型调用失败" },
      onToggleEnabled: vi.fn(),
    });
    const compactMarkup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...props} />);
    const workspaceMarkup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...props} />);
    const busyMarkup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps([], {
      actionFeedback: { kind: "enabled", providerId: "relay_a", phase: "busy", message: "正在保存" },
      onToggleEnabled: vi.fn(),
    })} />);
    const missingRowMarkup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps([], {
      rows: [],
      actionFeedback: { kind: "enabled", providerId: "missing-provider", phase: "error", message: "保存失败" },
      onToggleEnabled: vi.fn(),
    })} />);

    expect(compactMarkup).not.toContain('data-provider-retry-action="enabled"');
    expect(workspaceMarkup).not.toContain('data-provider-retry-action="enabled"');
    expect(busyMarkup).not.toContain('data-provider-retry-action="enabled"');
    expect(missingRowMarkup).not.toContain('data-provider-retry-action="enabled"');
  });

  it("retries enabled-action failures from workspace feedback", async () => {
    const onToggleEnabled = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);
    await act(async () => root.render(
      <ConfigProviderRegistryPanel {...panelProps([], {
        actionFeedback: { kind: "enabled", providerId: "relay_a", phase: "error", message: "保存失败" },
        onToggleEnabled,
      })} />,
    ));
    const retry = container.querySelector<HTMLButtonElement>('[data-provider-retry-action="enabled"]')!;

    await act(async () => retry.click());
    expect(onToggleEnabled).toHaveBeenCalledExactlyOnceWith("relay_a", false);
  });

  it.each([
    { disabled: true, saveBusy: false },
    { disabled: false, saveBusy: true },
  ])("keeps the workspace enabled-action retry disabled when disabled or busy", async ({ disabled, saveBusy }) => {
    const onToggleEnabled = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);
    await act(async () => root.render(
      <ConfigProviderRegistryPanel {...panelProps([], {
        disabled,
        actionFeedback: { kind: "enabled", providerId: "relay_a", phase: "error", message: "保存失败" },
        onToggleEnabled,
        saveBusy,
      })} />,
    ));
    const retry = container.querySelector<HTMLButtonElement>('[data-provider-retry-action="enabled"]')!;

    expect(retry.disabled).toBe(true);
    await act(async () => retry.click());
    expect(onToggleEnabled).not.toHaveBeenCalled();
  });

  it("reaches connection, credentials and advanced diagnostics through the selected service tabs", async () => {
    const onEditRoute = vi.fn();
    const onEditCredential = vi.fn();
    const onSaveContextWindow = vi.fn();
    const container = await mount(panelProps([model("pinned", "pinned")], { onEditRoute, onEditCredential, onSaveContextWindow }));
    const connection = container.querySelector<HTMLElement>('[data-vui-region="config-provider-connection"]')!;
    expect(connection.hidden).toBe(true);
    await activateTab(container, "连接");
    expect(connection.hidden).toBe(false);
    expect(container.querySelector<HTMLElement>('[data-provider-tab="models"]')!.hidden).toBe(true);
    await act(async () => container.querySelector<HTMLButtonElement>('[data-provider-action="route"]')!.click());
    await act(async () => buttonByText(connection, "更新 API Key").click());
    await act(async () => buttonByText(connection, CONFIG_COPY.zh.saveContextWindow).click());
    expect(onEditRoute).toHaveBeenCalledExactlyOnceWith("relay_a");
    expect(onEditCredential).toHaveBeenCalledExactlyOnceWith("relay_a");
    expect(onSaveContextWindow).toHaveBeenCalledExactlyOnceWith("relay_a", 128000);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    await act(async () => container.querySelector<HTMLButtonElement>('[data-provider-action="edit-asset"]')!.click());
    const inspector = document.querySelector<HTMLElement>('[data-vui-region="config-asset-inspector"]')!;
    await act(async () => buttonByText(inspector, CONFIG_COPY.zh.diagnosticsMergeAdvanced).click());
    expect(inspector.textContent).toContain(CONFIG_COPY.zh.wireProtocolLabel);
    expect(inspector.textContent).toContain(CONFIG_COPY.zh.registryDiagnosticsTitle);
  });
});

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
    const { container } = await mountWorkspace(panelProps([], { onSaveContextWindow, onEditRoute }));
    await activateTab(container, "连接");
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

  it("filters models through one searchable status select with added and available counts", async () => {
    const models = [
      model("pinned", "pinned"),
      model("observed", "observed"),
      model("disabled", "disabled"),
    ];

    const { container } = await mountWorkspace(panelProps(models));
    expect(container.querySelector<HTMLInputElement>('input[aria-label="搜索模型"]')?.placeholder).toBe("搜索模型名称或 ID");
    const filters = container.querySelectorAll<HTMLButtonElement>(`[role="combobox"][aria-label="${CONFIG_COPY.zh.modelFiltersAria}"]`);
    expect(filters).toHaveLength(1);
    expect(filters[0].textContent).toContain("已添加 · 1");
    await act(async () => filters[0].dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
    const options = [...document.querySelectorAll<HTMLElement>('[role="option"]')];
    expect(options.map((option) => option.textContent)).toEqual(["全部 · 3", "已添加 · 1", "可添加 · 1"]);
    await act(async () => options.find((option) => option.textContent === "可添加 · 1")!.click());
    expect(container.querySelector('[data-model-row="relay_a/observed"]')).not.toBeNull();
    expect(container.querySelector('[data-model-row="relay_a/pinned"]')).toBeNull();
    expect(container.querySelector('[data-model-row="relay_a/disabled"]')).toBeNull();
    expect(container.querySelector('[data-provider-action="discover-models"]')?.textContent).toBe("发现模型");
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

  // Wave 3 governance path B: whitelist-governed model entry editing.
  function pinnedModelWithDraft(): ConfigCatalogModel {
    return {
      ...model("luna", "pinned", "Luna"),
      reasoningEffortValues: ["low", "medium", "high"],
      defaultReasoningEffort: "medium",
      draftEntry: {
        upstream_id: "luna-upstream",
        label: "Luna",
        enabled: true,
        context_window: 262144,
        wire_protocol: "responses",
        interaction_contract: "tool_chat",
        defaults: {
          reasoning_effort_values: ["low", "medium", "high"],
          reasoning_effort_adapter: "reasoning_object",
          default_reasoning_effort: "medium",
          streaming: true,
        },
      },
    };
  }

  it("renders the whitelist edit form with read-only protocol facts for pinned models", async () => {
    const markup = await renderModelDetails(
      [pinnedModelWithDraft()],
      { onUpdateModel: () => undefined },
    );
    expect(markup).toContain('data-model-section="edit"');
    // Entry fields and existing overrides are visible; optional generation
    // parameters must be added explicitly rather than prefilled by the page.
    const fields = [...markup.matchAll(/data-model-edit-field="([^"]+)"/g)].map((match) => match[1]);
    expect(fields).toEqual([
      "label",
      "model",
      "context_window",
      "enabled",
      "streaming",
      "default_reasoning_effort",
    ]);
    expect(markup).toContain(`aria-label="${CONFIG_COPY.zh.modelEditAddParameter}"`);
    // The resolved route remains a read-only fact in advanced details.
    expect(markup).toContain('data-model-resolved-route="responses"');
    expect(markup).toContain("OpenAI Responses");
    expect(markup).not.toContain('data-model-protocol-field=');
    expect(markup).not.toContain(">wire_protocol<");
    expect(markup).not.toContain(">interaction_contract<");
    expect(markup).not.toContain(">reasoning_effort_adapter<");
    // Save starts disabled (nothing edited yet).
    const save = markup.match(/<button[^>]*data-model-action="save-edit"[^>]*>/)?.[0] ?? "";
    expect(save).toContain("disabled");
  });

  it("keeps the edit form away from discovered models and legacy callers", async () => {
    const observed = model("novas", "observed");
    const withCallback = await renderModelDetails([observed], { onUpdateModel: () => undefined });
    expect(withCallback).not.toContain('data-model-section="edit"');
    const withoutCallback = await renderModelDetails([pinnedModelWithDraft()]);
    expect(withoutCallback).not.toContain('data-model-section="edit"');
    // Credential fields never appear as editable model fields.
    const markup = await renderModelDetails([pinnedModelWithDraft()], { onUpdateModel: () => undefined });
    expect(markup).not.toContain('data-model-edit-field="api_key_env"');
    expect(markup).not.toContain('data-model-edit-field="wire_protocol"');
  });

  it("sends only changed whitelist fields on save", async () => {
    const onUpdateModel = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);
    await act(async () => root.render(<ProviderModelsTab copy={CONFIG_COPY.zh} provider={provider([pinnedModelWithDraft()])} disabled={false}
      modelQuery="" modelFilter="all" liveReferenceCountByModelRef={{}}
      onQueryChange={() => {}} onFilterChange={() => {}} onPin={() => {}} onUnpin={() => {}}
      onTestModel={() => {}} onProbeImageInput={() => {}} onUpdateModel={onUpdateModel} />));
    const row = container.querySelector<HTMLButtonElement>('[data-model-row] button');
    await act(async () => row!.click());
    // Edit two whitelist fields through the real controlled inputs.
    const labelInput = container.querySelector<HTMLInputElement>('[data-model-edit-field="label"] input')!;
    const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    await act(async () => {
      valueSetter.call(labelInput, "Luna fast");
      labelInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const windowInput = container.querySelector<HTMLInputElement>('[data-model-edit-field="context_window"] input')!;
    await act(async () => {
      valueSetter.call(windowInput, "131072");
      windowInput.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const save = container.querySelector<HTMLButtonElement>('[data-model-action="save-edit"]')!;
    expect(save.disabled).toBe(false);
    await act(async () => save.click());
    expect(onUpdateModel).toHaveBeenCalledTimes(1);
    expect(onUpdateModel).toHaveBeenCalledWith("relay_a", "luna", {
      label: "Luna fast",
      context_window: "131072",
    });
  });

  it("adds an optional parameter without inventing an override until the user enters a value", async () => {
    const onUpdateModel = vi.fn();
    const { container } = await mountWorkspace(panelProps([pinnedModelWithDraft()], { onUpdateModel }));
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-row="relay_a/luna"] button')!.click());
    expect(container.querySelector('[data-model-edit-field="temperature"]')).toBeNull();
    const addParameter = container.querySelector<HTMLButtonElement>(`[role="combobox"][aria-label="${CONFIG_COPY.zh.modelEditAddParameter}"]`)!;
    await act(async () => addParameter.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
    const options = [...document.querySelectorAll<HTMLElement>('[role="option"]')];
    expect(options.some((option) => option.textContent === CONFIG_COPY.zh.modelEditFieldTemperature)).toBe(true);
    expect(options.some((option) => /API Key|wire_protocol|interaction_contract|reasoning_effort_adapter/.test(option.textContent ?? ""))).toBe(false);
    await act(async () => options.find((option) => option.textContent === CONFIG_COPY.zh.modelEditFieldTemperature)!.click());
    const input = container.querySelector<HTMLInputElement>('[data-model-edit-field="temperature"] input')!;
    expect(input.value).toBe("");
    const save = container.querySelector<HTMLButtonElement>('[data-model-action="save-edit"]')!;
    expect(save.disabled).toBe(true);
    expect(onUpdateModel).not.toHaveBeenCalled();
    await changeInput(input, "0.25");
    await act(async () => save.click());
    expect(onUpdateModel).toHaveBeenCalledExactlyOnceWith("relay_a", "luna", { temperature: "0.25" });
  });

  it("reserves primary weight for add actions and danger weight for model removal", async () => {
    // Discovered model: the only primary weight is 添加 (banner bulk + detail pin),
    // probes/test are secondary; selecting a model does not become primary.
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
    expect(pressedButtons.length).toBe(1);
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

  it("uses low-emphasis copy for unobserved capabilities and invites model selection", () => {
    const markup = renderModels([model("observed", "observed")]);

    // Observed (not pinned) must not spam "thinking not declared" warnings.
    expect(markup).not.toContain("思考深度: 未配置");
    expect(markup).not.toContain("reasoning: 未声明");
    // P1: the detail pane hosts everything the rows used to; the empty pane
    // invites selection instead of a per-row「详情」button.
    expect(markup).toContain('data-vui-region="config-models-detail"');
    expect(markup).toContain("选择模型");
    expect(markup).not.toContain("unknown · 未观测");
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

  it("uses shared provider panes and keeps destructive provider controls in advanced management", async () => {
    expect(panelSource).toContain("layoutId={WORKBENCH_LAYOUT_IDS.configModelAssets}");
    const { container } = await mountWorkspace(panelProps([]));
    expect(container.querySelector('[data-provider-danger-zone]')).toBeNull();
    await activateTab(container, "连接");
    await act(async () => container.querySelector<HTMLButtonElement>('[data-provider-action="edit-asset"]')!.click());
    expect(document.querySelector('[data-vui-region="config-asset-inspector"] [data-provider-danger-zone="true"]')).not.toBeNull();
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

  it("keeps API Key and context window in their connection tab with settings rows", () => {
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
    expect(markup).toContain('role="tablist"');
    expect(markup).toContain("连接");
    expect(markup).toContain("已配置服务");
  });

  it("retains connection controls, resolved route facts, and errors in the compact workspace", () => {
    const markup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps([], {
      actionFeedback: {
        kind: "credential",
        providerId: "relay_a",
        phase: "error",
        message: "API Key 保存失败",
      },
    })} />);
    const summary = markup.slice(
      markup.indexOf('data-vui-region="config-provider-connection"'),
      markup.indexOf('data-provider-tab="models"'),
    );
    expect(summary).toContain('data-provider-action="route"');
    expect(summary).toContain("修改地址与协议");
    expect(summary).toContain("路线");
    expect(summary).toContain("OpenAI Responses");
    expect(summary).toContain('data-provider-resolved-route="responses"');
    expect(summary).not.toContain("驱动：");
    expect(summary).toContain("更新 API Key");
    expect(summary).toContain("调整上限与部署详情");
    expect(summary).toContain("默认上下文上限");
    expect(markup).toContain('role="alert"');
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
    // The surrounding settings page owns its single save action. The provider
    // workspace keeps its full-height list/detail surface when the page is dirty.
    expect(dirty).not.toContain('data-save-prompt="pending"');
    expect(dirty).not.toContain(">保存更改<");
    expect(dirty).toContain('data-vui-region="config-models-main"');
  });

  it("keeps the dot on availability only: stale catalog still shows a green dot", () => {
    const stale = { ...provider([]), status: "stale" as const, refreshDue: true };
    const markup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([], { rows: [stale] })} />,
    );
    expect(markup).toContain('data-provider-dot="ok"');
    // Freshness remains machine-readable without adding a permanent status sentence.
    expect(markup).toContain('data-provider-freshness="stale"');
    expect(markup).not.toContain("模型目录已过期");
    const freshMarkup = renderToStaticMarkup(
      <ConfigProviderRegistryPanel {...panelProps([])} />,
    );
    expect(freshMarkup).toContain('data-provider-freshness="fresh"');
    expect(freshMarkup).not.toContain("模型目录已同步");
  });

  it("does not call an untested provider catalog synchronized", () => {
    const untested = { ...provider([model("manual", "pinned")]), status: "not_discovered" as const, lastSuccessAt: "", lastAttemptAt: "" };
    const markup = renderToStaticMarkup(<ConfigProviderRegistryPanel {...panelProps([], { rows: [untested] })} />);
    expect(markup).toContain('data-provider-freshness="unchecked"');
    expect(markup).not.toContain("模型目录已同步");
    expect(markup).toContain("manual");
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

  it("disambiguates same-name providers without changing row selection or switch semantics", async () => {
    const anthroDirect = { ...provider([]), providerId: "anthropic_direct", label: "Anthropic" };
    const anthroRelay = { ...provider([]), providerId: "anthropic_relay", label: "Anthropic" };
    const xiaomiDirect = { ...provider([]), providerId: "xiaomi_direct", label: "Xiaomi" };
    const xiaomiRelay = { ...provider([]), providerId: "xiaomi_relay", label: "Xiaomi" };
    const onSelectProvider = vi.fn();
    const onToggleEnabled = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    mountedRoots.push(root);

    await act(async () => root.render(
      <ConfigProviderRegistryPanel
        {...panelProps([], {
          rows: [anthroDirect, anthroRelay, xiaomiDirect, xiaomiRelay],
          selectedProviderId: "xiaomi_relay",
          onSelectProvider,
          onToggleEnabled,
        })}
      />,
    ));

    const list = container.querySelector<HTMLElement>('[data-vui="entity-list"]')!;
    const items = Array.from(list.querySelectorAll<HTMLElement>('[data-vui="entity-list-item"]'));
    const itemFor = (providerId: string) => items.find((item) => item.textContent?.includes(providerId))!;
    const selectedButton = itemFor("xiaomi_relay").querySelector<HTMLButtonElement>("button[aria-pressed]")!;
    expect(selectedButton.tagName).toBe("BUTTON");
    expect(selectedButton.getAttribute("aria-pressed")).toBe("true");
    expect(itemFor("anthropic_direct").textContent).toContain("anthropic_direct");
    expect(itemFor("anthropic_relay").textContent).toContain("anthropic_relay");
    expect(itemFor("xiaomi_direct").textContent).toContain("xiaomi_direct");
    expect(itemFor("xiaomi_relay").textContent).toContain("xiaomi_relay");

    await act(async () => itemFor("anthropic_relay").querySelector<HTMLButtonElement>("button[aria-pressed]")!.click());
    expect(onSelectProvider).toHaveBeenCalledWith("anthropic_relay");

    const relaySwitch = itemFor("anthropic_relay").querySelector<HTMLElement>('[role="switch"]')!;
    expect(relaySwitch.getAttribute("aria-label")).toContain("anthropic_relay");
    await act(async () => relaySwitch.click());
    expect(onToggleEnabled).toHaveBeenCalledWith("anthropic_relay", false);
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

  it("shows disabled providers directly with an off dot and their saved switch state", async () => {
    const off = { ...provider([]), providerId: "relay_off", label: "Off Relay", enabled: false };
    const ok = { ...provider([]), providerId: "relay_ok", label: "Ok Relay", enabled: true };
    const { container } = await mountWorkspace(panelProps([], { rows: [off, ok], selectedProviderId: "relay_ok", onToggleEnabled: () => undefined }));
    const markup = container.innerHTML;
    expect(markup).toContain('data-provider-dot="off"');
    expect(markup).toContain('data-provider-enabled="false"');
    expect(markup).toContain('data-provider-switch="true"');
    // Off tooltip comes from the shared providerDotOff copy.
    expect(markup).toContain("已停用");
    expect(container.querySelector<HTMLInputElement>('[data-provider-enabled="false"] [role="switch"]')!.checked).toBe(false);
    const offIndex = markup.indexOf("Off Relay");
    const okIndex = markup.indexOf("Ok Relay");
    expect(okIndex).toBeGreaterThan(-1);
    expect(offIndex).toBeGreaterThan(okIndex);
  });

  it("keeps the provider rail to search and service rows with no action dock", async () => {
    const onAddConnection = vi.fn();
    const onAddSubscriptionModels = vi.fn();
    const { container } = await mountWorkspace(panelProps([], { onAddConnection, onAddSubscriptionModels }));
    const rail = container.querySelector('[data-vui="split-sidebar"]')!;
    expect(rail.querySelector('input[aria-label="搜索服务商"]')).not.toBeNull();
    expect(rail.querySelector('[data-vui="entity-list"]')).not.toBeNull();
    expect(rail.querySelector('[data-provider-action]')).toBeNull();
    expect(rail.textContent).not.toContain("未启用的服务");
    expect(rail.textContent).not.toContain("ChatGPT");
    expect(container.querySelector('[data-provider-action="add-provider"]')).toBeNull();
    expect(onAddConnection).not.toHaveBeenCalled();
    await activateTab(container, "连接");
    const subscription = container.querySelector<HTMLButtonElement>('[data-provider-action="subscription"]')!;
    expect(subscription.closest<HTMLElement>('[hidden]')).toBeNull();
    expect(subscription.closest('[data-vui-region="config-provider-connection"]')).not.toBeNull();
    expect(panelSource).not.toContain("批量停用");
  });

  it("opens subscription setup from the empty provider workspace without making API calls", async () => {
    const onAddConnection = vi.fn();
    const onAddSubscriptionModels = vi.fn();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { container } = await mountWorkspace(panelProps([], { rows: [], selectedProviderId: "", onAddConnection, onAddSubscriptionModels }));
    expect(container.querySelector('[data-testid="chatgpt-subscription-panel"]')).toBeNull();
    const subscription = container.querySelector<HTMLButtonElement>('[data-provider-action="subscription"]')!;
    expect(subscription.closest("[hidden]")).toBeNull();
    expect(subscription.closest('[data-vui="split-main"]')).not.toBeNull();
    await act(async () => subscription.click());
    const setup = container.querySelector('[data-testid="chatgpt-subscription-panel"]')!;
    expect(setup.textContent).toBe("Mock ChatGPT subscription setup");
    expect(setup.closest("[hidden]")).toBeNull();
    expect(onAddConnection).not.toHaveBeenCalled();
    expect(onAddSubscriptionModels).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("runs service detection from the connection tab and shows busy feedback", async () => {
    const onDiscover = vi.fn();
    const { container } = await mountWorkspace(panelProps([], { onDiscover }));
    await activateTab(container, "连接");
    const detect = container.querySelector<HTMLButtonElement>('[data-provider-action="detect"]');
    expect(detect!.closest("[hidden]")).toBeNull();
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
