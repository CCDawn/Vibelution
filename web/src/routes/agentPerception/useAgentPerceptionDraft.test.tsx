// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { defaultAgentPerceptionPolicy } from "./agentPerceptionDraft";
import { useAgentPerceptionDraft } from "./useAgentPerceptionDraft";
import type { AgentPerceptionConfiguration } from "./types";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;
let result: ReturnType<typeof useAgentPerceptionDraft> | null = null;

function configuration(
  agentId: string,
  agentUpdatedAt: string,
  policyFingerprint: string,
  policy = defaultAgentPerceptionPolicy(),
): AgentPerceptionConfiguration {
  return {
    schemaVersion: 1,
    agentId,
    agentUpdatedAt,
    configurationRevision: 1,
    configured: true,
    policy,
    sourceDecisions: [],
    policyFingerprint,
    availableScopes: { teams: [], knowledgeBases: [] },
  };
}

function DraftHarness({
  agentId,
  config,
}: {
  agentId: string;
  config: AgentPerceptionConfiguration | null;
}) {
  result = useAgentPerceptionDraft(agentId, config);
  return null;
}

function render(agentId: string, config: AgentPerceptionConfiguration | null) {
  if (!root) {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  }
  act(() => {
    root?.render(<DraftHarness agentId={agentId} config={config} />);
  });
}

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
  result = null;
});

describe("useAgentPerceptionDraft", () => {
  it("keeps edits across same-policy configuration refetches", () => {
    const initial = configuration("agent-a", "v1", "policy-a");
    render("agent-a", initial);
    act(() => result?.update((policy) => ({ ...policy, enabled: true })));

    render("agent-a", { ...initial, availableScopes: { teams: [], knowledgeBases: [] } });

    expect(result?.policy.enabled).toBe(true);
    expect(result?.isDirty).toBe(true);
    expect(result?.hasConflict).toBe(false);
  });

  it("preserves independent drafts when switching between Agents", () => {
    const configA = configuration("agent-a", "v1", "policy-a");
    const configB = configuration("agent-b", "v1", "policy-b");
    render("agent-a", configA);
    act(() => result?.update((policy) => ({
      ...policy,
      background: { ...policy.background, dailyMaxRuns: 8 },
    })));
    render("agent-b", configB);
    act(() => result?.update((policy) => ({
      ...policy,
      background: { ...policy.background, dailyMaxRuns: 2 },
    })));

    render("agent-a", { ...configA });
    expect(result?.policy.background.dailyMaxRuns).toBe(8);
    render("agent-b", { ...configB });
    expect(result?.policy.background.dailyMaxRuns).toBe(2);
  });

  it("rebases an unchanged policy revision while preserving the local draft", () => {
    const initial = configuration("agent-a", "v1", "policy-a");
    render("agent-a", initial);
    act(() => result?.update((policy) => ({ ...policy, enabled: true })));

    render("agent-a", { ...initial, agentUpdatedAt: "v2", configurationRevision: 2 });

    expect(result?.policy.enabled).toBe(true);
    expect(result?.isDirty).toBe(true);
    expect(result?.hasConflict).toBe(false);
  });

  it("preserves a draft and requires an explicit reload when the policy changed elsewhere", () => {
    const initial = configuration("agent-a", "v1", "policy-a");
    render("agent-a", initial);
    act(() => result?.update((policy) => ({
      ...policy,
      background: { ...policy.background, dailyMaxRuns: 8 },
    })));

    const remotePolicy = defaultAgentPerceptionPolicy();
    remotePolicy.background.dailyMaxRuns = 2;
    render("agent-a", configuration("agent-a", "v2", "policy-b", remotePolicy));

    expect(result?.policy.background.dailyMaxRuns).toBe(8);
    expect(result?.isDirty).toBe(true);
    expect(result?.hasConflict).toBe(true);

    act(() => result?.reset());
    expect(result?.policy.background.dailyMaxRuns).toBe(2);
    expect(result?.isDirty).toBe(false);
    expect(result?.hasConflict).toBe(false);
  });

  it("adopts a new server policy when the local draft has not been touched", () => {
    const remotePolicy = defaultAgentPerceptionPolicy();
    remotePolicy.background.dailyMaxRuns = 2;
    render("agent-a", configuration("agent-a", "v1", "policy-a"));
    render("agent-a", configuration("agent-a", "v2", "policy-b", remotePolicy));

    expect(result?.policy.background.dailyMaxRuns).toBe(2);
    expect(result?.isDirty).toBe(false);
    expect(result?.hasConflict).toBe(false);
  });
});
