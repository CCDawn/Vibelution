import { describe, expect, it } from "vitest";

import {
  WORKFLOW_MANUAL_LAYOUT_GRID,
  persistWorkflowManualLayout,
  readWorkflowManualLayout,
  resolveWorkflowManualEdgeGeometry,
  snapWorkflowManualPosition,
  workflowManualLayoutStorageKey,
  type WorkflowManualLayoutScope,
} from "./workflowManualLayout";

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => void values.set(key, value),
    removeItem: (key) => void values.delete(key),
    clear: () => values.clear(),
    key: (index) => [...values.keys()][index] ?? null,
    get length() { return values.size; },
  };
}

const scope: WorkflowManualLayoutScope = {
  structureKey: "graph:challenge-cup",
  runId: "run-42",
  nodeIds: ["collect", "design"],
};

describe("workflowManualLayout", () => {
  it("snaps visual positions to the 16px grid", () => {
    expect(snapWorkflowManualPosition({ x: 39, y: 57 })).toEqual({ x: 32, y: 64 });
    expect(WORKFLOW_MANUAL_LAYOUT_GRID).toBe(16);
  });

  it("persists only a matching structure/run and ignores malformed storage", () => {
    const storage = memoryStorage();
    persistWorkflowManualLayout(scope, { positions: { collect: { x: 41, y: 71 } }, locked: true }, storage);
    expect(readWorkflowManualLayout(scope, storage)).toEqual({
      positions: { collect: { x: 48, y: 64 } },
      locked: true,
    });

    storage.setItem(workflowManualLayoutStorageKey(scope), "{invalid");
    expect(readWorkflowManualLayout(scope, storage)).toEqual({ positions: {}, locked: false });
  });

  it("does not reuse a saved arrangement after the graph node set changes", () => {
    const storage = memoryStorage();
    persistWorkflowManualLayout(scope, { positions: { collect: { x: 32, y: 64 } }, locked: false }, storage);
    expect(readWorkflowManualLayout({ ...scope, nodeIds: ["collect", "review"] }, storage)).toEqual({
      positions: {},
      locked: false,
    });
  });

  it("uses a deterministic orthogonal live edge with a midpoint label anchor", () => {
    expect(resolveWorkflowManualEdgeGeometry({ x: 0, y: 0 }, { x: 120, y: 40 })).toEqual({
      path: "M 0 0 L 60 0 L 60 40 L 120 40",
      labelAnchor: { x: 60, y: 20 },
    });
    expect(resolveWorkflowManualEdgeGeometry({ x: 0, y: 0 }, { x: 40, y: 120 })).toEqual({
      path: "M 0 0 L 0 60 L 40 60 L 40 120",
      labelAnchor: { x: 20, y: 60 },
    });
  });
});
