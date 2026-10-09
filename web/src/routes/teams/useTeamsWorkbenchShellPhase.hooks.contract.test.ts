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

  it("suppresses only the outer team shell chrome for the Challenge Cup workflow", () => {
    expect(shellSource).toContain("isChallengeCupWorkspaceCanonicalizationEligible(searchParams.get(\"researchView\"))");
    expect(shellSource).toMatch(
      /challengeCupResearchTeamSelected\s*&&\s*\(researchWorkspaceView === "workflow" \|\| researchWorkspaceView === "overview"\)/,
    );
    expect(shellSource).toContain("suppressOuterShellChrome: suppressOuterTeamShellChrome");
  });

  it("gates challenge-cup canonicalization on team-owned URLs only", () => {
    // A URL naming another team is a switch in flight (pushed before
    // selectedTeamId commits); canonicalizing it would snap the switch back.
    expect(shellSource).toContain(
      "if (!isChallengeCupCanonicalizationTeamOwned(effectiveTeamId, searchParams)) {",
    );
    // The guard must run before the canonical route is built or navigated.
    const guardIndex = shellSource.indexOf("isChallengeCupCanonicalizationTeamOwned(effectiveTeamId, searchParams)) {");
    const navigateIndex = shellSource.indexOf("navigate(canonicalHref, { replace: true })");
    expect(guardIndex).toBeGreaterThan(-1);
    expect(navigateIndex).toBeGreaterThan(guardIndex);
  });
});
