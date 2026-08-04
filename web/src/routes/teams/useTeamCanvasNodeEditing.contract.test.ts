import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeSource = readFileSync(new URL("../TeamsRoute.tsx", import.meta.url), "utf8");
const editingSource = readFileSync(new URL("./useTeamCanvasNodeEditing.ts", import.meta.url), "utf8");
const modelSource = readFileSync(new URL("./teamCanvasNodeModel.ts", import.meta.url), "utf8");

describe("team canvas node editing extraction", () => {
  it("TeamsRoute composes canvas node edits from factory + pure model", () => {
    expect(routeSource).toContain("createTeamCanvasNodeEditing");
    expect(routeSource).toContain("addNode,");
    expect(routeSource).toContain("finishNodeDrag,");
    expect(routeSource).not.toContain("function addNode()");
    expect(routeSource).not.toContain("function finishNodeDrag(");
    expect(routeSource).not.toContain("function applyNodeDraft()");
  });

  it("factory and model own node mutate + drag math", () => {
    expect(editingSource).toContain("export function createTeamCanvasNodeEditing");
    expect(editingSource).toContain("buildCanvasWithNewNode");
    expect(editingSource).toContain("buildCanvasWithDraggedNode");
    expect(modelSource).toContain("export function applyNodeDragDeltas");
    expect(modelSource).toContain("export function buildCanvasWithLeadConnection");
  });
});
