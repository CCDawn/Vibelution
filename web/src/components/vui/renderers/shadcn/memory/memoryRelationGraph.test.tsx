/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { MemoryKnowledgeGraphEdge, MemoryKnowledgeGraphNode } from "../../../../../api/types";
import { memoryRelationLabel, ShadcnMemoryRelationGraph } from "./ShadcnMemoryRelationGraph";
import type { VMemoryGraphCanvasProps } from "../../../product/memory/VMemoryGraphCanvas";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let resize: (width: number, height?: number) => void;
class GraphResizeObserver {
  constructor(callback: ResizeObserverCallback) {
    resize = (width, height = 600) => callback([{ contentRect: { width, height } } as ResizeObserverEntry], this as unknown as ResizeObserver);
  }
  observe() {}
  disconnect() {}
  unobserve() {}
}
afterEach(() => vi.unstubAllGlobals());
function node(id: string, type = "knowledge_item"): MemoryKnowledgeGraphNode {
  return { id, type, label: `中文节点${id}`, summary: "", status: "active", createdAt: "", updatedAt: "",
    metadata: {}, responsibilityQuestion: "", visual: {}, childNodeIds: [], contentItems: [] };
}
const edges: MemoryKnowledgeGraphEdge[] = [
  { id: "candidate", source: "a", target: "b", type: "supports", label: "supports", weight: 1, metadata: { status: "candidate" } },
  { id: "missing", source: "a", target: "hidden", type: "references", label: "引用", weight: 1, metadata: {} },
];
async function setup(props: Partial<VMemoryGraphCanvasProps> = {}) {
  vi.stubGlobal("ResizeObserver", GraphResizeObserver);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const onSelectNode = vi.fn();
  const onSelectEdge = vi.fn();
  const input = { nodes: [node("a"), node("b", "concept")], edges, selectedNodeId: "", selectedEdgeId: "candidate", fallbackText: "fallback", onSelectNode, onSelectEdge, ...props };
  await act(async () => root.render(<ShadcnMemoryRelationGraph {...input} />));
  return { host, onSelectNode, onSelectEdge, close: async () => { await act(async () => root.unmount()); host.remove(); } };
}

it("keeps Chinese predicates, candidate state, DTO direction and selection on the wide graph", async () => {
  const view = await setup();
  try {
    await act(async () => resize(900));
    expect(view.host.querySelector('[data-relation-layout="graph"]')).not.toBeNull();
    const relation = view.host.querySelector<HTMLButtonElement>('[data-relation-id="candidate"]')!;
    expect(relation.textContent).toContain("支持 · 待确认");
    expect(relation.getAttribute("aria-label")).toBe("中文节点a — 支持 → 中文节点b");
    expect(relation.getAttribute("aria-pressed")).toBe("true");
    expect(relation.dataset.renderer).toBe("shadcn");
    const path = view.host.querySelector('[data-relation-path="candidate"]')!;
    expect(path.getAttribute("stroke-dasharray")).toBe("5 5");
    expect(path.getAttribute("marker-end")).toContain("selected");
    expect(view.host.querySelector('[data-relation-id="missing"]')).toBeNull();
    await act(async () => relation.click());
    expect(view.onSelectEdge).toHaveBeenCalledWith("candidate");
    await act(async () => view.host.querySelector<HTMLButtonElement>('[data-node-id="b"]')!.click());
    expect(view.onSelectNode).toHaveBeenCalledWith("b");
  } finally { await view.close(); }
});

it("retains every node and relation as readable buttons below 660px and for more than 12 nodes", async () => {
  const view = await setup();
  try {
    await act(async () => resize(659));
    expect(view.host.querySelector('[data-relation-layout="list"]')).not.toBeNull();
    expect(view.host.querySelectorAll('[data-node-id]')).toHaveLength(2);
    expect(view.host.querySelector('[data-relation-id="candidate"]')?.textContent).toContain("中文节点a");
    await act(async () => resize(660));
    expect(view.host.querySelector('[data-relation-layout="graph"]')).not.toBeNull();
  } finally { await view.close(); }
  const dense = await setup({ nodes: Array.from({ length: 13 }, (_, i) => node(String(i))), edges: [] });
  try {
    await act(async () => resize(1200));
    expect(dense.host.querySelector('[data-relation-layout="list"]')).not.toBeNull();
    expect(dense.host.querySelectorAll('[data-node-id]')).toHaveLength(13);
    expect(dense.host.textContent).toContain("没有可见关系");
  } finally { await dense.close(); }
});

it("uses safe Chinese fallbacks and preserves empty and long-content states", async () => {
  expect(memoryRelationLabel({ ...edges[0], label: "经人工审核支持" })).toBe("经人工审核支持");
  expect(memoryRelationLabel({ ...edges[0], label: "", type: "unfamiliar" })).toBe("关联（unfamiliar）");
  const long = node("long"); long.label = "长标签".repeat(40);
  const view = await setup({ nodes: [long], edges: [] });
  try {
    await act(async () => resize(900));
    expect(view.host.querySelector('[data-relation-layout="list"]')).not.toBeNull();
    expect(view.host.querySelector('[data-node-id="long"]')?.textContent).toBe(long.label);
  } finally { await view.close(); }
  const empty = await setup({ nodes: [], edges: [] });
  try { expect(empty.host.textContent).toContain("当前范围没有可见节点"); }
  finally { await empty.close(); }
});
