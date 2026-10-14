/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { SessionLlmModelOption } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import {
  ConversationTurnModelControl,
  validateModelContextWindow,
} from "./ConversationTurnModelControl";
import controlSource from "./ConversationTurnModelControl.tsx?raw";
import styles from "./ConversationTurnModelControl.styles";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const luna: SessionLlmModelOption = {
  modelId: "ai-pixel/gpt-5.6-luna",
  modelRef: "ai-pixel/gpt-5.6-luna",
  label: "Luna 5.6",
  model: "gpt-5.6-luna",
  providerId: "ai-pixel",
  providerLabel: "Ai-Pixel",
  providerKind: "relay",
  apiKeyConfigured: true,
  missingApiKey: false,
  supportsReasoningEffort: true,
  reasoningEffortValues: ["low", "high"],
  reasoningEffortOptions: [
    { value: "low", label: "低", description: "快速响应" },
    { value: "high", label: "高", description: "复杂任务" },
  ],
  defaultReasoningEffort: "low",
  isDefault: true,
};

function renderControl(
  overrides: Partial<React.ComponentProps<typeof ConversationTurnModelControl>> = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationTurnModelControl
        sessionId="session-a"
        agentId="agent-a"
        configRevision={4}
        model={luna}
        contextWindow={64_000}
        maxContextWindow={128_000}
        currentReasoningEffort="low"
        onSave={() => undefined}
        {...overrides}
      />
    </QueryClientProvider>,
  );
}

async function withInteractiveControl(
  check: (render: (props?: Partial<React.ComponentProps<typeof ConversationTurnModelControl>>) => Promise<void>, onSave: ReturnType<typeof vi.fn>) => Promise<void>,
) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const onSave = vi.fn();
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
  const render = async (props: Partial<React.ComponentProps<typeof ConversationTurnModelControl>> = {}) => {
    await act(async () => root.render(
      <QueryClientProvider client={queryClient}>
        <ConversationTurnModelControl sessionId="session-a" agentId="agent-a" configRevision={4} model={luna} contextWindow={64_000} maxContextWindow={128_000} currentReasoningEffort="high" onSave={onSave} {...props} />
      </QueryClientProvider>,
    ));
  };
  try {
    await render();
    await act(async () => host.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]')?.click());
    await vi.waitFor(() => expect(document.body.querySelector('[data-testid="conversation-model-parameters-panel"]')).not.toBeNull());
    await check(render, onSave);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    queryClient.clear();
  }
}

async function editNativeValue(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("ConversationTurnModelControl", () => {
  it("keeps the current provider's raw effort names and supported stops", async () => {
    await withInteractiveControl(async (render) => {
      await render({
        model: { ...luna, reasoningEffortValues: ["low", "xhigh", "max"], reasoningEffortOptions: [{ value: "max", label: "最大" }], defaultReasoningEffort: "low" },
        currentReasoningEffort: "max",
      });
      const slider = document.body.querySelector<HTMLInputElement>('input[aria-label="思考强度"]')!;
      expect(slider.max).toBe("2");
      expect(slider.getAttribute("aria-valuetext")).toBe("max");
      expect(document.body.querySelector('output')?.textContent).toBe("max");
      await editNativeValue(slider, "1");
      expect(slider.getAttribute("aria-valuetext")).toBe("xhigh");
      expect(document.body.querySelector('output')?.textContent).toBe("xhigh");
    });
  });

  it("shows the Agent model and opens parameters without a model chooser", () => {
    const html = renderControl();
    expect(html).toContain("Luna 5.6");
    expect(html).toContain('aria-label="Agent 模型: Luna 5.6"');
    expect(html).toContain('aria-haspopup="dialog"');
    expect(html).not.toContain("listbox");
    expect(html).not.toContain("选择模型");
    expect(html).not.toContain("data-override");
    expect(controlSource).toContain("contextWindow");
    expect(controlSource).toContain("reasoningEffort");
    expect(controlSource).not.toContain("modelChoices");
    expect(controlSource).not.toContain("onSelectionChange={onModel");
  });

  it("does not keep the previous Agent model during loading or error", () => {
    expect(renderControl({ loading: true })).toContain("读取模型…");
    expect(renderControl({ loading: true })).not.toContain("Luna 5.6");
    expect(renderControl({ error: true })).toContain("模型读取失败");
    expect(renderControl({ error: true })).not.toContain("Luna 5.6");
    expect(renderControl({ model: null })).toContain("未绑定模型");
  });

  it("requires an Agent revision and a valid model maximum before editing", () => {
    expect(renderControl({ configRevision: undefined })).toContain("disabled");
    expect(renderControl({ maxContextWindow: undefined })).toContain("disabled");
  });

  it("validates a positive integer against the model's hard context limit", () => {
    expect(validateModelContextWindow("128000", 128_000, "zh")).toEqual({
      value: 128_000,
      valid: true,
      error: "",
    });
    expect(validateModelContextWindow("128001", 128_000, "zh").error).toBe("不能超过 128,000");
    expect(validateModelContextWindow("1.5", 128_000, "zh").error).toBe("请输入正整数");
    expect(validateModelContextWindow("", 128_000, "en").error).toBe("Enter a positive integer");
  });

  it.each([
    ["low", false],
    ["", false],
    ["high", true],
  ] as const)("preserves reasoning %s or explicitly restores the model default (%s)", async (reasoningEffort, clearEffort) => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const onSave = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    queryClient.setQueryData(queryKeys.configPublic(), { language: "zh" });
    try {
      await act(async () => {
        root.render(
          <QueryClientProvider client={queryClient}>
            <ConversationTurnModelControl
              sessionId="session-a"
              agentId="agent-a"
              configRevision={4}
              model={luna}
              contextWindow={64_000}
              maxContextWindow={128_000}
              currentReasoningEffort={reasoningEffort}
              onSave={onSave}
            />
          </QueryClientProvider>,
        );
      });
      const trigger = host.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]');
      expect(trigger).not.toBeNull();
      await act(async () => trigger?.dispatchEvent(new MouseEvent("click", { bubbles: true })));

      await vi.waitFor(() => {
        const found = document.body.querySelector<HTMLElement>('[data-testid="conversation-model-parameters-panel"]');
        expect(found).not.toBeNull();
      });
      const panel = () => document.body.querySelector<HTMLElement>('[data-testid="conversation-model-parameters-panel"]');
      const numberTrigger = document.body.querySelector<HTMLButtonElement>('button[aria-label="精确设置上下文，当前 64000 tokens"]');
      await act(async () => numberTrigger?.click());
      const contextInput = () => document.body.querySelector<HTMLInputElement>('input[aria-label="精确上下文大小"]');
      const saveButton = () => document.body.querySelector<HTMLButtonElement>('button[aria-label="保存模型参数"]');
      const valueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
      await act(async () => {
        valueSetter?.call(contextInput(), "128001");
        contextInput()?.dispatchEvent(new Event("input", { bubbles: true }));
        contextInput()?.dispatchEvent(new Event("change", { bubbles: true }));
      });
      expect(panel()?.textContent).toContain("不能超过 128,000");
      expect(saveButton()?.disabled).toBe(true);

      await act(async () => {
        valueSetter?.call(contextInput(), "32000");
        contextInput()?.dispatchEvent(new Event("input", { bubbles: true }));
        contextInput()?.dispatchEvent(new Event("change", { bubbles: true }));
      });
      expect(saveButton()?.disabled).toBe(false);
      if (clearEffort) {
        const reset = document.body.querySelector<HTMLButtonElement>('button[aria-label="恢复默认思考强度"]');
        expect(reset).not.toBeNull();
        await act(async () => reset?.click());
      }
      await act(async () => saveButton()?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
      expect(onSave).toHaveBeenCalledWith({ contextWindow: 32_000, reasoningEffort: clearEffort ? "" : reasoningEffort });
      expect(document.body.textContent).not.toContain("选择模型");
    } finally {
      await act(async () => root.unmount());
      host.remove();
      queryClient.clear();
    }
  });

  it("keeps the toolbar trigger compact and the popover within the viewport", () => {
    expect(styles.label).toContain("truncate");
    expect(styles.label).toContain("max-w-32");
    expect(styles.trigger).toContain("h-7");
    expect(styles.popover).toContain("w-[min(272px,calc(100vw-16px))]");
    expect(styles.saveButton).toContain("!h-7");
  });

  it("preserves failed drafts across revisions and accepts the resolved default after successful saving", async () => {
    await withInteractiveControl(async (render, onSave) => {
      const reset = () => document.body.querySelector<HTMLButtonElement>('button[aria-label="恢复默认思考强度"]')!;
      const save = () => document.body.querySelector<HTMLButtonElement>('button[aria-label="保存模型参数"]')!;
      await act(async () => reset().click());
      await act(async () => save().click());
      expect(onSave).toHaveBeenCalledWith({ contextWindow: 64_000, reasoningEffort: "" });
      await render({ pending: true });
      expect(save().disabled).toBe(true);
      expect(document.body.querySelector<HTMLInputElement>('input[aria-label="思考强度"]')?.disabled).toBe(true);
      await render({ configRevision: 5, pending: false, errorMessage: "配置已变更，请重试", contextWindow: 32_000 });
      expect(document.body.querySelector('output')?.textContent).toBe("默认");
      expect(document.body.querySelector('button[aria-label="精确设置上下文，当前 64000 tokens"]')).not.toBeNull();
      expect(save().disabled).toBe(false);
      await render({ pending: true, configRevision: 5, contextWindow: 32_000 });
      await render({ pending: false, configRevision: 6, contextWindow: 65_536, currentReasoningEffort: "low" });
      expect(save().disabled).toBe(true);
      expect(document.body.querySelector('output')?.textContent).toBe("low");
      const context = document.body.querySelector<HTMLInputElement>('input[aria-label="上下文大小"]')!;
      expect(context.getAttribute("aria-valuetext")).toBe("65,536 tokens");
      expect(context.value).toBe("4");
    });
  });

  it("keeps exact custom context values, cancels numeric edits and resets drafts when Agent identity changes", async () => {
    await withInteractiveControl(async (render, onSave) => {
      const numberButton = () => document.body.querySelector<HTMLButtonElement>('button[aria-label^="精确设置上下文"]')!;
      const numberInput = () => document.body.querySelector<HTMLInputElement>('input[aria-label="精确上下文大小"]')!;
      await act(async () => numberButton().click());
      await editNativeValue(numberInput(), "65536");
      await act(async () => numberInput().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
      expect(numberButton().textContent).toBe("65,536");
      expect(document.body.querySelector<HTMLInputElement>('input[aria-label="上下文大小"]')?.value).toBe("4");
      await act(async () => numberButton().click());
      await editNativeValue(numberInput(), "32000");
      await act(async () => numberInput().dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })));
      expect(numberButton().textContent).toBe("65,536");
      await act(async () => document.body.querySelector<HTMLButtonElement>('button[aria-label="保存模型参数"]')?.click());
      expect(onSave).toHaveBeenCalledWith({ contextWindow: 65_536, reasoningEffort: "high" });
      await render({ agentId: "agent-b", contextWindow: 16_000, currentReasoningEffort: "low" });
      expect(document.body.querySelector('[data-testid="conversation-model-parameters-panel"]')).toBeNull();
    });
  });
});
