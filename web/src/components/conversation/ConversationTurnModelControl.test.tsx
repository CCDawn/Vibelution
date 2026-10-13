import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SessionLlmModelOption } from "../../api/types";
import { ConversationTurnModelControl } from "./ConversationTurnModelControl";
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
        model={luna}
        {...overrides}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationTurnModelControl", () => {
  it("shows the Agent model as text without a model-changing control", () => {
    const html = renderControl();
    expect(html).toContain("Luna 5.6");
    expect(html).toContain('aria-label="Agent 模型: Luna 5.6"');
    expect(html).toContain("请到 Agent 管理页修改");
    expect(html).not.toContain("<button");
    expect(html).not.toContain("aria-haspopup");
    expect(html).not.toContain("listbox");
    expect(html).not.toContain("data-override");
  });

  it("does not keep the previous Agent model during loading or error", () => {
    expect(renderControl({ loading: true })).toContain("读取模型…");
    expect(renderControl({ loading: true })).not.toContain("Luna 5.6");
    expect(renderControl({ error: true })).toContain("模型读取失败");
    expect(renderControl({ error: true })).not.toContain("Luna 5.6");
    expect(renderControl({ model: null })).toContain("未绑定模型");
  });

  it("falls back to the upstream name and constrains long labels", () => {
    expect(renderControl({ model: { ...luna, label: "" } })).toContain("gpt-5.6-luna");
    expect(styles.label).toContain("truncate");
    expect(styles.label).toContain("max-w-32");
    expect(controlSource).not.toContain("onSelectionChange");
    expect(controlSource).not.toContain("VPopover");
  });
});
