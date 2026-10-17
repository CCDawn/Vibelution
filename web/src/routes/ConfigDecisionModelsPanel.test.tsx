// @vitest-environment happy-dom
import React, { act, type ComponentProps } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { VuiProvider } from "../components/vui";
import { ConfigDecisionModelsPanel, readDecisionModelMap } from "./ConfigDecisionModelsPanel";

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
beforeEach(() => vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true));
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
  async function rerender(next: Partial<PanelProps> = {}) {
    props = { ...props, ...next };
    await act(async () => root.render(<VuiProvider><ConfigDecisionModelsPanel {...props} /></VuiProvider>));
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
    expect(markup).toContain("OpenJev");
    expect(markup).toContain("不绑定");
    expect(markup).toContain("检查连通");
    expect(markup).toContain("不进入对话槽");
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
  });

  it("saves only the requested enabled value and waits for saved props", async () => {
    const onCommit = vi.fn();
    const onToggleEnabled = vi.fn(async () => true);
    const { container } = await mount({ onCommit, onToggleEnabled });
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
    const input = field(container, "本地地址");
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
    const input = field(container, "名称");
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
    const input = field(container, "名称");
    await edit(input, "Local name");
    const options = await openHandoff(container);
    await act(async () => options.find((item) => item.textContent === "不绑定")!.click());

    expect(onSelectHandoff).toHaveBeenCalledExactlyOnceWith("");
    expect(onCommit).not.toHaveBeenCalled();
    expect(container.querySelector('[role="combobox"]')!.textContent).toContain("d1-3B");
    expect(input.value).toBe("Local name");

    onSelectHandoff.mockResolvedValueOnce(true);
    const nextOptions = await openHandoff(container);
    await act(async () => nextOptions.find((item) => item.textContent === "不绑定")!.click());
    await rerender({ savedHandoffModelId: "" });
    await act(async () => input.dispatchEvent(new FocusEvent("focusout", { bubbles: true })));

    expect(onCommit).toHaveBeenCalledExactlyOnceWith({
      "d1-3b": { ...savedModels["d1-3b"], label: "Local name" },
    }, "");
  });

  it("disables immediate controls for a new unsaved model and excludes it from handoff", async () => {
    const onToggleEnabled = vi.fn(async () => true);
    const { container } = await mount({ onToggleEnabled });
    const add = [...container.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "OpenJev")!;
    await act(async () => add.click());
    const checkboxes = container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]');

    expect(checkboxes).toHaveLength(2);
    expect(checkboxes[1].disabled).toBe(true);
    await act(async () => checkboxes[1].click());
    expect(onToggleEnabled).not.toHaveBeenCalled();
    const options = await openHandoff(container);
    expect(options.map((option) => option.textContent)).toEqual(["不绑定", "d1-3B"]);
  });

  it("retains draft-only enabled behavior when immediate callbacks are absent", async () => {
    const onCommit = vi.fn();
    const { container } = await mount({ onCommit, onToggleEnabled: undefined, onSelectHandoff: undefined });

    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());

    expect(onCommit).toHaveBeenCalledExactlyOnceWith({
      "d1-3b": { ...savedModels["d1-3b"], enabled: false },
    }, "");
  });
});
