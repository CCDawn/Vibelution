import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const shellSource = readFileSync(new URL("./useTeamsWorkbenchShellPhase.tsx", import.meta.url), "utf8");

describe("useTeamsWorkbenchShellPhase hook order", () => {
  it("declares every React hook before the first conditional render exit", () => {
    const firstConditionalExit = shellSource.indexOf("if (sourceCollectionStandalone)");
    const lastHook = Math.max(
      shellSource.lastIndexOf("useEffect("),
      shellSource.lastIndexOf("useMemo("),
      shellSource.lastIndexOf("useState("),
    );

    expect(firstConditionalExit).toBeGreaterThan(-1);
    expect(lastHook).toBeGreaterThan(-1);
    expect(lastHook).toBeLessThan(firstConditionalExit);
  });

  it("wires the research primary action into the left status rail CTA", () => {
    expect(shellSource).toContain("const statusCta = researchWorkflowTeamSelected && researchPrimaryAction");
    expect(shellSource).toContain("researchPrimaryActionLabel(researchPrimaryAction, lang)");
    expect(shellSource).toContain("statusCtaDisabled: Boolean(researchPrimaryAction?.blocked)");
  });
});
