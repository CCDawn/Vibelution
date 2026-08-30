/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { AgentModelChoice } from "../../../api/types";
import type { CommandOffer } from "../../../api/types/research-workflow/commands";
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

  it("surfaces a productized inline error when the primary offer fails", async () => {
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const primaryOffer = {
      command: "start_node",
      idempotencyKey: "key-ops",
      label: "启动节点",
      available: true,
      reasonCode: "",
      blockerIds: [],
    } as unknown as CommandOffer;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
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
            meters={[]}
            primaryOffer={primaryOffer}
            busy={false}
            onOffer={async () => {
              throw new Error("source search is still running");
            }}
            sessionHref={null}
            configHref={null}
            agents={[]}
            agentSwitchDisabled
            onSelectPinned={() => undefined}
            onPromote={() => undefined}
          />
        </MemoryRouter>,
      );
    });

    const button = Array.from(container.querySelectorAll("button"))
      .find((item) => item.textContent?.includes("启动节点"));
    expect(button).toBeTruthy();
    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("资料搜索仍在进行");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("shows a stale primary offer's refresh reason inline instead of tooltip-only", () => {
    const staleOffer = {
      command: "retry_node",
      idempotencyKey: "key-stale-primary",
      label: "重试节点",
      available: false,
      reasonCode: "node_in_flight",
      blockerIds: [],
      expectedRunVersion: 5,
    } as unknown as CommandOffer;
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <NodeInspectorOpsCard
          stageLabel="知识搜集"
          title="知识入库"
          status={{ tone: "warning", label: "阻塞" }}
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
          meters={[]}
          primaryOffer={staleOffer}
          busy={false}
          runVersion={8}
          sessionHref={null}
          configHref={null}
          agents={[]}
          agentSwitchDisabled
          onSelectPinned={() => undefined}
          onPromote={() => undefined}
        />
      </MemoryRouter>,
    );

    expect(markup).toContain("重试节点");
    expect(markup).toContain("运行状态已更新，请刷新后重试");
    expect(markup).toContain('role="status"');
    expect(markup).not.toContain("当前节点已在执行");
  });
});
