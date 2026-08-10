import { describe, expect, it } from "vitest";

import type { NodeHandoffRecord, WorkflowDefinition } from "../../../api/types/researchWorkflow";
import { buildResearchCriticalPath } from "./researchCriticalPathModel";

describe("buildResearchCriticalPath", () => {
  it("follows accepted handoffs to the current runtime node", () => {
    const definition = {
      nodes: [
        { nodeId: "source_finding", label: "资料寻找" },
        { nodeId: "source_extraction", label: "资料提炼" },
        { nodeId: "evidence_relations", label: "证据关系" },
      ],
    } as unknown as WorkflowDefinition;
    const handoffs = [
      { handoffId: "h1", fromNodeId: "source_finding", toNodeId: "source_extraction", status: "accepted" },
      { handoffId: "h2", fromNodeId: "source_extraction", toNodeId: "evidence_relations", status: "accepted" },
    ] as NodeHandoffRecord[];

    expect(buildResearchCriticalPath(definition, handoffs, ["evidence_relations"])).toEqual([
      { nodeId: "source_finding", label: "资料寻找" },
      { nodeId: "source_extraction", label: "资料提炼" },
      { nodeId: "evidence_relations", label: "证据关系" },
    ]);
  });
});
