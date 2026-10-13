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

describe("ConversationTurnModelControl", () => {
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

  it("saves only a valid context value and the current model's reasoning level", async () => {
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
              currentReasoningEffort="low"
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
      const contextInput = () => document.body.querySelector<HTMLInputElement>('input[aria-label="上下文上限"]');
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
      await act(async () => saveButton()?.dispatchEvent(new MouseEvent("click", { bubbles: true })));
      expect(onSave).toHaveBeenCalledWith({ contextWindow: 32_000, reasoningEffort: "low" });
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
});
