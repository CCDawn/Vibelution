import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { AgentModelChoice } from "../../../api/types";
import { NodeInspectorOpsCard } from "./NodeInspectorOpsCard";

function candidate(modelRef: string, label: string, overrides: Partial<AgentModelChoice> = {}): AgentModelChoice {
  return {
    modelId: modelRef,
    modelRef,
    modelKey: label,
    upstreamId: label,
    label,
    model: label,
    providerId: "qwen",
    providerLabel: "通义",
    providerKind: "openai",
    providerBaseUrl: "",
    transport: "chat",
    source: "pinned",
    runtimeSelectable: true,
    availability: "pinned",
    verificationStatus: "verified",
    catalogStale: false,
    slotCompatibility: { dialogue: { allowed: true, reasonCode: "" } },
    capabilities: {},
    apiKeyEnv: "",
    apiKeyConfigured: true,
    apiKeyState: "configured",
    requiresApiKey: false,
    missingApiKey: false,
    capabilityStatus: "ready",
    capabilitySource: "catalog",
    ...overrides,
  };
}

describe("NodeInspectorOpsCard", () => {
  it("puts the current model and budget meters on the bound inspector card", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <NodeInspectorOpsCard
          stageLabel="知识搜集"
          title="知识入库"
          status={{ tone: "success", label: "待运行" }}
          unbound={false}
          agentId="agent-ingestor"
          agentName="资料入库"
          agentInitial="资"
          modelLabel="qwen-plus"
          modelMeta="通义"
          providerVisual="qwen"
          selectedModelRef="qwen-plus"
          candidates={[candidate("qwen-plus", "qwen-plus")]}
          pendingModelRef=""
          modelPending={false}
          meters={[
            { key: "tokens", label: "Tokens", percent: 8, detail: "8 / 100", warn: false },
            { key: "toolCalls", label: "工具", percent: 4, detail: "4 / 100", warn: false },
            { key: "wallClockSeconds", label: "时间", percent: 2, detail: "2 / 100", warn: false },
          ]}
          primaryOffer={null}
          busy={false}
          sessionHref={null}
          configHref="/agents?pane=config&agent=agent-ingestor"
          agents={[{ id: "agent-ingestor", name: "资料入库", initial: "资" }]}
          agentSwitchDisabled={false}
          onSelectPinned={() => undefined}
          onPromote={() => undefined}
        />
      </MemoryRouter>,
    );

    expect(markup).toContain("qwen-plus");
    expect(markup).toContain("资料入库");
    expect(markup).toContain("Tokens");
    expect(markup).toContain('data-testid="node-inspector-model-trigger"');
    expect(markup).toContain("nio-icon-link");
    expect(markup).not.toContain("source_ingestor");
    expect(markup).not.toContain("执行者");
  });
});
