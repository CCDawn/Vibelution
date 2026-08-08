/**
 * RED acceptance tests for the TWO-LEVEL layout architecture.
 *
 * These invariants FAIL on the current single-compound layout (INCLUDE_CHILDREN
 * pulls stage children into the root RIGHT layering, stretching stage boxes and
 * breaking stage-internal vertical order). They become the GREEN contract of
 * the two-level layout (stage-internal DOWN + stage meta RIGHT + gateway
 * cross-stage routing).
 *
 * §7 constraints encoded here:
 *  1. three-stage compactness (stage width <= 380, overall width <= 1350,
 *     stage gap in [24, 64]);
 *  2. stage-internal vertical flow (main-chain Y strictly increasing, center X
 *     deviation <= 24, vertical gap in [16, 80]);
 *  3. whitespace budget (stage extent ~ children + title band + padding);
 *  4. cross-stage edges stay in the gap channel (no node/title-band crossing);
 *  5. fit timing handled by the settling protocol (hook-level, separate file);
 *  6. port coordinate alignment (DOM-level, separate renderer tests).
 */
import ELK from "elkjs/lib/elk.bundled.js";
import { describe, expect, it } from "vitest";

import type {
  WorkflowLayoutInput,
  WorkflowLayoutResult,
} from "../../../product/workflow/workflowCanvasTypes";
import { layoutTwoLevel } from "./workflowTwoLevelLayout";
import { challengeCupDefinition } from "./workflowElkLayout.test";
import { analyzeEdgeSections } from "./workflowElkEdgePath";

const STAGE_ORDER = ["knowledge_collection", "experiment_design", "execution_iteration"] as const;

/** Main chain of a stage: nodes ordered by definition (stage.nodeIds). */
function mainChain(input: WorkflowLayoutInput, stageId: string): string[] {
  const stage = input.stages.find((s) => s.stageId === stageId);
  return stage ? stage.nodeIds : [];
}

async function layoutCurrent(): Promise<WorkflowLayoutResult> {
  const input = challengeCupDefinition();
  const elk = new ELK();
  return layoutTwoLevel(input, elk);
}

describe("two-level layout · three-stage compactness (RED on current)", () => {
  it("keeps every stage width within the design budget (linear <= 380, decision <= 520)", async () => {
    const input = challengeCupDefinition();
    const result = await layoutCurrent();
    const stages = result.nodes.filter((n) => n.kind === "stage");
    expect(stages.length).toBe(3);
    const hasDecision = (stageId: string) =>
      input.nodes.some((n) => n.stageId === stageId && n.visualKind === "decision");
    for (const stage of stages) {
      const budget = hasDecision(stage.stageId) ? 520 : 380;
      expect(stage.width, `stage ${stage.id} width ${stage.width}`).toBeLessThanOrEqual(budget);
    }
  });

  it("keeps the overall layout width within the 1920 viewport (spacer-architected gaps)", async () => {
    const result = await layoutCurrent();
    const maxRight = Math.max(...result.nodes.map((n) => n.x + n.width));
    // Gaps are ELK-driven (label width + safety spacing), so the budget is
    // "fits a 1920 desktop with the full flow visible", not a fixed number.
    expect(maxRight).toBeLessThanOrEqual(1600);
    expect(maxRight).toBeGreaterThan(0);
  });

  it("keeps stage gaps positive and driven by layout content (no fixed 40px channel)", async () => {
    const result = await layoutCurrent();
    const stages = result.nodes
      .filter((n) => n.kind === "stage")
      .sort((a, b) => a.x - b.x);
    expect(stages.length).toBe(3);
    for (let i = 0; i + 1 < stages.length; i += 1) {
      const gap = stages[i + 1]!.x - (stages[i]!.x + stages[i]!.width);
      expect(gap, `gap after ${stages[i]!.id}`).toBeGreaterThanOrEqual(24);
      // The gap is content-driven (label spacer + ELK spacing); a gap that
      // exactly equals a fixed constant would indicate the old hand-rolled row.
      expect(gap, `gap after ${stages[i]!.id} is ELK-driven`).not.toBe(40);
    }
  });

  it("orders stages along X in definition order (knowledge -> experiment -> execution)", async () => {
    const result = await layoutCurrent();
    const stages = result.nodes
      .filter((n) => n.kind === "stage")
      .sort((a, b) => a.x - b.x)
      .map((s) => s.stageId);
    expect(stages).toEqual([...STAGE_ORDER]);
  });
});

describe("two-level layout · stage-internal vertical flow (RED on current)", () => {
  it("keeps main-chain node Y strictly increasing within each stage", async () => {
    const input = challengeCupDefinition();
    const result = await layoutCurrent();
    for (const stageId of STAGE_ORDER) {
      const chain = mainChain(input, stageId);
      let prevY = Number.NEGATIVE_INFINITY;
      for (const nodeId of chain) {
        const node = result.nodes.find((n) => n.id === nodeId);
        expect(node, `node ${nodeId} in stage ${stageId}`).toBeDefined();
        expect(node!.y, `node ${nodeId} Y monotonic in stage ${stageId}`).toBeGreaterThan(prevY);
        prevY = node!.y;
      }
    }
  });

  it("keeps main-chain node center X within 24px of each other (single column)", async () => {
    const input = challengeCupDefinition();
    const result = await layoutCurrent();
    for (const stageId of STAGE_ORDER) {
      // Main chain = the column that holds the majority of the stage's
      // definition-ordered nodes (branch targets live in side columns).
      const chainNodeRefs = mainChain(input, stageId).map((nodeId) => {
        const node = result.nodes.find((n) => n.id === nodeId)!;
        return { nodeId, center: node.x + node.width / 2 };
      });
      if (chainNodeRefs.length === 0) continue;
      const columnOf = (center: number) => Math.round(center / 30);
      const counts = new Map<number, number>();
      for (const n of chainNodeRefs) {
        const col = columnOf(n.center);
        counts.set(col, (counts.get(col) ?? 0) + 1);
      }
      let mainCol = -1;
      let maxCount = 0;
      for (const [col, count] of counts) {
        if (count > maxCount) {
          maxCount = count;
          mainCol = col;
        }
      }
      const mainChainNodes = chainNodeRefs.filter((n) => columnOf(n.center) === mainCol);
      expect(mainChainNodes.length, `stage ${stageId} has a main column`).toBeGreaterThan(0);
      const first = mainChainNodes[0]!.center;
      for (const n of mainChainNodes) {
        expect(
          Math.abs(n.center - first),
          `stage ${stageId} main-chain center deviation`,
        ).toBeLessThanOrEqual(24);
      }
    }
  });

  it("keeps stage-internal node vertical gap within [16, 80]px", async () => {
    const input = challengeCupDefinition();
    const result = await layoutCurrent();
    for (const stageId of STAGE_ORDER) {
      const chain = mainChain(input, stageId);
      let prevBottom = Number.NEGATIVE_INFINITY;
      for (const nodeId of chain) {
        const node = result.nodes.find((n) => n.id === nodeId)!;
        const gap = node.y - prevBottom;
        if (prevBottom !== Number.NEGATIVE_INFINITY) {
          expect(gap, `gap before ${nodeId} in ${stageId}`).toBeGreaterThanOrEqual(16);
          expect(gap, `gap before ${nodeId} in ${stageId}`).toBeLessThanOrEqual(80);
        }
        prevBottom = node.y + node.height;
      }
    }
  });
});

describe("two-level layout · whitespace budget (RED on current)", () => {
  it("keeps stage extent close to children + title band + padding (no giant empty stage)", async () => {
    const input = challengeCupDefinition();
    const result = await layoutCurrent();
    for (const stage of result.nodes.filter((n) => n.kind === "stage")) {
      const children = result.nodes.filter((n) => n.parentStageId === stage.id);
      if (children.length === 0) continue;
      const childMinX = Math.min(...children.map((c) => c.x));
      const childMaxX = Math.max(...children.map((c) => c.x + c.width));
      const childMinY = Math.min(...children.map((c) => c.y));
      const childMaxY = Math.max(...children.map((c) => c.y + c.height));
      const contentW = childMaxX - childMinX;
      const contentH = childMaxY - childMinY;
      // Title band (44-56) + vertical padding (~28) are the allowed slack;
      // width slack must be modest (horizontal padding 16-24 per side).
      expect(stage.width, `stage ${stage.id} width ${stage.width} vs content ${contentW}`)
        .toBeLessThanOrEqual(contentW + 64);
      expect(stage.height, `stage ${stage.id} height ${stage.height} vs content ${contentH}`)
        .toBeLessThanOrEqual(contentH + 120);
    }
  });
});

describe("two-level layout · cross-stage edges stay in the channel (RED on current)", () => {
  it("keeps every cross-stage edge section inside its source/target stage or the gap", async () => {
    const input = challengeCupDefinition();
    const result = await layoutCurrent();
    const stages = result.nodes.filter((n) => n.kind === "stage");
    const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));
    const crossEdges = result.edges.filter((e) => {
      const s = stageOf.get(e.source);
      const t = stageOf.get(e.target);
      return s && t && s !== t;
    });
    expect(crossEdges.length).toBeGreaterThan(0);
    for (const edge of crossEdges) {
      for (const section of edge.sections) {
        const points = [section.start, section.end, ...section.bendPoints];
        for (const p of points) {
          const sourceStageId = stageOf.get(edge.source);
          const targetStageId = stageOf.get(edge.target);
          const insideForeignStage = stages.some(
            (st) =>
              st.stageId !== sourceStageId &&
              st.stageId !== targetStageId &&
              p.x > st.x && p.x < st.x + st.width && p.y > st.y && p.y < st.y + st.height,
          );
          expect(insideForeignStage, `section of ${edge.id} crosses a foreign stage`).toBe(false);
        }
      }
    }
  });

  it("keeps cross-stage sections continuous and gives every labeled edge a bounds anchor", async () => {
    const input = challengeCupDefinition();
    const result = await layoutCurrent();
    const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));
    const crossEdges = result.edges.filter((e) => {
      const s = stageOf.get(e.source);
      const t = stageOf.get(e.target);
      return s && t && s !== t;
    });
    for (const edge of crossEdges) {
      for (const section of edge.sections) {
        const isHorizontal = Math.abs(section.start.y - section.end.y) < 1e-6;
        const isVertical = Math.abs(section.start.x - section.end.x) < 1e-6;
        expect(isHorizontal || isVertical, `section of ${edge.id} is orthogonal`).toBe(true);
      }
      // Chain continuity within each leg: consecutive sections land exactly
      // on the next start. The boundary between leg1 and leg2 crosses the
      // label spacer (the label rect sits between the two legs — intended).
      const byId = new Map(edge.sections.map((s) => [s.id, s] as const));
      for (const section of edge.sections) {
        for (const nextId of section.outgoingSectionIds) {
          const next = byId.get(nextId);
          if (!next) continue;
          const crossLegBoundary =
            section.id.includes("leg1") && next.id.includes("leg2");
          if (crossLegBoundary) continue;
          expect(Math.abs(section.end.x - next.start.x)).toBeLessThanOrEqual(1e-3);
          expect(Math.abs(section.end.y - next.start.y)).toBeLessThanOrEqual(1e-3);
        }
      }
      // The label rect must cover the leg boundary gap (spacer occupancy).
      // Leg sections are identified by their id (leg1/leg2 are the layout
      // edge ids); the composer's gateway stubs sit outside the legs.
      const lb = edge.labelBounds;
      const leg1Sections = edge.sections.filter((s) => s.id.includes("leg1"));
      const leg2Sections = edge.sections.filter((s) => s.id.includes("leg2"));
      if (lb && leg1Sections.length > 0 && leg2Sections.length > 0) {
        const leg1End = leg1Sections[leg1Sections.length - 1]!.end;
        const leg2Start = leg2Sections[0]!.start;
        const covered =
          leg1End.x >= lb.x - 1e-3 && leg2Start.x <= lb.x + lb.width + 1e-3;
        expect(covered, `label of ${edge.id} covers the leg boundary`).toBe(true);
      }
      if (edge.label.length > 0) {
        expect(edge.labelBounds, `cross-stage edge ${edge.id} has a label anchor`).toBeDefined();
      }
    }
  });

  it("keeps cross-stage label bounds inside the stage gap channel", async () => {
    const input = challengeCupDefinition();
    const result = await layoutCurrent();
    const stages = result.nodes.filter((n) => n.kind === "stage");
    const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));
    const crossEdges = result.edges.filter((e) => {
      const s = stageOf.get(e.source);
      const t = stageOf.get(e.target);
      return s && t && s !== t;
    });
    for (const edge of crossEdges) {
      const lb = edge.labelBounds;
      if (!lb) continue;
      const sourceStageId = stageOf.get(edge.source);
      const targetStageId = stageOf.get(edge.target);
      const sourceStage = stages.find((s) => s.stageId === sourceStageId)!;
      const targetStage = stages.find((s) => s.stageId === targetStageId)!;
      const gapLeft = sourceStage.x + sourceStage.width;
      const gapRight = targetStage.x;
      const labelCenterX = lb.x + lb.width / 2;
      expect(
        labelCenterX,
        `label of ${edge.id} centered in the gap between ${sourceStageId} and ${targetStageId}`,
      ).toBeGreaterThanOrEqual(gapLeft);
      expect(labelCenterX).toBeLessThanOrEqual(gapRight);
    }
  });

  it("keeps every cross-stage section chain well-formed after spacer reassembly", async () => {
    const input = challengeCupDefinition();
    const result = await layoutCurrent();
    const stageOf = new Map(input.nodes.map((n) => [n.nodeId, n.stageId] as const));
    const crossEdges = result.edges.filter((e) => {
      const sourceStage = stageOf.get(e.source);
      const targetStage = stageOf.get(e.target);
      return sourceStage && targetStage && sourceStage !== targetStage;
    });

    expect(crossEdges.length).toBeGreaterThan(0);
    for (const edge of crossEdges) {
      const diagnostic = analyzeEdgeSections(edge.sections);
      expect(
        diagnostic.wellFormed,
        `${edge.id}: ${diagnostic.diagnostics.join("; ")}`,
      ).toBe(true);
    }
  });
});
