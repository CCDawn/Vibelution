/** @vitest-environment happy-dom */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../../api/queryKeys";
import type { AgentConfigWorkspaceAgent } from "../../../api/types";
import type { WorkflowRunRecord } from "../../../api/researchWorkflow";
import type { EffectiveAgentBinding } from "../../../api/types/researchWorkflow";
import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import {
  ownsResearchCurrentTask,
  researchArchiveReturnNodeId,
  ResearchProcessInspectorPane,
} from "./ResearchProcessInspectorPane";
import type { ResearchProcessPanel } from "./researchProcessPanelSelection";
import type { NodeDetailState } from "./useNodeDetailState";

const leafHarness = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
}));
const hypothesisLeafHarness = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
}));

vi.mock("../teamLazyPanels", async () => {
  const actual = await vi.importActual<typeof import("../teamLazyPanels")>("../teamLazyPanels");
  return {
    ...actual,
    ResearchProcessNodeInspector: (props: Record<string, unknown>) => {
      leafHarness.props = props;
      return <div data-testid="mock-research-process-node-inspector" />;
    },
    HypothesisFirstNodeInspector: (props: Record<string, unknown>) => {
      hypothesisLeafHarness.props = props;
      return <div data-testid="mock-hypothesis-first-node-inspector" />;
    },
  };
});

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

function makeReadyNodeDetail(): NodeDetailState {
  return {
    kind: "ready",
    detail: {
      runId: "run-1",
      teamId: "research-team",
      nodeId: "source_finding",
      runVersion: 1,
      actorKind: "agent",
      primaryRoleKey: "source_finder",
      label: "资料寻找",
      runtimeCurrent: true,
      status: "waiting_human",
      attempts: [],
      commandOffers: [],
      latestEventSequence: 1,
      generatedAt: "2026-08-24T00:00:00.000Z",
      agentId: "agent-finder",
      displayName: "Finder Agent",
      resolvedFrom: "workflow_default",
      sessionAnchorDegraded: false,
      chatDeepLink: null,
      nodeAttempt: 1,
      blockedReason: "",
    } as ResearchWorkflowNodeDetail,
  };
}

async function renderInspectorLeaf(
  language: "zh" | "en",
  scope: InspectorProps["scope"],
  nodeDetail: NodeDetailState = { kind: "idle" },
  extras: Partial<Pick<InspectorProps, "nextAction" | "onRecoverCollection" | "allowLaunchPanel">> = {},
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
            {...extras}
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

describe("ResearchProcessInspectorPane collection recovery wiring", () => {
  afterEach(() => {
    leafHarness.props = null;
    hypothesisLeafHarness.props = null;
    document.body.innerHTML = "";
  });

  it("forwards the current collection recovery props to the node inspector leaf", async () => {
    const onRecoverCollection = async () => undefined;
    const { container, root } = await renderInspectorLeaf(
      "zh",
      makeInspectorScope("node", {
        selectedNodeId: "source_finding",
      }),
      makeReadyNodeDetail(),
    );

    // The helper renders the default node state first; rerender the pane with
    // the recovery action so the assertion covers the actual prop boundary.
    await act(async () => {
      root.render(
        <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
          <MemoryRouter>
            <ResearchProcessInspectorPane
              scope={makeInspectorScope("node", { selectedNodeId: "source_finding" })}
              state={makeInspectorState(makeReadyNodeDetail())}
              actions={makeInspectorActions()}
              nextAction={{
                stage: "collection_recovery",
                targetNodeId: "source_finding",
                navigationLabel: "打开资料搜集",
                command: "retry_collection",
                collectionRequestId: "collection-request-1",
              }}
              onRecoverCollection={onRecoverCollection}
              collectionRecoveryBusy
              collectionRecoveryError="worker unavailable"
            />
          </MemoryRouter>
        </QueryClientProvider>,
      );
    });

    expect(container.querySelector('[data-testid="mock-research-process-node-inspector"]')).not.toBeNull();
    expect(leafHarness.props?.collectionRecoveryRequestId).toBe("collection-request-1");
    expect(leafHarness.props?.onRecoverCollection).toBe(onRecoverCollection);
    expect(leafHarness.props?.collectionRecoveryBusy).toBe(true);
    expect(leafHarness.props?.collectionRecoveryError).toBe("worker unavailable");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it("keeps collection recovery mutation out of source and hypothesis leaves without an owner callback", async () => {
    const nextAction = {
      stage: "collection_recovery" as const,
      targetNodeId: "source_finding",
      navigationLabel: "前往资料搜集",
      command: "retry_collection" as const,
      collectionRequestId: "collection-request-1",
    };
    const source = await renderInspectorLeaf(
      "zh",
      makeInspectorScope("node", { selectedNodeId: "source_finding" }),
      makeReadyNodeDetail(),
      { nextAction },
    );

    expect(leafHarness.props?.onRecoverCollection).toBeUndefined();
    expect(leafHarness.props?.collectionRecoveryBusy).toBe(false);
    expect(leafHarness.props?.collectionRecoveryError).toBeNull();
    await act(async () => source.root.unmount());
    source.container.remove();

    const hypothesis = await renderInspectorLeaf(
      "zh",
      makeInspectorScope("node", { selectedNodeId: "hf_collection" }),
      { kind: "idle" },
      { nextAction },
    );

    expect(hypothesisLeafHarness.props?.onRetryCollection).toBeUndefined();
    await act(async () => hypothesis.root.unmount());
    hypothesis.container.remove();
  });

  it("hides launch actions when the URL is stale during collection recovery", async () => {
    const { container, root } = await renderInspectorLeaf(
      "zh",
      makeInspectorScope("launch", { runId: "", selectedNodeId: null, questionId: "SCI-004" }),
      { kind: "idle" },
      {
        nextAction: {
          stage: "collection_recovery",
          targetNodeId: "source_finding",
          navigationLabel: "前往资料搜集",
          command: "retry_collection",
          commandLabel: "重试搜集",
          collectionRequestId: "collection-request-1",
          recovery: {
            command: "retry_collection",
            label: "重试搜集",
            reason: "资料搜集失败，请重试。",
          },
        },
        onRecoverCollection: async () => undefined,
      },
    );

    expect(container.textContent).toContain("资料补充需要处理");
    expect(container.textContent).not.toContain("取消");
    expect(container.textContent).not.toContain("开始实验");
    expect(container.textContent).not.toContain("重试搜集");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });

  it.each([
    ["formal runtime", undefined],
    ["hypothesis-first", {
      stage: "selection_required" as const,
      targetNodeId: "hf_selection",
      navigationLabel: "前往假说选择",
      command: "record_selection" as const,
      commandLabel: "记录选择并开启评审",
    }],
  ])("hides the launch actions from a stale URL when %s owns the task", async (_label, nextAction) => {
    const { container, root } = await renderInspectorLeaf(
      "zh",
      makeInspectorScope("launch", { runId: "run-1", selectedNodeId: null, questionId: "SCI-004" }),
      { kind: "idle" },
      { nextAction, allowLaunchPanel: false },
    );

    expect(container.textContent).toContain("当前任务已接管操作");
    expect(container.textContent).not.toContain("开始实验");
    expect(container.textContent).not.toContain("新建运行");

    await act(async () => {
      root.unmount();
    });
    container.remove();
  });
});
