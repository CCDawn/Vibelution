/**
 * Definition-sync contract: the frontend's hand-listed node ids must equal the
 * server's pinned definition snapshots. Reads the versioned JSON snapshots in
 * core/research/workflow/definitions/ directly so hand-copied drift fails CI
 * instead of silently diverging at runtime.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  CHALLENGE_CUP_NODE_IDS,
  KNOWLEDGE_SIDEFLOW_NODE_IDS,
} from "./researchWorkflow";

const definitionsDir = resolve(
  import.meta.dirname,
  "../../../../core/research/workflow/definitions",
);

type DefinitionSnapshot = {
  workflowId: string;
  schemaVersion: string;
  definition: {
    nodes: Array<{ nodeId: string }>;
    stages: Array<{ stageId: string; nodeIds: string[] }>;
  };
};

function readSnapshot(fileName: string): DefinitionSnapshot {
  return JSON.parse(
    readFileSync(resolve(definitionsDir, fileName), "utf-8"),
  ) as DefinitionSnapshot;
}

describe("frontend node id lists mirror the server definition snapshots", () => {
  it("CHALLENGE_CUP_NODE_IDS equals the pinned 2.1.0 main definition", () => {
    const snapshot = readSnapshot("challenge-cup-research@2.1.0.json");
    expect(snapshot.schemaVersion).toBe("2.1.0");
    const serverNodeIds = snapshot.definition.nodes.map((node) => node.nodeId);
    expect([...CHALLENGE_CUP_NODE_IDS]).toEqual(serverNodeIds);
    // Stage membership must not reference nodes outside the canonical list.
    const known = new Set<string>(CHALLENGE_CUP_NODE_IDS);
    for (const stage of snapshot.definition.stages) {
      for (const nodeId of stage.nodeIds) {
        expect(known.has(nodeId), `stage ${stage.stageId} references ${nodeId}`).toBe(true);
      }
    }
  });

  it("KNOWLEDGE_SIDEFLOW_NODE_IDS equals the pinned sideflow definition", () => {
    const snapshot = readSnapshot("challenge-cup-knowledge-sideflow@1.0.0.json");
    expect(snapshot.workflowId).toBe("challenge-cup-knowledge-sideflow");
    expect(snapshot.schemaVersion).toBe("1.0.0");
    const serverNodeIds = snapshot.definition.nodes.map((node) => node.nodeId);
    expect([...KNOWLEDGE_SIDEFLOW_NODE_IDS]).toEqual(serverNodeIds);
  });

  it("the 3.0.0 main definition carries no in-graph knowledge nodes", () => {
    const snapshot = readSnapshot("challenge-cup-research@3.0.0.json");
    const serverNodeIds = snapshot.definition.nodes.map((node) => node.nodeId);
    expect(serverNodeIds).toHaveLength(12);
    for (const sideflowNode of KNOWLEDGE_SIDEFLOW_NODE_IDS) {
      expect(serverNodeIds).not.toContain(sideflowNode);
    }
    // The sideflow entry point is fed directly by problem understanding.
    expect(serverNodeIds[0]).toBe("problem_understanding");
    expect(serverNodeIds).toContain("hypothesis_design");
  });
});
