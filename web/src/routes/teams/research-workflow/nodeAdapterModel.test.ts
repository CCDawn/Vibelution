import { describe, expect, it } from "vitest";

import { CHALLENGE_CUP_NODE_IDS } from "../../../api/types/researchWorkflow";
import {
  adaptersForStage,
  getNodeAdapter,
  listNodeAdapters,
} from "./nodeAdapterModel";

describe("nodeAdapterModel", () => {
  it("covers all fifteen fixed nodes exactly once", () => {
    const adapters = listNodeAdapters();
    expect(adapters).toHaveLength(15);
    expect(adapters.map((a) => a.nodeId).sort()).toEqual([...CHALLENGE_CUP_NODE_IDS].sort());
  });

  it("maps knowledge handoff to human gate slot", () => {
    const adapter = getNodeAdapter("knowledge_handoff");
    expect(adapter?.actorKind).toBe("human");
    expect(adapter?.slot).toBe("human_gate");
    expect(adapter?.commands).toContain("accept_handoff");
  });

  it("maps controlled_run to system slot not agent chat", () => {
    const adapter = getNodeAdapter("controlled_run");
    expect(adapter?.actorKind).toBe("system");
    expect(adapter?.slot).toBe("system_run");
    expect(adapter?.commands).not.toContain("open_session");
  });

  it("groups three stages", () => {
    expect(adaptersForStage("knowledge_collection")).toHaveLength(5);
    expect(adaptersForStage("experiment_design")).toHaveLength(5);
    expect(adaptersForStage("execution_iteration")).toHaveLength(5);
  });

  it("does not invent adapters for unknown nodes", () => {
    expect(getNodeAdapter("not_a_node")).toBeNull();
    expect(getNodeAdapter(null)).toBeNull();
  });
});
