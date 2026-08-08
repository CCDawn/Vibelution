import { describe, expect, it } from "vitest";

import { CHALLENGE_CUP_NODE_IDS } from "../../../api/types/researchWorkflow";
import {
  adaptersForStage,
  getNodeAdapter,
  listNodeAdapters,
  WIRED_COMMANDS,
} from "./nodeAdapterModel";

describe("nodeAdapterModel", () => {
  it("covers all fifteen fixed nodes exactly once", () => {
    const adapters = listNodeAdapters();
    expect(adapters).toHaveLength(15);
    expect(adapters.map((a) => a.nodeId).sort()).toEqual([...CHALLENGE_CUP_NODE_IDS].sort());
  });

  it("wires exactly the commands with a live handler (human-gate actions)", () => {
    // The inspector renders only wired commands; every wired command must be
    // handled by the workspace onInspectorCommand. Adding a command here
    // without a handler recreates the fake-button error path.
    expect(WIRED_COMMANDS).toEqual(["accept_handoff", "reject_handoff", "revise"]);
    for (const command of WIRED_COMMANDS) {
      expect(
        listNodeAdapters().some((a) => a.commands.includes(command)),
        `wired command ${command} is declared by at least one adapter`,
      ).toBe(true);
    }
  });

  it("declares only wired commands, the session link slot, or known roadmap commands", () => {
    // Adapters keep their target-state declarations (roadmap); the inspector
    // filters to WIRED_COMMANDS + open_session at render time. Every declared
    // command must be explicitly classified so no command can surface as an
    // unwired button.
    const ROADMAP_COMMANDS = [
      "start_agent_task",
      "open_evidence_graph",
      "run_smoke",
      "start_controlled_run",
      "view_artifacts",
      "build_package",
    ];
    const declared = listNodeAdapters().flatMap((a) => a.commands);
    for (const command of declared) {
      expect(
        (WIRED_COMMANDS as readonly string[]).includes(command) ||
          command === "open_session" ||
          ROADMAP_COMMANDS.includes(command),
        `command ${command} is wired, the session link slot, or a known roadmap command`,
      ).toBe(true);
    }
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
