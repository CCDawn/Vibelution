import { describe, expect, it } from "vitest";

import routeSource from "./EvolutionRoute.tsx?raw";

describe("EvolutionRoute library user flow contract", () => {
  it("shows self-evolution candidates as local pending details instead of proposal details", () => {
    expect(routeSource).toContain("selectedProposalIsSelfCandidate");
    expect(routeSource).toContain("!selectedProposalIsSelfCandidate");
    expect(routeSource).toContain("renderSelfEvolutionCandidateDetail(selectedProposalSummary)");
    expect(routeSource).toContain("function isSelfEvolutionCandidateItem");
    expect(routeSource).toContain('item?.ingestMode === "self_evolution_candidate"');
  });

  it("labels self-evolution candidate origins without opening them as supervised runs", () => {
    expect(routeSource).toContain("function proposalDisplaySourceRun");
    expect(routeSource).toContain("item.sourceSelfRunId || item.sourceRun");
    expect(routeSource).toContain("function canOpenProposalSourceRun");
    expect(routeSource).toContain("!isSelfEvolutionCandidateItem(item)");
    expect(routeSource).toContain("selectedProposalDisplaySourceRun || latestRun?.id");
    expect(routeSource).toContain("selectedProposalSummary && selectedProposalCanOpenSourceRun");
    expect(routeSource).toContain("item.riskLevel ? riskLabel(item.riskLevel) : \"--\"");
  });

  it("does not let blocked library items enter batch delete selection", () => {
    const disabledSelectionCount = routeSource.match(/disabled={!item\.canDelete}/g)?.length ?? 0;
    expect(disabledSelectionCount).toBeGreaterThanOrEqual(2);
    expect(routeSource).toContain("visibleLibraryEntries.filter((item) => item.canDelete).map((item) => item.sourceRun)");
    expect(routeSource).toContain("function toggleProposalSelection(item: EvolutionLibraryEntry)");
    expect(routeSource).toContain("if (!item.canDelete)");
    expect(routeSource).toContain("onChange={() => toggleProposalSelection(item)}");
  });
});
