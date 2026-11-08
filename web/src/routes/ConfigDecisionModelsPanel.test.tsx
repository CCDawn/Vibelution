// @vitest-environment happy-dom
import React, { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VuiProvider } from "../components/vui";
import { testDecisionModel } from "../api/config";
import { ConfigDecisionModelsPanel, readDecisionModelMap } from "./ConfigDecisionModelsPanel";

vi.mock("../api/config", () => ({ testDecisionModel: vi.fn() }));

const presets = [
  {
    presetId: "d1-3b",
    label: "d1-3B",
    modelId: "LiquidAI/d1-3B",
    baseUrl: "http://127.0.0.1:8088/v1/systemone",
    noteZh: "本机可跑",
    noteEn: "fits this machine",
  },
  {
    presetId: "openjev",
    label: "OpenJev",
    modelId: "ggml-org/OpenJev-GGUF",
    baseUrl: "http://127.0.0.1:8093/v1/systemone",
    noteZh: "27B，只允许非商用",
    noteEn: "27B, non-commercial only",
  },
];

type PanelProps = ComponentProps<typeof ConfigDecisionModelsPanel>;
const savedModels = readDecisionModelMap({
  "d1-3b": {
    label: "d1-3B",
    model_id: "LiquidAI/d1-3B",
    base_url: "http://127.0.0.1:8088/v1/systemone",
    min_probability: 0.8,
    enabled: true,
    note: "本机可跑",
  },
});

let roots: Root[] = [];
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.mocked(testDecisionModel).mockReset();
});
afterEach(async () => {
  for (const root of roots) await act(async () => root.unmount());
  roots = [];
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

async function mount(overrides: Partial<PanelProps> = {}) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  let props: PanelProps = {
    models: savedModels,
    handoffModelId: "d1-3b",
    savedModels,
    savedHandoffModelId: "d1-3b",
    presets,
    disabled: false,
    lang: "zh",
    onCommit: vi.fn(),
    onToggleEnabled: vi.fn(async () => true),
    onSelectHandoff: vi.fn(async () => true),
    ...overrides,
  };
  let generation = 0;
  async function rerender(next: Partial<PanelProps> = {}, discard = false) {
    props = { ...props, ...next };
    if (discard) generation += 1;
    await act(async () => root.render(<VuiProvider><ConfigDecisionModelsPanel key={generation} {...props} /></VuiProvider>));
  }
  await rerender();
  return { container, rerender };
}

function field(container: HTMLElement, label: string): HTMLInputElement {
  const row = [...container.querySelectorAll("label")]
    .find((item) => item.firstElementChild?.textContent === label);
  const input = row?.querySelector("input");
  if (!input) throw new Error(`Missing input: ${label}`);
  return input;
}

async function edit(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function openEditor(container: HTMLElement, id = "d1-3b") {
  const row = container.querySelector(`[data-decision-model-id="${id}"]`)!;
  const button = row.querySelector<HTMLButtonElement>("button")!;
  await act(async () => button.click());
  const editor = container.querySelector<HTMLElement>('[data-testid="decision-model-editor"]');
  if (!editor) throw new Error("Missing decision model editor");
  return editor;
}

async function closeEditor() {
  const button = document.querySelector<HTMLButtonElement>('button[aria-label="返回用途"]')!;
  await act(async () => button.click());
}

async function addEntry(container: HTMLElement, label = "自定义") {
  const button = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((item) => item.textContent === "添加")!;
  await act(async () => button.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
  const item = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')]
    .find((item) => item.textContent === label)!;
  await act(async () => item.click());
}

async function openHandoff(container: HTMLElement) {
  const select = container.querySelector<HTMLButtonElement>('[role="combobox"]')!;
  await act(async () => select.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })));
  return [...document.querySelectorAll<HTMLElement>('[role="option"]')];
}

describe("ConfigDecisionModelsPanel", () => {
  it("renders the decision class without a chat slot", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <ConfigDecisionModelsPanel
          models={readDecisionModelMap({
            "d1-3b": {
              label: "d1-3B",
              model_id: "LiquidAI/d1-3B",
              base_url: "http://127.0.0.1:8088/v1/systemone",
              min_probability: 0.8,
              enabled: true,
              note: "本机可跑",
            },
          })}
          handoffModelId=""
          presets={presets}
          disabled={false}
          lang="zh"
          onCommit={() => undefined}
        />
      </VuiProvider>,
    );
    expect(markup).toContain("决策模型");
    expect(markup).toContain("添加");
    expect(markup).toContain("不绑定");
    expect(markup).not.toContain("检查连通");
    expect(markup).not.toContain("不进入对话槽");
    expect(markup).not.toContain("renderers/shadcn");
  });

  it("is mounted from the models section and stays on the VUI API", () => {
    const route = readFileSync(resolve(import.meta.dirname, "ConfigRoute.tsx"), "utf8");
    const panel = readFileSync(resolve(import.meta.dirname, "ConfigDecisionModelsPanel.tsx"), "utf8");
    expect(route).toContain("ConfigDecisionModelsPanel");
    expect(route).toContain("decision_models");
    expect(route).toContain("decision_handoff_model_id");
    expect(panel).not.toContain("renderers/shadcn");
    expect(panel).not.toContain("@heroui/react");
    expect(panel).not.toContain("VDialog");
  });

  it("preserves unknown saved fields when reading and editing an entry", async () => {
    const extension = { route: "custom", options: ["a", "b"] };
    const models = readDecisionModelMap({
      "d1-3b": { ...savedModels["d1-3b"], custom_option: extension },
    });
    expect(models["d1-3b"].custom_option).toEqual(extension);
    const onCommit = vi.fn();
    const { container } = await mount({ models, savedModels: models, onCommit });
    await edit(field(await openEditor(container), "名称"), "Renamed");
    await closeEditor();
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({
      "d1-3b": { ...models["d1-3b"], label: "Renamed", custom_option: extension },
    }, "d1-3b");
  });

  it("accepts refreshed extension fields before starting a new edit", async () => {
    const models = readDecisionModelMap({ "d1-3b": { ...savedModels["d1-3b"], custom_option: "old" } });
    const onCommit = vi.fn();
    const { container, rerender } = await mount({ models, savedModels: models, onCommit });
    const refreshed = { "d1-3b": { ...models["d1-3b"], custom_option: "new" } };
    await rerender({ models: refreshed, savedModels: refreshed });
    await edit(field(await openEditor(container), "名称"), "Renamed");
    await closeEditor();
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({
      "d1-3b": { ...refreshed["d1-3b"], label: "Renamed" },
    }, "d1-3b");
  });

  it("discards retained incomplete values only when the parent remounts after explicit discard", async () => {
    const onPendingChange = vi.fn();
    const { container, rerender } = await mount({ onPendingChange });
    const editor = await openEditor(container);
    await edit(field(editor, "模型名"), "");
    await closeEditor();
    expect(document.activeElement).toBe(container.querySelector('[data-decision-model-id="d1-3b"] button'));
    await rerender({ models: { ...savedModels } });
    expect(field(await openEditor(container), "模型名").value).toBe("");
    await rerender({}, true);
    expect(container.querySelector('[data-testid="decision-model-editor"]')).toBeNull();
    expect(field(await openEditor(container), "模型名").value).toBe(savedModels["d1-3b"].model_id);
    expect(onPendingChange.mock.calls).toEqual([[false], [true], [false]]);
  });

  it("saves only the requested enabled value and waits for saved props", async () => {
    const onCommit = vi.fn();
    const onToggleEnabled = vi.fn(async () => true);
    const { container } = await mount({ onCommit, onToggleEnabled });
    await openEditor(container);
    const checkbox = container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;

    await act(async () => checkbox.click());

    expect(onToggleEnabled).toHaveBeenCalledExactlyOnceWith("d1-3b", false);
    expect(onCommit).not.toHaveBeenCalled();
    expect(checkbox.checked).toBe(true);
  });

  it("keeps the saved switch and local text when an immediate save fails", async () => {
    const onCommit = vi.fn();
    const onToggleEnabled = vi.fn(async () => false);
    const { container } = await mount({ onCommit, onToggleEnabled });
    const input = field(await openEditor(container), "本地地址");
    await edit(input, "http://127.0.0.1:9000/v1/systemone");

    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());

    expect(onToggleEnabled).toHaveBeenCalledExactlyOnceWith("d1-3b", false);
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(true);
    expect(input.value).toBe("http://127.0.0.1:9000/v1/systemone");
    expect(onCommit).not.toHaveBeenCalled();
  });

  it("publishes text with the latest saved enabled and cleared handoff values", async () => {
    const onCommit = vi.fn();
    const { container, rerender } = await mount({ onCommit });
    const input = field(await openEditor(container), "名称");
    await edit(input, "Edited locally");
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await rerender({
      savedModels: { "d1-3b": { ...savedModels["d1-3b"], enabled: false } },
      savedHandoffModelId: "",
    });

    expect(input.value).toBe("Edited locally");
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
    await act(async () => input.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));

    expect(onCommit).toHaveBeenCalledExactlyOnceWith({
      "d1-3b": { ...savedModels["d1-3b"], label: "Edited locally", enabled: false },
    }, "");
  });

  it("saves handoff separately and preserves a text draft through failure and success", async () => {
    const onCommit = vi.fn();
    const onSelectHandoff = vi.fn(async () => false);
    const { container, rerender } = await mount({ onCommit, onSelectHandoff });
    const editor = await openEditor(container);
    const input = field(editor, "名称");
    await edit(input, "Local name");
    await edit(field(editor, "模型名"), "");
    await closeEditor();
    const options = await openHandoff(container);
    await act(async () => options.find((item) => item.textContent === "不绑定")!.click());

    expect(onSelectHandoff).toHaveBeenCalledExactlyOnceWith("");
    expect(onCommit).not.toHaveBeenCalled();
    expect(container.querySelector('[role="combobox"]')!.textContent).toContain("d1-3B");

    onSelectHandoff.mockResolvedValueOnce(true);
    const nextOptions = await openHandoff(container);
    await act(async () => nextOptions.find((item) => item.textContent === "不绑定")!.click());
    await rerender({ savedHandoffModelId: "" });
    const reopened = await openEditor(container);
    expect(field(reopened, "名称").value).toBe("Local name");
    expect(field(reopened, "模型名").value).toBe("");
    await edit(field(reopened, "模型名"), savedModels["d1-3b"].model_id);
    await closeEditor();

    expect(onCommit).toHaveBeenCalledExactlyOnceWith({
      "d1-3b": { ...savedModels["d1-3b"], label: "Local name" },
    }, "");
  });

  it("disables immediate controls for a new unsaved model and excludes it from handoff", async () => {
    const onToggleEnabled = vi.fn(async () => true);
    const { container } = await mount({ onToggleEnabled });
    await addEntry(container, "OpenJev");
    const checkbox = container.querySelector<HTMLInputElement>('input[type="checkbox"]')!;

    expect(checkbox.disabled).toBe(true);
    await act(async () => checkbox.click());
    expect(onToggleEnabled).not.toHaveBeenCalled();
    await closeEditor();
    const options = await openHandoff(container);
    expect(options.map((option) => option.textContent)).toEqual(["不绑定", "d1-3B"]);
  });

  it("retains draft-only enabled behavior when immediate callbacks are absent", async () => {
    const onCommit = vi.fn();
    const { container } = await mount({ onCommit, onToggleEnabled: undefined, onSelectHandoff: undefined });
    await openEditor(container);

    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());

    expect(onCommit).toHaveBeenCalledExactlyOnceWith({
      "d1-3b": { ...savedModels["d1-3b"], enabled: false },
    }, "");
  });

  it("keeps 24 models compact and mounts fields only for the selected entity", async () => {
    const models = Object.fromEntries(Array.from({ length: 24 }, (_, index) => [
      `model-${index}`,
      { ...savedModels["d1-3b"], label: `Decision ${index}`, model_id: `local/model-${index}` },
    ]));
    const { container } = await mount({ models, savedModels: models, handoffModelId: "model-0", savedHandoffModelId: "model-0" });

    expect(container.querySelectorAll("li[data-decision-model-id]")).toHaveLength(24);
    expect(container.querySelector('input[type="text"]')).toBeNull();
    expect(container.textContent).toContain("local/model-23");
    expect(container.querySelector('[data-decision-model-id="model-0"]')!.textContent).toContain("用于交接");
    expect([...container.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === "添加")!.disabled).toBe(true);
    const editor = await openEditor(container, "model-23");
    expect(field(editor, "名称").value).toBe("Decision 23");
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(0);
    expect(container.querySelector("li[data-decision-model-id]")).toBeNull();
    expect(container.querySelector('button[aria-label="返回用途"]')).not.toBeNull();
    expect(editor.querySelectorAll('input[type="text"]')).toHaveLength(3);
  });

  it("flushes valid edits to the page draft when closing without a blur event", async () => {
    const onCommit = vi.fn();
    const { container } = await mount({ onCommit });
    const editor = await openEditor(container);
    await edit(field(editor, "名称"), "Edited decision");
    expect(onCommit).not.toHaveBeenCalled();
    await closeEditor();

    expect(onCommit).toHaveBeenCalledExactlyOnceWith({
      "d1-3b": { ...savedModels["d1-3b"], label: "Edited decision" },
    }, "d1-3b");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(field(await openEditor(container), "名称").value).toBe("Edited decision");
  });

  it("reports incomplete additions until the parent accepts them and does not clear them on close", async () => {
    const onCommit = vi.fn();
    const onPendingChange = vi.fn();
    const { container, rerender } = await mount({ models: {}, savedModels: {}, handoffModelId: "", savedHandoffModelId: "", onCommit, onPendingChange });
    expect(onPendingChange.mock.calls).toEqual([[false]]);
    await addEntry(container);
    expect(onPendingChange.mock.calls).toEqual([[false], [true]]);
    expect(onCommit).not.toHaveBeenCalled();
    await closeEditor();
    expect(container.querySelector('[data-decision-model-id="custom-1"]')).not.toBeNull();
    expect(onPendingChange.mock.calls).toEqual([[false], [true]]);
    const editor = await openEditor(container, "custom-1");
    expect(field(editor, "模型名").value).toBe("");
    await edit(field(editor, "模型名"), "local/custom");
    await closeEditor();
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onPendingChange.mock.calls).toEqual([[false], [true]]);
    const [models, handoffModelId] = onCommit.mock.calls[0];
    await rerender({ models, handoffModelId });
    expect(onPendingChange.mock.calls).toEqual([[false], [true], [false]]);
  });

  it("reports unpublished valid and invalid text once per pending transition", async () => {
    const onCommit = vi.fn();
    const onPendingChange = vi.fn();
    const { container, rerender } = await mount({ onCommit, onPendingChange });
    const editor = await openEditor(container);
    await edit(field(editor, "名称"), "Local name");
    expect(onPendingChange.mock.calls).toEqual([[false], [true]]);
    expect(onCommit).not.toHaveBeenCalled();
    await edit(field(editor, "本地地址"), "http://");
    await closeEditor();
    await rerender({ onPendingChange: (pending) => onPendingChange(pending), models: { ...savedModels } });
    await rerender({ onPendingChange: (pending) => onPendingChange(pending), models: { ...savedModels } });
    expect(onPendingChange.mock.calls).toEqual([[false], [true]]);
    expect(onCommit).not.toHaveBeenCalled();
    const reopened = await openEditor(container);
    expect(field(reopened, "名称").value).toBe("Local name");
    expect(field(reopened, "本地地址").value).toBe("http://");
    await edit(field(reopened, "本地地址"), savedModels["d1-3b"].base_url);
    await closeEditor();
    expect(onCommit).toHaveBeenCalledTimes(1);
    const [models, handoffModelId] = onCommit.mock.calls[0];
    await rerender({ models, handoffModelId });
    expect(onPendingChange.mock.calls).toEqual([[false], [true], [false]]);
  });

  it("clears local pending when text is restored or an incomplete new entry is removed", async () => {
    const onPendingChange = vi.fn();
    const { container } = await mount({ onPendingChange });
    const editor = await openEditor(container);
    await edit(field(editor, "名称"), "Changed");
    await edit(field(editor, "名称"), savedModels["d1-3b"].label);
    expect(onPendingChange.mock.calls).toEqual([[false], [true], [false]]);
    await closeEditor();
    await addEntry(container);
    const remove = [...container.querySelectorAll<HTMLButtonElement>('[data-testid="decision-model-editor"] button')].find((item) => item.textContent === "删除")!;
    await act(async () => remove.click());
    expect(onPendingChange.mock.calls).toEqual([[false], [true], [false], [true], [false]]);
  });

  it("preserves pending text through immediate enabled and handoff saves", async () => {
    const onCommit = vi.fn();
    const onPendingChange = vi.fn();
    const onToggleEnabled = vi.fn(async () => true);
    const { container, rerender } = await mount({ onCommit, onPendingChange, onToggleEnabled });
    const input = field(await openEditor(container), "名称");
    await edit(input, "Still local");
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    const saved = { "d1-3b": { ...savedModels["d1-3b"], enabled: false } };
    await rerender({ models: saved, handoffModelId: "", savedModels: saved, savedHandoffModelId: "" });
    expect(onToggleEnabled).toHaveBeenCalledExactlyOnceWith("d1-3b", false);
    expect(input.value).toBe("Still local");
    expect(onPendingChange.mock.calls).toEqual([[false], [true]]);
    expect(onCommit).not.toHaveBeenCalled();
    await closeEditor();
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({ "d1-3b": { ...saved["d1-3b"], label: "Still local" } }, "");
    const [models, handoffModelId] = onCommit.mock.calls[0];
    await rerender({ models, handoffModelId });
    expect(onPendingChange.mock.calls).toEqual([[false], [true], [false]]);
  });

  it("does not report immediate-only state changes as unpublished local edits", async () => {
    const onPendingChange = vi.fn();
    const { rerender } = await mount({ onPendingChange });
    const saved = { "d1-3b": { ...savedModels["d1-3b"], enabled: false } };
    await rerender({ models: saved, handoffModelId: "", savedModels: saved, savedHandoffModelId: "" });
    await rerender({ models: { ...saved }, onPendingChange: (pending) => onPendingChange(pending) });
    expect(onPendingChange.mock.calls).toEqual([[false]]);
  });

  it("keeps incomplete values per entity through closing, switching and parent updates", async () => {
    const models = { ...savedModels, second: { ...savedModels["d1-3b"], label: "Second", model_id: "local/second" } };
    const onCommit = vi.fn();
    const { container, rerender } = await mount({ models, savedModels: models, onCommit });
    const first = await openEditor(container);
    await edit(field(first, "名称"), "First draft");
    await edit(field(first, "本地地址"), "http://");
    await closeEditor();
    const second = await openEditor(container, "second");
    await edit(field(second, "名称"), "Second draft");
    await edit(field(second, "最低概率"), "0.42");
    await closeEditor();
    await rerender({ models: { ...models } });
    expect(onCommit).not.toHaveBeenCalled();

    const firstAgain = await openEditor(container);
    expect(field(firstAgain, "名称").value).toBe("First draft");
    expect(field(firstAgain, "本地地址").value).toBe("http://");
    await edit(field(firstAgain, "本地地址"), savedModels["d1-3b"].base_url);
    await closeEditor();
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({
      "d1-3b": { ...models["d1-3b"], label: "First draft" },
      second: { ...models.second, label: "Second draft", min_probability: 0.42 },
    }, "d1-3b");
    const secondAgain = await openEditor(container, "second");
    expect(field(secondAgain, "名称").value).toBe("Second draft");
    expect(field(secondAgain, "最低概率").value).toBe("0.42");
  });

  it("opens a new custom entry and commits it only after its required fields are ready", async () => {
    const onCommit = vi.fn();
    const { container } = await mount({ onCommit });
    await addEntry(container);
    const editor = container.querySelector<HTMLElement>('[data-testid="decision-model-editor"]')!;
    expect(field(editor, "名称").value).toBe("自定义决策模型");
    expect(onCommit).not.toHaveBeenCalled();
    await edit(field(editor, "模型名"), "local/custom");
    await closeEditor();

    expect(onCommit).toHaveBeenCalledExactlyOnceWith({
      ...savedModels,
      "custom-1": {
        label: "自定义决策模型", model_id: "local/custom", base_url: "http://127.0.0.1:8088/v1/systemone",
        min_probability: 0.8, enabled: true, note: "",
      },
    }, "d1-3b");
  });

  it.each([
    "https://public.example/v1/systemone",
    "http://user:password@127.0.0.1:8088/v1/systemone",
    "http://127.0.0.1:8088/v1/systemone?token=secret",
    "http://127.0.0.1:8088/v1/systemone#fragment",
    "http://127.0.0.1:8088/other",
  ])("preserves but does not commit an unsafe endpoint %s", async (address) => {
    const onCommit = vi.fn();
    const { container } = await mount({ onCommit });
    await edit(field(await openEditor(container), "本地地址"), address);
    await closeEditor();
    expect(onCommit).not.toHaveBeenCalled();
    expect(container.textContent).toContain("待补全");
    expect(field(await openEditor(container), "本地地址").value).toBe(address);
  });

  it("probes the selected current model and shows its choice and probability", async () => {
    vi.mocked(testDecisionModel).mockResolvedValue({ ok: true, choice: "handoff", probability: 0.91 });
    const { container } = await mount();
    const editor = await openEditor(container);
    await edit(field(editor, "模型名"), "local/draft-model");
    await edit(field(editor, "本地地址"), "http://127.0.0.1:9000/v1/systemone");
    const check = [...editor.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === "检查连通")!;
    await act(async () => check.click());

    expect(testDecisionModel).toHaveBeenCalledExactlyOnceWith({ baseUrl: "http://127.0.0.1:9000/v1/systemone", modelId: "local/draft-model" });
    expect(editor.textContent).toContain("模型响应: handoff 0.91");
    await closeEditor();
    expect(container.textContent).toContain("模型响应: handoff 0.91");
    const reopened = await openEditor(container);
    await edit(field(reopened, "模型名"), "local/another-model");
    expect(reopened.textContent).not.toContain("模型响应: handoff 0.91");
    await closeEditor();
    expect(container.textContent).not.toContain("模型响应: handoff 0.91");
  });

  it("reports failed probes on the summary row", async () => {
    vi.mocked(testDecisionModel).mockRejectedValue(new Error("unavailable"));
    const { container } = await mount();
    const editor = await openEditor(container);
    const check = [...editor.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === "检查连通")!;
    await act(async () => check.click());
    await closeEditor();
    expect(container.textContent).toContain("连通检查失败");
  });

  it("removes a bound entry through the page draft without calling immediate saves", async () => {
    const onCommit = vi.fn();
    const onToggleEnabled = vi.fn(async () => true);
    const onSelectHandoff = vi.fn(async () => true);
    const { container } = await mount({ onCommit, onToggleEnabled, onSelectHandoff });
    const editor = await openEditor(container);
    const remove = [...editor.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === "删除")!;
    await act(async () => remove.click());
    expect(onCommit).toHaveBeenCalledExactlyOnceWith({}, "");
    expect(onToggleEnabled).not.toHaveBeenCalled();
    expect(onSelectHandoff).not.toHaveBeenCalled();
    expect(container.querySelector('[data-decision-model-id="d1-3b"]')).toBeNull();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });
});
