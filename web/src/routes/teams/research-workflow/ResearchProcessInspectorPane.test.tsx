/** @vitest-environment happy-dom */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import type { AgentConfigWorkspaceAgent } from "../../../api/types";
import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import {
  ownsResearchCurrentTask,
  researchArchiveReturnNodeId,
  ResearchProcessInspectorPane,
} from "./ResearchProcessInspectorPane";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import type { NodeDetailState } from "./useNodeDetailState";

type InspectorProps = ComponentProps<typeof ResearchProcessInspectorPane>;

const BINDINGS: EffectiveAgentBinding[] = [
  { nodeId: "source_finding", roleKey: "source_finder", agentId: "agent-finder", resolvedFrom: "workflow_default" },
];

function makeRun(): WorkflowRunRecord {
  return {
    runId: "run-1",
    workflowId: "challenge-cup-research",
    workflowVersionId: "wv-x",
    status: "waiting_human",
    bindingSnapshots: [
      { snapshotId: "s1", nodeId: "source_finding", agentId: "agent-finder", roleKey: "source_finder", resolvedFrom: "workflow_default" },
    ],
    sessionBindings: {},
    events: [],
    humanTasks: [],
    handoffs: [],
  } as unknown as WorkflowRunRecord;
}

async function flushUntil(container: HTMLElement, marker: string) {
  // The agents leaf is a lazy pack facade: the first flush must cover the
  // on-demand transform of the whole research-workflow chunk.
  for (let index = 0; index < 400 && !container.textContent?.includes(marker); index += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 25));
    });
  }
}

async function renderAgentsPane(language: "zh" | "en") {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryDefaults(queryKeys.configPublic(), { staleTime: Number.POSITIVE_INFINITY });
  queryClient.setQueryData(queryKeys.configPublic(), { language });
  queryClient.setQueryData<AgentConfigWorkspaceAgent[]>(queryKeys.agentSummary(false), [
    {
      agentId: "agent-finder",
      llmBindings: { dialogue: { modelId: "qwen-plus" } },
    } as AgentConfigWorkspaceAgent,
  ]);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ResearchProcessInspectorPane
            scope={{
              teamId: "research-team",
              teamName: "",
              linkedChatRoomId: "",
              runId: "",
              selectedNodeId: null,
              questionId: "",
              panel: "agents",
            }}
            state={{
              run: makeRun(),
              projection: null,
              effectiveBindings: BINDINGS,
              nodeDetail: { kind: "idle" },
              insights: {
                ledger: null,
                budget: null,
                hypotheses: null,
                campaigns: null,
                evaluation: null,
                handoffs: null,
                loading: false,
                error: null,
              },
              busy: false,
            }}
            actions={{
              replaceParams: () => undefined,
              retryNodeDetail: () => undefined,
              submitRun: async () => undefined,
              pendingTaskId: () => null,
              submitOffer: async () => undefined,
            }}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
  return { container, root };
}

function makeInspectorScope(panel: ResearchProcessPanel, patch: Partial<InspectorProps["scope"]> = {}): InspectorProps["scope"] {
  return {
    teamId: "research-team",
    teamName: "",
    linkedChatRoomId: "",
    runId: "run-1",
    selectedNodeId: "controlled_run",
    questionId: "",
    panel,
    ...patch,
  };
}

function makeInspectorState(nodeDetail: NodeDetailState = { kind: "idle" }): InspectorProps["state"] {
  return {
    run: null,
    projection: null,
    effectiveBindings: BINDINGS,
    nodeDetail,
    insights: {
      ledger: null,
      budget: null,
      hypotheses: null,
      campaigns: null,
      evaluation: null,
      handoffs: null,
      loading: false,
      error: null,
    },
    busy: false,
  };
}

function makeInspectorActions(): InspectorProps["actions"] {
  return {
    replaceParams: () => undefined,
    retryNodeDetail: () => undefined,
    submitRun: async () => undefined,
    pendingTaskId: () => null,
    submitOffer: async () => undefined,
  };
}

async function renderInspectorLeaf(
  language: "zh" | "en",
  scope: InspectorProps["scope"],
  nodeDetail: NodeDetailState = { kind: "idle" },
) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.configPublic(), { language });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ResearchProcessInspectorPane
            scope={scope}
            state={makeInspectorState(nodeDetail)}
            actions={makeInspectorActions()}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  });
  return { container, root };
}

describe("ResearchProcessInspectorPane agents panel language", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("follows the shell language when it is English", async () => {
    const { container, root } = await renderAgentsPane("en");
    await flushUntil(container, "Model");

    expect(container.textContent).toContain("Role");
    expect(container.textContent).toContain("Model");
    expect(container.textContent).toContain("Status");
    expect(container.textContent).toContain("qwen-plus");
    expect(container.textContent).not.toContain("职责");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("keeps Chinese when the shell language is Chinese", async () => {
    const { container, root } = await renderAgentsPane("zh");
    await flushUntil(container, "模型");

    expect(container.textContent).toContain("职责");
    expect(container.textContent).toContain("模型");
    expect(container.textContent).toContain("状态");
    expect(container.textContent).toContain("qwen-plus");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("localizes inspector fallback states when the shell language is English", async () => {
    const cases: Array<{
      scope: InspectorProps["scope"];
      nodeDetail?: NodeDetailState;
      marker: string;
    }> = [
      {
        scope: makeInspectorScope("question", { questionId: "" }),
        marker: "Question review",
      },
      {
        scope: makeInspectorScope("evidence", { runId: "" }),
        marker: "Evidence relations unavailable",
      },
      {
        scope: makeInspectorScope("node", { selectedNodeId: null }),
        marker: "Select a workflow node",
      },
      {
        scope: makeInspectorScope("node"),
        nodeDetail: { kind: "loading" },
        marker: "Loading node details",
      },
      {
        scope: makeInspectorScope("node"),
        nodeDetail: { kind: "error", nodeId: "controlled_run", message: "backend unavailable" },
        marker: "Node details failed to load: backend unavailable",
      },
      {
        scope: makeInspectorScope("node"),
        nodeDetail: { kind: "empty", nodeId: "controlled_run" },
        marker: "No node details yet",
      },
    ];

    for (const testCase of cases) {
      const { container, root } = await renderInspectorLeaf("en", testCase.scope, testCase.nodeDetail);
      expect(container.textContent).toContain(testCase.marker);
      expect(container.textContent).not.toMatch(/[\u4e00-\u9fff]/);
      await act(async () => {
        root.unmount();
      });
      container.remove();
    }
  });
});

describe("ResearchProcessInspectorPane current-task ownership", () => {
  it("compares ledger attempts through their stable semantic canvas node", () => {
    expect(ownsResearchCurrentTask("hf_selection", "hf_meeting_1")).toBe(false);
    expect(ownsResearchCurrentTask("hf_review", "hf_meeting_1")).toBe(true);
    expect(ownsResearchCurrentTask("hf_collection", "source_finding")).toBe(true);
    expect(ownsResearchCurrentTask("source_finding", null)).toBe(false);
  });

  it("returns from the archive to the semantic current task", () => {
    expect(researchArchiveReturnNodeId("hf_selection", "hf_meeting_4")).toBe("hf_review");
    expect(researchArchiveReturnNodeId("hf_collection", null)).toBe("hf_collection");
  });
});
