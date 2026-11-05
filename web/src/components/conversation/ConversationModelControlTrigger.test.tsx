// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { SessionLlmModelOption } from "../../api/types";
import { LauncherAssistantModelControl } from "../../routes/desktopPet/LauncherAssistantModelControl";
import { ConversationTurnModelControl } from "./ConversationTurnModelControl";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
let container: HTMLDivElement;
let client: QueryClient;

afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  container?.remove();
  client?.clear();
});

const model: SessionLlmModelOption = {
  modelId: "provider/gpt-6", modelRef: "provider/gpt-6", label: "GPT-6", model: "GPT-6",
  providerId: "provider", providerLabel: "Provider", providerKind: "relay",
  apiKeyConfigured: true, missingApiKey: false, supportsReasoningEffort: true,
  reasoningEffortValues: ["low", "high"], defaultReasoningEffort: "low", isDefault: true,
};

async function renderBoth(pending = false) {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, enabled: false, staleTime: Infinity } } });
  client.setQueryData(queryKeys.configPublic(), { language: "zh" });
  const onSave = vi.fn();
  const onModelChange = vi.fn();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root!.render(<QueryClientProvider client={client}>
    <ConversationTurnModelControl sessionId="session-a" agentId="agent-a" model={model}
      configRevision={1} contextWindow={64_000} maxContextWindow={128_000}
      currentReasoningEffort="high" pending={pending} onSave={onSave} />
    <LauncherAssistantModelControl lang="zh" modelId="native-model" modelDisplay="GPT-6"
      choices={[{ modelId: "native-model", label: "GPT-6", providerLabel: "Provider",
        isDefault: true, providerHealthy: true, missingApiKey: false, availability: "ready" }]}
      pending={pending} selectionDisabled={false} onModelChange={onModelChange} />
  </QueryClientProvider>));
  return { onSave, onModelChange,
    triggers: [...container.querySelectorAll<HTMLButtonElement>('[data-vui="conversation-model-control-trigger"]')] };
}

describe("shared host model trigger", () => {
  it("shares the same entry while preserving Agent parameters and native model selection boundaries", async () => {
    const { triggers, onSave, onModelChange } = await renderBoth();
    expect(triggers).toHaveLength(2);
    const [agent, native] = triggers;
    expect(agent.textContent).toBe("GPT-6");
    expect(native.textContent).toBe(agent.textContent);
    expect(native.className).toBe(agent.className);
    expect(agent.querySelector("svg")?.getAttribute("class")).toContain("lucide-chevron-down");
    expect(native.querySelector("svg")?.getAttribute("class")).toBe(agent.querySelector("svg")?.getAttribute("class"));
    await act(async () => agent.click());
    expect(document.querySelector('input[aria-label="思考强度"]')).toBeTruthy();
    expect(document.querySelector('[role="combobox"]')).toBeNull();
    await act(async () => agent.click());
    await act(async () => native.click());
    expect(document.querySelector('[role="combobox"][aria-label="切换助理模型"]')).toBeTruthy();
    expect(document.querySelector('input[aria-label="思考强度"]')).toBeNull();
    expect(document.querySelector('input[aria-label="上下文大小"]')).toBeNull();
    expect(onSave).not.toHaveBeenCalled();
    expect(onModelChange).not.toHaveBeenCalled();
  });

  it("gives both hosts the same pending feedback and prevents configuration actions", async () => {
    const { triggers, onSave, onModelChange } = await renderBoth(true);
    expect(triggers).toHaveLength(2);
    for (const trigger of triggers) {
      expect(trigger.disabled).toBe(true);
      expect(trigger.getAttribute("aria-busy")).toBe("true");
      expect(trigger.querySelector('[data-slot="vui-button-pending"]')).toBeTruthy();
      await act(async () => trigger.click());
    }
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(onSave).not.toHaveBeenCalled();
    expect(onModelChange).not.toHaveBeenCalled();
  });
});
