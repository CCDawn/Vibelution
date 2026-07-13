import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionLlmModelOption } from "../../api/types";
import { ConversationModelSelector, resolveConversationModelSelection } from "./ConversationModelSelector";

const models: SessionLlmModelOption[] = [
  {
    modelId: "luna",
    label: "gpt-5.6-luna",
    model: "gpt-5.6-luna",
    providerId: "ai-pixel",
    providerLabel: "Ai-Pixel",
    providerKind: "relay",
    apiKeyConfigured: true,
    missingApiKey: false,
    supportsReasoningEffort: true,
    reasoningEffortValues: ["low", "medium", "high"],
    reasoningEffortOptions: [
      { value: "low", label: "低", description: "更快" },
      { value: "medium", label: "中", description: "平衡" },
      { value: "high", label: "高", description: "更深" },
    ],
    defaultReasoningEffort: "medium",
    isDefault: true,
  },
];

describe("ConversationModelSelector", () => {
  it("keeps the effective model and reasoning effort visible in the closed composer", () => {
    const html = renderToStaticMarkup(
      <ConversationModelSelector
        models={models}
        currentModelId="luna"
        currentReasoningEffort="high"
        disabled={false}
        pending={false}
        onSelectionChange={() => undefined}
      />,
    );

    expect(html).toContain("gpt-5.6-luna");
    expect(html).toContain(">高<");
    expect(html).toContain('aria-haspopup="listbox"');
  });

  it("falls back to the model default effort when the stored effort is unsupported", () => {
    const selection = resolveConversationModelSelection(models, "luna", "ultra");
    expect(selection.model?.modelId).toBe("luna");
    expect(selection.effort).toBe("medium");
    expect(selection.effortOption?.label).toBe("中");
  });
});
