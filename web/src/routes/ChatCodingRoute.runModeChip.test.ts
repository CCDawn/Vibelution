import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeCssSource = readFileSync(new URL("./ChatCodingRoute.legacy.css", import.meta.url), "utf-8");

function cssRuleBody(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = routeCssSource.match(new RegExp(`(?:^|\\n)[^\\n{]*${escaped}\\s*\\{([\\s\\S]*?)\\n\\}`, "m"));
  return match?.[1] ?? "";
}

describe("ChatCodingRoute run mode chip visual contract", () => {
  it("keeps persistent enabled state on the dot instead of filling the whole chip", () => {
    const activeChip = cssRuleBody(".featureChipActive");
    const primaryActiveChip = cssRuleBody(".featureChipPrimary.featureChipActive");
    const baseDot = cssRuleBody(".featureChip::before");
    const activeDot = cssRuleBody(".featureChipActive::before");
    const primaryActiveDot = cssRuleBody(".featureChipPrimary.featureChipActive::before");

    expect(activeChip).toContain("border-color:");
    expect(activeChip).toContain("color: var(--fg-primary)");
    expect(activeChip).not.toContain("background:");
    expect(primaryActiveChip).toContain("border-color:");
    expect(primaryActiveChip).not.toContain("background:");
    expect(baseDot).toContain("content: \"\"");
    expect(baseDot).toContain("width: 6px");
    expect(activeDot).toContain("background: var(--accent-cool)");
    expect(primaryActiveDot).toContain("background: var(--accent-warm-2)");
  });

  it("does not collapse VButton slot spans inside run mode chips", () => {
    const contentSlot = cssRuleBody('.featureChip [data-slot="vui-button-content"]');
    const labelSlot = cssRuleBody('.featureChip [data-slot="vui-button-label"]');
    const chipLabel = cssRuleBody(".featureChip strong");
    const broadSpanRule = cssRuleBody(".featureChip span");

    expect(broadSpanRule).toBe("");
    expect(contentSlot).toContain("min-width: 0");
    expect(contentSlot).toContain("max-width: 100%");
    expect(labelSlot).toContain("min-width: 0");
    expect(labelSlot).toContain("overflow: hidden");
    expect(chipLabel).toContain("white-space: nowrap");
    expect(chipLabel).toContain("text-overflow: ellipsis");
    expect(chipLabel).not.toContain("overflow-wrap: anywhere");
  });
});
