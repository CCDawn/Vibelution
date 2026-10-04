import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionLlmModelOption } from "../../api/types";
import {
  ConversationTurnModelControl,
  effectiveTurnModelId,
  resolveTurnModelSelectionLabel,
} from "./ConversationTurnModelControl";
import controlSource from "./ConversationTurnModelControl.tsx?raw";
import styles from "./ConversationTurnModelControl.styles";

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

const sol: SessionLlmModelOption = {
  ...luna,
  modelId: "ai-pixel/sol-4",
  modelRef: "ai-pixel/sol-4",
  label: "Sol 4",
  model: "sol-4",
  isDefault: false,
};

const choices = [luna, sol];

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
        choices={choices}
        sessionDefaultModelId="ai-pixel/gpt-5.6-luna"
        selection={null}
        disabled={false}
        onSelectionChange={() => undefined}
        {...overrides}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationTurnModelControl", () => {
  it("follows the session default model when no override is pinned", () => {
    const html = renderControl();
    expect(html).toContain("Luna 5.6");
    expect(html).toContain("本轮模型");
    expect(html).toContain('aria-label="本轮模型: Luna 5.6"');
    expect(html).not.toContain('data-override="true"');
  });

  it("marks a pinned non-default override with the ≠default chip state", () => {
    const html = renderControl({ selection: { modelId: "ai-pixel/sol-4" } });
    expect(html).toContain("Sol 4");
    expect(html).toContain('aria-label="本轮模型: Sol 4"');
    expect(html).toContain('data-override="true"');
  });

  it("keeps the scope label visible and prefixes the existing follow or override tooltip", () => {
    expect(controlSource).toContain('lang === "zh" ? "本轮模型" : "Model for this turn"');
    expect(controlSource).toContain('t("turnModelOverrideTooltip").replace("{model}", effectiveLabel)');
    expect(controlSource).toContain('t("turnModelFollowTooltip").replace("{model}", effectiveLabel)');
    expect(controlSource).toContain("tooltip={turnModelTooltip}");
    expect(controlSource).toContain("max-w-32 truncate");
  });

  it("does not mark an override that re-pins the session default model", () => {
    const html = renderControl({ selection: { modelId: "ai-pixel/gpt-5.6-luna" } });
    expect(html).not.toContain('data-override="true"');
  });

  it("hosts the menu on VPopover with a flat panel, never a hand-placed portal", () => {
    expect(controlSource).toContain("<VPopover");
    expect(controlSource).toContain('data-vui="conversation-turn-model-menu"');
    expect(controlSource).toContain("contentClassName={styles.menu}");
    expect(controlSource).not.toContain("createPortal(");
    expect(styles.menu).toContain("overflow-y-auto");
    expect(styles.menu).not.toContain("absolute");
    expect(styles.option).toContain("!grid-cols-[minmax(0,1fr)_0.875rem]");
    expect(styles.option).toContain("data-[selected=true]");
  });

  it("keeps the ≠default marker on a token-based accent, not a raw hex color", () => {
    expect(styles.overrideDot).toContain("var(--accent-cool)");
    expect(styles.overrideDot).not.toMatch(/#[0-9a-fA-F]{3,8}/);
    expect(styles.triggerOverride).toContain("var(--accent-cool)");
  });

  it("resolves labels through modelRef then library id", () => {
    expect(resolveTurnModelSelectionLabel(choices, "ai-pixel/sol-4")).toBe("Sol 4");
    expect(resolveTurnModelSelectionLabel(choices, "unknown/model")).toBe("unknown/model");
    expect(effectiveTurnModelId("ai-pixel/gpt-5.6-luna", null)).toBe("ai-pixel/gpt-5.6-luna");
    expect(effectiveTurnModelId("ai-pixel/gpt-5.6-luna", { modelId: "ai-pixel/sol-4" })).toBe(
      "ai-pixel/sol-4",
    );
  });
});
