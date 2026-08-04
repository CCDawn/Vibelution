import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AgentModelChoice } from "../api/types";
import {
  AgentModelPicker,
  agentModelChoiceDisabledReason,
  groupAgentModelCandidates,
} from "./AgentModelPicker";
import pickerSource from "./AgentModelPicker.tsx?raw";
import pickerStyles from "./AgentModelPicker.styles";

function candidate(
  modelRef: string,
  label: string,
  overrides: Partial<AgentModelChoice> = {},
): AgentModelChoice {
  const [providerId, modelKey] = modelRef.split("/");
  return {
    modelId: modelRef,
    modelRef,
    modelKey,
    upstreamId: modelKey,
    label,
    model: modelKey,
    providerId,
    providerLabel: providerId === "ai-pixel" ? "Ai-Pixel" : providerId,
    providerKind: "openai",
    providerBaseUrl: "https://relay.example/v1",
    transport: "responses",
    source: "discovered",
    runtimeSelectable: false,
    availability: "observed",
    verificationStatus: "unverified",
    catalogStale: false,
    slotCompatibility: { dialogue: { allowed: true, reasonCode: "" } },
    capabilities: {},
    apiKeyEnv: "",
    apiKeyConfigured: true,
    apiKeyState: "configured",
    requiresApiKey: false,
    missingApiKey: false,
    capabilityStatus: "unknown",
    capabilitySource: "unknown",
    ...overrides,
  };
}

const candidates = [
  candidate("ai-pixel/gpt-5.6-luna", "Luna", {
    reasoningEffortValues: ["low", "high"],
  }),
  candidate("ai-pixel/gpt-5.6-sol", "Sol", {
    source: "pinned",
    runtimeSelectable: true,
    availability: "pinned",
  }),
  candidate("ai-pixel/gpt-5.6-terra", "Terra"),
  candidate("ai-pixel/image2", "Image 2", {
    slotCompatibility: {
      dialogue: { allowed: false, reasonCode: "non_dialogue_model" },
    },
  }),
];

describe("AgentModelPicker", () => {
  it("renders a closed trigger with the selected model via VDialog host", () => {
    const html = renderToStaticMarkup(
      <AgentModelPicker
        candidates={candidates}
        slot={{ slot: "dialogue", label: "对话", description: "", required: true }}
        selectedModelRef="ai-pixel/gpt-5.6-sol"
        disabled={false}
        pendingModelRef=""
        configDraftDirty={false}
        agentDraftDirty={false}
        onSelectPinned={() => undefined}
        onPromote={() => undefined}
      />,
    );

    expect(html).toContain("Sol");
    expect(html).toContain('aria-haspopup="dialog"');
    expect(pickerSource).toContain("<VDialog");
    expect(pickerSource).toContain("onOpenChange={handleOpenChange}");
    expect(pickerSource).not.toContain("createPortal(");
    expect(pickerStyles.dialogContent).toContain("min(760px");
    expect(pickerStyles.dialogContent).toContain("100dvh");
  });

  it("groups one relay's models and keeps observed and incompatible rows visible in grouping", () => {
    const groups = groupAgentModelCandidates(candidates, "dialogue", "");
    expect(groups).toHaveLength(1);
    expect(groups[0]?.providerLabel).toBe("Ai-Pixel");
    expect(groups[0]?.items.map((item) => item.label)).toEqual([
      "Image 2",
      "Luna",
      "Sol",
      "Terra",
    ]);
    expect(agentModelChoiceDisabledReason(candidates[0]!, "dialogue", false)).toBe("");
    expect(agentModelChoiceDisabledReason(candidates[3]!, "dialogue", false)).toContain("对话模型");
  });

  it("searches canonical identity and preserves provider grouping", () => {
    const groups = groupAgentModelCandidates(candidates, "dialogue", "terra");
    expect(groups).toHaveLength(1);
    expect(groups[0]?.providerId).toBe("ai-pixel");
    expect(groups[0]?.items.map((item) => item.modelRef)).toEqual([
      "ai-pixel/gpt-5.6-terra",
    ]);
  });

  it("blocks promotion while either owning draft is dirty", () => {
    const discovered = candidates[0]!;
    expect(agentModelChoiceDisabledReason(discovered, "dialogue", true)).toBe(
      "请先保存或放弃未保存修改",
    );
    expect(agentModelChoiceDisabledReason(candidates[1]!, "dialogue", true)).toBe("");
  });
});
