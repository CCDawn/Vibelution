/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode, MemoryKnowledgeGraphPayload } from "../api/types";
import { VuiProvider } from "../components/vui";
import { MemoryGraphViewPanel, type MemoryGraphViewPanelCopy } from "./MemoryGraphViewPanel";

vi.mock("./MemoryGraphCanvas", async () => {
  const ReactModule = await import("react");
  return {
    MemoryGraphCanvas: (props: {
      nodes: MemoryKnowledgeGraphNode[];
      edges: MemoryKnowledgeGraphEdge[];
      onSelectNode: (nodeId: string) => void;
      onSelectEdge: (edgeId: string) => void;
    }) => ReactModule.createElement(
      "div",
      { "data-testid": "mock-graph-canvas", "data-node-ids": props.nodes.map(node => node.id).join(",") },
      ...props.nodes.map(node => ReactModule.createElement(
        "button",
        { key: node.id, type: "button", "data-testid": `canvas-node-${node.id}`, onClick: () => props.onSelectNode(node.id) },
        node.label,
      )),
      ...props.edges.map(edge => ReactModule.createElement(
        "button",
        { key: edge.id, type: "button", "data-testid": `canvas-edge-${edge.id}`, onClick: () => props.onSelectEdge(edge.id) },
        edge.label,
      )),
      ReactModule.createElement("span", { "data-testid": "canvas-edges", "data-edge-ids": props.edges.map(edge => edge.id).join(",") }),
    ),
  };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const copy: MemoryGraphViewPanelCopy = {
  graphSelectedNode: "已选节点",
  graphNoSelection: "未选择节点",
  graphResponsibilityQuestion: "责任问题",
  status: "状态",
  sourceOrigin: "来源",
  generatedAt: "更新时间",
  graphDirectChildren: "直接子节点",
  graphNoChildren: "暂无子节点",
  graphNodeKnowledge: "关联知识",
  graphKnowledgeLoading: "正在读取知识",
  graphNoKnowledge: "暂无关联知识",
  graphKnowledgeTruncated: "内容已截断",
  graphRelations: "关系",
  graphNoRelations: "暂无关系",
  graphIncoming: "指向此节点",
  graphOutgoing: "从此节点出发",
  graphVisibleNodes: "可见节点",
  graphNodes: "节点",
  graphVisibleEdges: "可见关系",
  graphEdges: "关系",
  graphGpu: "GPU",
  yes: "是",
  no: "否",
  graphWorker: "布局任务",
  graphReadOnly: "只读图谱",
  graphAcl: "遵循知识库权限",
  knowledgeGraph: "记忆知识图谱",
  filters: "筛选",
  graphSearchPlaceholder: "搜索记忆或来源",
  graphNodeTypes: "节点类型",
  graphClearFocus: "清除筛选",
  loading: "正在加载图谱",
  graphInteractionHint: "拖动与缩放",
  graphCanvasFallback: "图形渲染不可用",
};

const date = "2026-09-30T00:00:00.000Z";
const itemSummary = { id: "item-a", type: "memory", title: "Alpha 的记录", summary: "来自会话", updatedAt: date };
const itemDetail = { ...itemSummary, content: "完整正文仅在选中后读取" };
const node = (id: string, label: string, contentItems: MemoryKnowledgeGraphNode["contentItems"] = []): MemoryKnowledgeGraphNode => ({
  id,
  type: "agent_private_memory",
  label,
  summary: `${label}摘要`,
  status: "active",
  createdAt: date,
  updatedAt: date,
  metadata: {},
  responsibilityQuestion: "",
  visual: {},
  childNodeIds: [],
  contentItems,
});
const nodes = [node("alpha", "Alpha", [itemSummary]), node("beta", "Beta"), node("gamma", "Gamma")];
const edges: MemoryKnowledgeGraphEdge[] = [
  { id: "alpha-beta", source: "alpha", target: "beta", type: "related", label: "提及", weight: 1, metadata: {} },
  { id: "beta-gamma", source: "beta", target: "gamma", type: "related", label: "延伸", weight: 1, metadata: {} },
];
const graphPayload: MemoryKnowledgeGraphPayload = {
  schemaVersion: 1,
  mode: "read_only_project_memory_graph",
  agentId: "actor-a",
  summary: {
    nodeCount: nodes.length,
    edgeCount: edges.length,
    truncated: false,
    nodeTypeCounts: { agent_private_memory: nodes.length },
    edgeTypeCounts: { related: edges.length },
    elapsedMs: 1,
  },
  nodes,
  edges,
  filters: { include: ["officialResearchGraph"] },
  operatingBoundary: {
    readOnly: true,
    gpuPreferred: true,
    layoutWorker: true,
    honorsKnowledgeAcl: true,
    fullContentIncluded: false,
    canEditGraph: false,
    canApplyKnowledge: false,
  },
};

type HarnessOptions = {
  payloadMode?: "default" | "structure" | "empty" | "none";
  graphLoading?: boolean;
  graphError?: string;
  initialQuery?: string;
  onRetry?: () => void;
  withTeam?: boolean;
  onActorChange?: (agentId: string) => void;
  onTeamChange?: (teamId: string) => void;
};

function Harness({
  payloadMode = "default",
  graphLoading = false,
  graphError = "",
  initialQuery = "",
  onRetry = () => undefined,
  withTeam = false,
  onActorChange = () => undefined,
  onTeamChange = () => undefined,
}: HarnessOptions) {
  const [query, setQuery] = React.useState(initialQuery);
  const [nodeType, setNodeType] = React.useState("");
  const [selectedId, setSelectedId] = React.useState("");
  const [actorId, setActorId] = React.useState("actor-a");
  const [teamId, setTeamId] = React.useState("");
  const team = { ...node("team:research-team", "研究团队"), type: "team", metadata: { teamId: "research-team" } };
  const payloadNodes = payloadMode === "empty" ? [] : payloadMode === "structure" ? [
    { ...node("project", "项目"), type: "project" }, { ...node("agent", "Agent"), type: "agent" },
  ] : withTeam ? [...nodes, team] : nodes;
  const payload = payloadMode === "none" ? undefined : { ...graphPayload, nodes: payloadNodes,
    edges: payloadMode === "empty" || payloadMode === "structure" ? [] : edges,
    summary: { ...graphPayload.summary, nodeCount: payloadNodes.length } };
  const selectedNode = payload?.nodes.find(candidate => candidate.id === selectedId) ?? null;

  return (
    <VuiProvider>
      <MemoryGraphViewPanel
        copy={copy}
        graphPayload={payload}
        isGraphLoading={graphLoading}
        graphError={graphError}
        onRetryGraph={onRetry}
        graphActorAgentId={actorId}
        graphActorChoices={[{ agentId: "actor-a", displayName: "Agent A" }, { agentId: "actor-b", displayName: "Agent B" }]}
        graphTeamId={teamId}
        onGraphActorChange={id => { setActorId(id); setTeamId(""); onActorChange(id); }}
        onGraphTeamChange={id => { setTeamId(id); onTeamChange(id); }}
        graphSearchText={query}
        activeGraphNodeType={nodeType}
        graphTypeEntries={payload ? Object.entries(payload.summary.nodeTypeCounts) : []}
        selectedGraphNode={selectedNode}
        selectedGraphChildren={[]}
        selectedGraphRelations={{ incoming: [], outgoing: [] }}
        selectedGraphDetailItems={selectedNode?.id === "alpha" ? [itemDetail] : []}
        isGraphNodeDetailFetching={false}
        formatTimestamp={value => value}
        onGraphSearchTextChange={setQuery}
        onActiveGraphNodeTypeChange={setNodeType}
        onClearGraphFilters={() => { setQuery(""); setNodeType(""); }}
        onSelectGraphNode={setSelectedId}
        onFocusGraphNode={setSelectedId}
      />
    </VuiProvider>
  );
}

let root: Root | null = null;
let host: HTMLDivElement | null = null;

async function renderPanel(options: HarnessOptions = {}) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root!.render(<Harness {...options} />);
    await Promise.resolve();
    await Promise.resolve();
  });
  return host;
}

async function click(element: Element | null) {
  if (!element) throw new Error("Expected a clickable element in the rendered panel");
  await act(async () => { (element as HTMLElement).click(); });
}

async function enterSearch(value: string) {
  const input = host?.querySelector<HTMLInputElement>('input[aria-label="搜索记忆或来源"]');
  if (!input) throw new Error("Expected the graph search input");
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function chooseScope(label: string, value: string) {
  const select = host?.querySelector<HTMLSelectElement>(`select[aria-label="${label}"]`);
  if (!select) throw new Error("Expected graph scope selector");
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

beforeEach(() => {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1440 });
});

afterEach(async () => {
  if (root) await act(async () => root?.unmount());
  root = null;
  host?.remove();
  host = null;
});

describe("MemoryGraphViewPanel", () => {
  it("changes explicit actor and authorized team scope while clearing filters and private reading", async () => {
    const actorChanged = vi.fn();
    const teamChanged = vi.fn();
    const view = await renderPanel({ withTeam: true, onActorChange: actorChanged, onTeamChange: teamChanged });
    const teamSelect = view.querySelector<HTMLSelectElement>('select[aria-label="团队范围"]');
    expect(Array.from(teamSelect?.options ?? []).map(option => option.value)).toEqual(["", "research-team"]);
    await click(view.querySelector('[data-testid="canvas-node-alpha"]'));
    expect(view.textContent).toContain("完整正文仅在选中后读取");
    await chooseScope("团队范围", "research-team");
    expect(teamChanged).toHaveBeenCalledWith("research-team");
    expect(view.querySelector('[data-vui-region="memory-graph-inspector"]')).toBeNull();
    await enterSearch("Alpha");
    await click(view.querySelector('[data-testid="canvas-node-alpha"]'));
    await chooseScope("读取身份", "actor-b");
    expect(actorChanged).toHaveBeenCalledWith("actor-b");
    expect(teamSelect?.value).toBe("");
    expect(view.querySelector<HTMLInputElement>('input[aria-label="搜索记忆或来源"]')?.value).toBe("");
    expect(view.textContent).not.toContain("完整正文仅在选中后读取");
    expect(view.querySelector('[data-vui-region="memory-graph-inspector"]')).toBeNull();
  });

  it("explains a structure-only actor scope without pretending that the whole knowledge library is empty", async () => {
    const view = await renderPanel({ payloadMode: "structure" });
    expect(view.querySelector('[role="status"]')?.textContent).toContain("当前读取身份没有可见知识或私有记忆");
    expect(view.querySelector<HTMLElement>('[data-testid="mock-graph-canvas"]')?.dataset.nodeIds).toBe("project,agent");
    expect(view.textContent).not.toContain("当前范围还没有可显示的图谱");
  });

  it("starts without an inspector and opens, closes, and reopens selected-node reading", async () => {
    const view = await renderPanel();
    expect(view.querySelector('[data-vui-region="memory-graph-inspector"]')).toBeNull();
    expect(graphPayload.operatingBoundary.fullContentIncluded).toBe(false);
    expect(graphPayload.nodes[0].contentItems[0].content).toBeUndefined();

    await click(view.querySelector('[data-testid="canvas-node-alpha"]'));
    expect(view.querySelector('[data-vui-region="memory-graph-inspector"]')?.textContent).toContain("Alpha");
    expect(view.textContent).toContain("完整正文仅在选中后读取");

    await click(view.querySelector('button[aria-label="关闭详情"]'));
    expect(view.querySelector('[data-vui-region="memory-graph-inspector"]')).toBeNull();
    await click(Array.from(view.querySelectorAll("button")).find(button => button.textContent?.includes("查看详情")) ?? null);
    expect(view.querySelector('[data-vui-region="memory-graph-inspector"]')?.textContent).toContain("Alpha");
  });

  it("keeps adjacent nodes in search context and lets the user show matches only", async () => {
    const view = await renderPanel();
    await enterSearch("Alpha");

    const canvas = view.querySelector<HTMLElement>('[data-testid="mock-graph-canvas"]');
    expect(canvas?.dataset.nodeIds).toBe("alpha,beta");
    expect(view.querySelector<HTMLElement>('[data-testid="canvas-edges"]')?.dataset.edgeIds).toBe("alpha-beta");

    await click(Array.from(view.querySelectorAll("button")).find(button => button.textContent?.includes("仅看匹配项")) ?? null);
    expect(view.querySelector<HTMLElement>('[data-testid="mock-graph-canvas"]')?.dataset.nodeIds).toBe("alpha");
    expect(view.querySelector<HTMLElement>('[data-testid="canvas-edges"]')?.dataset.edgeIds).toBe("");
    await click(Array.from(view.querySelectorAll("button")).find(button => button.textContent?.includes("恢复关联上下文")) ?? null);
    expect(view.querySelector<HTMLElement>('[data-testid="mock-graph-canvas"]')?.dataset.nodeIds).toBe("alpha,beta");
  });

  it("opens and closes a relation inspector when an edge is selected before any node", async () => {
    const view = await renderPanel();
    expect(view.querySelector('[data-vui-region="memory-graph-inspector"]')).toBeNull();

    await click(view.querySelector('[data-testid="canvas-edge-alpha-beta"]'));

    const inspector = view.querySelector('[data-vui-region="memory-graph-inspector"]');
    expect(inspector?.querySelector('[aria-label="关系与依据"]')).not.toBeNull();
    expect(inspector?.textContent).toContain("提及");
    expect(inspector?.textContent).toContain("起点 · Alpha");
    expect(inspector?.textContent).toContain("终点 · Beta");

    await click(view.querySelector('button[aria-label="关闭详情"]'));
    expect(view.querySelector('[data-vui-region="memory-graph-inspector"]')).toBeNull();
  });

  it("distinguishes loading, an empty graph, initial failure, and stale data after refresh failure", async () => {
    let retryCount = 0;
    const loadingView = await renderPanel({ payloadMode: "none", graphLoading: true });
    expect(loadingView.querySelector('[role="status"]')?.textContent).toContain("正在加载图谱");
    expect(loadingView.textContent).not.toContain("当前范围还没有可显示的图谱");

    await act(async () => root?.unmount());
    root = null;
    loadingView.remove();
    host = null;

    const emptyView = await renderPanel({ payloadMode: "empty" });
    expect(emptyView.querySelector('[role="status"]')?.textContent).toContain("当前范围还没有可显示的图谱");
    expect(emptyView.querySelector('[role="alert"]')).toBeNull();

    await act(async () => root?.unmount());
    root = null;
    emptyView.remove();
    host = null;

    const failedView = await renderPanel({ payloadMode: "none", graphError: "network unavailable", onRetry: () => { retryCount += 1; } });
    expect(failedView.querySelector('[role="alert"]')?.textContent).toContain("network unavailable");
    await click(Array.from(failedView.querySelectorAll("button")).find(button => button.textContent?.includes("重试")) ?? null);
    expect(retryCount).toBe(1);

    await act(async () => root?.unmount());
    root = null;
    failedView.remove();
    host = null;

    const staleView = await renderPanel({ graphError: "refresh timed out", onRetry: () => { retryCount += 1; } });
    expect(staleView.querySelector('[role="alert"]')?.textContent).toContain("刷新失败，当前显示上次加载的图谱");
    expect(staleView.querySelector('[data-testid="mock-graph-canvas"]')?.dataset.nodeIds).toBe("alpha,beta,gamma");
    await click(Array.from(staleView.querySelectorAll("button")).find(button => button.textContent?.includes("重试")) ?? null);
    expect(retryCount).toBe(2);
  });
});
