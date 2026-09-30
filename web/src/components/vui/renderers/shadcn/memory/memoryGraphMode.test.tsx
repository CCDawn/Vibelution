/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { MemoryKnowledgeGraphNode } from "../../../../../api/types";
import { ShadcnMemoryGraphCanvas } from "./ShadcnMemoryGraphCanvas";
import { createMemoryGraphEngine } from "./MemoryGraphEngine";

vi.mock("./MemoryGraphEngine", () => ({
  createMemoryGraphEngine: vi.fn(() => ({ updateSelection: vi.fn(), updateHighlights: vi.fn(),
    updateFlat: vi.fn(), refreshTheme: vi.fn(), updateLabels: vi.fn(), focus: vi.fn(), dispose: vi.fn() })),
}));
vi.mock("three", () => ({}));
vi.mock("three/addons/controls/OrbitControls.js", () => ({ OrbitControls: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("preserves the engine on selection and restores spatial coordinates after a real flat projection", async () => {
  const nodes: MemoryKnowledgeGraphNode[] = Array.from({ length: 8 }, (_, i) => ({
    id: String(i), type: "concept", label: String(i), summary: "", status: "active",
    createdAt: "", updatedAt: "", metadata: {}, responsibilityQuestion: "", visual: {}, childNodeIds: [], contentItems: [],
  }));
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  const edges: [] = [];
  const render = async (flat: boolean, selectedNodeId = "") => {
    await act(async () => { root.render(<ShadcnMemoryGraphCanvas nodes={nodes} edges={edges}
      selectedNodeId={selectedNodeId} onSelectNode={() => {}} fallbackText="fallback" flat={flat} />); });
    await vi.waitFor(() => expect(host.querySelector('[data-webgl="ready"]')).not.toBeNull());
  };
  const create = vi.mocked(createMemoryGraphEngine);
  try {
    await render(false);
    const spatial = create.mock.calls[0][0].nodes.map(n => [n.x, n.y, n.z]);
    expect(new Set(spatial.map(p => p[2])).size).toBeGreaterThan(3);
    const first = create.mock.results[0].value!;
    await render(false, "1");
    expect(create).toHaveBeenCalledTimes(1);
    expect(first.updateSelection).toHaveBeenCalledWith("1");
    await render(true, "1");
    expect(first.dispose).toHaveBeenCalledOnce();
    expect(create.mock.calls[1][0].nodes.every(n => n.z === 0)).toBe(true);
    expect(create.mock.calls[1][0].clusters.every(c => c.center.z === 0)).toBe(true);
    await render(false, "1");
    expect(create.mock.calls[2][0].nodes.map(n => [n.x, n.y, n.z])).toEqual(spatial);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
