// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../components/vui", () => ({ VNativeButton: () => null }));
vi.mock("./AgentDetailHeaderPanel", () => ({ AgentDetailHeaderPanel: () => null }));
vi.mock("./AgentFocusedOverviewPanel", () => ({ AgentFocusedOverviewPanel: () => null }));
vi.mock("./finance/FinancialAssistantStatusNote", () => ({ FinancialAssistantStatusNote: () => null }));
vi.mock("./shared/ProgressiveRegionSkeleton", () => ({ ProgressiveRegionSkeleton: () => null }));
vi.mock("./AgentPerceptionPane", async () => {
  const ReactModule = await import("react");
  const { defaultAgentPerceptionPolicy } = await import("./agentPerception/agentPerceptionDraft");
  const { useAgentPerceptionDraft } = await import("./agentPerception/useAgentPerceptionDraft");

  function AgentPerceptionPaneStub({ agentId, draftStore }: { agentId: string; draftStore?: unknown }) {
    const config = {
      schemaVersion: 1 as const,
      agentId,
      agentUpdatedAt: `${agentId}-revision-1`,
      configurationRevision: 1,
      configured: true,
      policy: defaultAgentPerceptionPolicy(),
      sourceDecisions: [],
      policyFingerprint: `${agentId}-policy-1`,
      availableScopes: { teams: [], knowledgeBases: [] },
    };
    const draft = useAgentPerceptionDraft(agentId, config, draftStore as never);
    const nextLimit = agentId === "agent-a" ? 8 : 2;
    return ReactModule.createElement(
      "div",
      null,
      ReactModule.createElement("output", { "data-testid": `draft-${agentId}` }, String(draft.policy.background.dailyMaxRuns)),
      ReactModule.createElement(
        "button",
        {
          type: "button",
          "data-testid": `edit-${agentId}`,
          onClick: () => draft.update((policy) => ({
            ...policy,
            background: { ...policy.background, dailyMaxRuns: nextLimit },
          })),
        },
        `Edit ${agentId}`,
      ),
    );
  }

  return { AgentPerceptionPane: AgentPerceptionPaneStub };
});

import {
  AgentSelectedDetailContentPanel,
  type AgentSelectedDetailContentPanelProps,
} from "./AgentSelectedDetailContentPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function panelProps(agentId: string, activePane: AgentSelectedDetailContentPanelProps["activePane"]): AgentSelectedDetailContentPanelProps {
  return {
    agentId,
    activePane,
    header: {
      lang: "en",
      agentName: agentId,
      activePane,
      onSelectPane: () => undefined,
      panes: [],
    } as never,
    brief: {} as never,
    overview: null,
    resources: null,
    configChanges: {} as never,
    configPrimary: { healthMaintenance: undefined } as never,
    configPolicies: {} as never,
    configReferences: {} as never,
    virtualHumanPlugin: {} as never,
    activity: {} as never,
    onOpenSession: () => undefined,
  };
}

async function render(agentId: string, activePane: AgentSelectedDetailContentPanelProps["activePane"]) {
  if (!root) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  }
  act(() => {
    root?.render(<AgentSelectedDetailContentPanel {...panelProps(agentId, activePane)} />);
  });
  await act(async () => {
    await vi.dynamicImportSettled();
  });
}

function draftValue(agentId: string) {
  return container?.querySelector(`[data-testid="draft-${agentId}"]`)?.textContent ?? null;
}

function edit(agentId: string) {
  act(() => {
    container?.querySelector<HTMLButtonElement>(`[data-testid="edit-${agentId}"]`)?.click();
  });
}

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
});

describe("AgentSelectedDetailContentPanel perception draft lifecycle", () => {
  it("retains each Agent draft across Agent switches and leaving and returning to perception", async () => {
    await render("agent-a", "perception");
    edit("agent-a");
    expect(draftValue("agent-a")).toBe("8");

    await render("agent-b", "perception");
    edit("agent-b");
    expect(draftValue("agent-b")).toBe("2");

    await render("agent-a", "perception");
    expect(draftValue("agent-a")).toBe("8");

    await render("agent-a", "overview");
    await render("agent-a", "perception");
    expect(draftValue("agent-a")).toBe("8");

    await render("agent-b", "perception");
    expect(draftValue("agent-b")).toBe("2");
  });
});
