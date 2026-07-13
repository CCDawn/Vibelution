import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionLlmModelOption } from "../../api/types";
import { ConversationInferenceControl, resolveConversationInferenceEffort } from "./ConversationInferenceControl";

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

describe("ConversationInferenceControl", () => {
  it("shows one fixed model and only its current effort", () => {
    const html = renderToStaticMarkup(
      <ConversationInferenceControl
        model={luna}
        currentReasoningEffort="high"
        disabled={false}
        pending={false}
        onReasoningEffortChange={() => undefined}
      />,
    );

    expect(html).toContain("Luna 5.6");
    expect(html).toContain("高");
    expect(html).not.toContain("选择模型");
    expect(html).not.toContain("Sol");
  });

  it("keeps models without reasoning as a non-interactive label", () => {
    const html = renderToStaticMarkup(
      <ConversationInferenceControl
        model={{ ...luna, reasoningEffortValues: [], reasoningEffortOptions: [] }}
        currentReasoningEffort=""
        disabled={false}
        pending={false}
        onReasoningEffortChange={() => undefined}
      />,
    );

    expect(html).toContain("Luna 5.6");
    expect(html).not.toContain('aria-haspopup="listbox"');
  });

  it("falls back to the declared model default", () => {
    expect(resolveConversationInferenceEffort(luna, "unsupported").effort).toBe("low");
  });
});
