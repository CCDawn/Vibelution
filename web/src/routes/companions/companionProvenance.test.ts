import { describe, expect, it } from "vitest";

import { companionProvenanceLabel } from "./companionProvenance";

describe("companionProvenanceLabel", () => {
  it("only labels schedule simulations isolated when recall exclusion is confirmed", () => {
    expect(companionProvenanceLabel("simulation", "zh", true)).toBe("日程模拟（已隔离）");
    expect(companionProvenanceLabel("simulation", "zh", false)).toBe("日程模拟");
    expect(companionProvenanceLabel("simulation", "zh")).toBe("日程模拟");
  });

  it("uses the same verified, reported, and unknown labels in English and Chinese", () => {
    expect(companionProvenanceLabel("verified_action", "zh")).toBe("工具行动（有回执）");
    expect(companionProvenanceLabel("verified_action", "en")).toBe("Tool action (receipt recorded)");
    expect(companionProvenanceLabel("character_report", "zh")).toBe("人物自述");
    expect(companionProvenanceLabel("character_report", "en")).toBe("Character report");
    expect(companionProvenanceLabel(undefined, "zh")).toBe("来源未核实");
    expect(companionProvenanceLabel("unrecognized", "en")).toBe("Unverified source");
  });
});
