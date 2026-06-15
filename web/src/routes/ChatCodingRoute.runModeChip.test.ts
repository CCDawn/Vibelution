import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const routeCssSource = readFileSync(new URL("./ChatCodingRoute.module.css", import.meta.url), "utf-8");

function cssRuleBody(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = routeCssSource.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([\\s\\S]*?)\\n\\}`, "m"));
  return match?.[1] ?? "";
}

describe("ChatCodingRoute run mode chip visual contract", () => {
  it("keeps persistent enabled state on the dot instead of filling the whole chip", () => {
    const activeChip = cssRuleBody(".featureChipActive");
    const primaryActiveChip = cssRuleBody(".featureChipPrimary.featureChipActive");
    const activeDot = cssRuleBody(".featureChipActive span");
    const primaryActiveDot = cssRuleBody(".featureChipPrimary.featureChipActive span");

    expect(activeChip).toContain("border-color:");
    expect(activeChip).toContain("color: var(--fg-primary)");
    expect(activeChip).not.toContain("background:");
    expect(primaryActiveChip).toContain("border-color:");
    expect(primaryActiveChip).not.toContain("background:");
    expect(activeDot).toContain("background: var(--accent-cool)");
    expect(primaryActiveDot).toContain("background: var(--accent-warm-2)");
  });
});
