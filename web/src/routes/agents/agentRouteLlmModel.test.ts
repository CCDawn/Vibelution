import { describe, expect, it } from "vitest";

import type { AgentLlmBindings, AgentModelChoice } from "../../api/types";
import {
  agentModelById,
  normalizeAgentLlmBindings,
  normalizeAgentReasoningEffort,
  pruneAgentReasoningEffortBySlot,
  sameAgentLlmBindings,
  updateAgentLlmSlotBinding,
} from "./agentRouteLlmModel";

describe("agentRouteLlmModel", () => {
  it("normalizes bindings and compares slots", () => {
    const left = normalizeAgentLlmBindings({
      dialogue: { modelId: " m1 " },
      mentalModel: { modelId: "" },
    } as AgentLlmBindings);
    expect(left).toEqual({ dialogue: { modelId: "m1" } });
    expect(sameAgentLlmBindings(left, { dialogue: { modelId: "m1" } })).toBe(true);
    expect(sameAgentLlmBindings(left, { dialogue: { modelId: "m2" } })).toBe(false);
  });

  it("updates slot bindings and prunes unsupported reasoning effort", () => {
    const next = updateAgentLlmSlotBinding({}, { slot: "dialogue", label: "d", description: "", required: true, requiresImageInput: false }, "gpt");
    expect(next.dialogue?.modelId).toBe("gpt");
    const cleared = updateAgentLlmSlotBinding(next, { slot: "dialogue", label: "d", description: "", required: true, requiresImageInput: false }, "");
    expect(cleared.dialogue).toBeUndefined();

    const models = [{
      modelId: "gpt",
      reasoningEffortValues: ["low", "high"],
      supportsReasoningEffort: true,
    }] as AgentModelChoice[];
    const pruned = pruneAgentReasoningEffortBySlot(
      { dialogue: "medium", vision: "high" },
      { dialogue: { modelId: "gpt" } },
      models,
    );
    // unsupported effort values are dropped (empty after normalize → filtered out)
    expect(pruned.dialogue).toBeUndefined();
    expect(pruned.vision).toBeUndefined();
    expect(pruneAgentReasoningEffortBySlot(
      { dialogue: "high" },
      { dialogue: { modelId: "gpt" } },
      models,
    )).toEqual({ dialogue: "high" });
    expect(normalizeAgentReasoningEffort("high", ["low", "high"])).toBe("high");
    expect(agentModelById(models, "gpt")?.modelId).toBe("gpt");
  });
});
