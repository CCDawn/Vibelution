import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionLlmModelOption } from "../../api/types";
import {
  ConversationInferenceControl,
  placeInferenceMenu,
  resolveConversationInferenceEffort,
} from "./ConversationInferenceControl";
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

  it("keeps the reasoning menu compact and reserves a right-side selection column", () => {
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
    expect(styles.triggerSeparator).toContain("opacity-55");
  });

  it("places the menu fixed above the trigger when there is room", () => {
    const style = placeInferenceMenu(
      { top: 400, bottom: 428, right: 900 },
      { width: 1200, height: 800 },
    );
    expect(style.position).toBe("fixed");
    expect(style.bottom).toBe(800 - 400 + 6);
    expect(style.width).toBe(200);
    expect(Number(style.maxHeight)).toBeGreaterThanOrEqual(88);
    expect(style.right).toBe(1200 - 900);
  });

  it("flips the menu below when space above is tight", () => {
    const style = placeInferenceMenu(
      { top: 40, bottom: 68, right: 900 },
      { width: 1200, height: 800 },
    );
    expect(style.top).toBe(68 + 6);
    expect(style.bottom).toBeUndefined();
    expect(Number(style.maxHeight)).toBeGreaterThan(0);
  });

  it("clamps menu right edge so a wide panel stays on-screen", () => {
    const style = placeInferenceMenu(
      { top: 400, bottom: 428, right: 40 },
      { width: 400, height: 800 },
    );
    // width 200 → right must leave room: max right = 400 - 200 - 8 = 192, min 8
    expect(Number(style.right)).toBeGreaterThanOrEqual(8);
    expect(Number(style.right) + 200).toBeLessThanOrEqual(400 - 8 + 0.01);
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
