import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionLlmModelOption } from "../../api/types";
import {
  ConversationInferenceControl,
  resolveConversationInferenceEffort,
} from "./ConversationInferenceControl";
import controlSource from "./ConversationInferenceControl.tsx?raw";
import styles from "./ConversationInferenceControl.styles";

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
    expect(html).toContain('aria-hidden="true">·</span>');
    expect(html).not.toContain('data-slot="vui-button-label"');
    expect(html).not.toContain("选择模型");
    expect(html).not.toContain("Sol");
  });

  it("hosts the reasoning menu on VPopover instead of a hand-placed portal", () => {
    expect(controlSource).toContain("<VPopover");
    expect(controlSource).toContain('data-vui="conversation-inference-menu"');
    expect(controlSource).toContain("contentClassName={styles.menu}");
    expect(controlSource).not.toContain("createPortal(");
    expect(controlSource).not.toContain("placeInferenceMenu");
    expect(styles.menu).toContain("w-[min(200px,calc(100vw-16px))]");
    expect(styles.menu).toContain("overflow-y-auto");
    expect(styles.menu).not.toContain("absolute");
    expect(styles.option).toContain("!grid-cols-[minmax(0,1fr)_0.875rem]");
    expect(styles.option).toContain("!min-h-9");
    expect(styles.option).toContain("data-[selected=true]");
    expect(styles.optionDescription).toContain("line-clamp-2");
    expect(styles.trigger).toContain("data-[open=true]");
    expect(styles.triggerChevron).toContain("data-[open=true]:rotate-180");
    expect(styles.trigger).toContain("!px-1.5");
    expect(styles.trigger).toContain("!max-w-full");
    expect(styles.trigger).not.toContain("max-w-[min(200px");
    expect(styles.trigger).not.toContain("max-[719px]:!max-w-[min(148px");
    expect(styles.triggerModel).toContain("whitespace-nowrap");
    expect(styles.triggerModel).not.toContain("truncate");
    expect(styles.fixedLabel).toContain("max-w-full");
    expect(styles.fixedLabel).not.toContain("max-w-[200px]");
    expect(styles.triggerSeparator).toContain("opacity-55");
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
