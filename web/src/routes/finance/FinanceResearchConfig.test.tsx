// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionLlmModelOption, SessionLlmOptions } from "../../api/types";
import { FinanceResearchConfig, financialResearchModelGateIssue } from "./FinanceResearchConfig";
import { localResearchDate } from "./stockResearchModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function modelOption(modelId: string, contextWindow: number): SessionLlmModelOption & { contextWindow: number; runtimeSelectable: boolean; providerHealthy: boolean } {
  return {
    modelId,
    modelRef: modelId,
    label: modelId,
    model: modelId,
    providerId: "provider",
    providerLabel: "Provider",
    providerKind: "openai",
    apiKeyConfigured: true,
    missingApiKey: false,
    supportsReasoningEffort: false,
    reasoningEffortValues: [],
    reasoningEffortOptions: [],
    defaultReasoningEffort: "",
    isDefault: modelId === "provider/default",
    contextWindow,
    runtimeSelectable: true,
    providerHealthy: true,
  };
}

function options(defaultModel: SessionLlmModelOption, alternate: SessionLlmModelOption): SessionLlmOptions {
  return {
    sessionId: "research",
    currentModelId: defaultModel.modelRef,
    currentReasoningEffort: "",
    model: defaultModel,
    choices: [defaultModel, alternate],
  };
}

describe("finance research model gate", () => {
  it("blocks research when Native cannot confirm the bound default model context", async () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const onStart = vi.fn();
    const sessionOptions = options(modelOption("provider/default", 0), modelOption("provider/alternate", 1_000_000));
    try {
      await act(async () => root.render(
        <FinanceResearchConfig
          value={{ period: "2025FY", date: localResearchDate(), scope: "comprehensive", depth: "standard" }}
          onChange={vi.fn()}
          onStart={onStart}
          disabled={false}
          pending={false}
          zh
          sessionId="research"
          sessionLlmOptions={sessionOptions}
          onTurnModelSelectionChange={vi.fn()}
        />,
      ));

      const status = host.querySelector('[data-testid="finance-research-model-status"]');
      const start = [...host.querySelectorAll("button")].find((button) => button.textContent?.includes("开始研究"));
      expect(status?.textContent).toContain("context_window");
      expect(status?.textContent).toContain("本轮模型选择不能绕过");
      expect(start).toBeDefined();
      expect(start?.disabled).toBe(true);
      expect(onStart).not.toHaveBeenCalled();
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  });

  it("rejects stale options and an unavailable pinned turn model", () => {
    const sessionOptions = options(modelOption("provider/default", 1_000_000), modelOption("provider/alternate", 0));
    expect(financialResearchModelGateIssue({ sessionId: "other", options: sessionOptions })).toBe("options_loading");
    expect(financialResearchModelGateIssue({
      sessionId: "research",
      options: sessionOptions,
      selection: { modelId: "provider/alternate" },
    })).toBe("turn_model_unavailable");
  });

  it("shows the lowest supported effort for quick research instead of the model default", async () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const ready = { ...modelOption("provider/default", 1_000_000), supportsReasoningEffort: true,
      reasoningEffortValues: ["low", "medium", "high"], defaultReasoningEffort: "medium" };
    try {
      await act(async () => root.render(<FinanceResearchConfig
        value={{ period: "", date: localResearchDate(), scope: "financial", depth: "brief" }}
        onChange={vi.fn()} onStart={vi.fn()} disabled={false} pending={false} zh
        sessionId="research" sessionLlmOptions={options(ready, { ...ready, modelId: "provider/alternate", modelRef: "provider/alternate" })}
        onTurnModelSelectionChange={vi.fn()}
      />));
      expect(host.textContent).toContain("本轮推理：低");
      expect(host.textContent).not.toContain("本轮推理：中");
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  });
});
