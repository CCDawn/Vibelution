import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const panelSource = readFileSync(
  new URL("./HypothesisSelectionPanel.tsx", import.meta.url),
  "utf8",
);
const listSource = readFileSync(
  new URL("./HypothesisSelectionList.tsx", import.meta.url),
  "utf8",
);
const detailPanelSource = readFileSync(
  new URL("./ChallengeQuestionDetailPanel.tsx", import.meta.url),
  "utf8",
);
const inspectorPaneSource = readFileSync(
  new URL("../research-workflow/ResearchProcessInspectorPane.tsx", import.meta.url),
  "utf8",
);

describe("HypothesisSelectionPanel contract (HF-6)", () => {
  it("uses named hypothesisFirst API functions and never raw paths", () => {
    expect(panelSource).toContain("fetchHypothesisSelectionContext");
    expect(listSource).toContain("recordHypothesisSelection");
    expect(listSource).toContain("queryKeys.hypothesisFirstSelectionContext");
    expect(panelSource).not.toContain("fetch(");
    expect(panelSource).not.toMatch(/["'`]\/api\//);
    expect(listSource).not.toMatch(/["'`]\/api\//);
    expect(panelSource).not.toContain("workflow-orchestration/hypothesis-first");
  });

  it("defaults the multi-selection from the server projection", () => {
    expect(listSource).toContain("context?.latestSelection?.selectedCandidateIds");
    expect(listSource).toContain("context?.defaultSelectedCandidateIds");
    expect(listSource).toContain("HYPOTHESIS_SELECTION_MIN = 2");
    expect(listSource).toContain("HYPOTHESIS_SELECTION_MAX = 16");
    expect(panelSource).toContain("HYPOTHESIS_SELECTION_MIN");
    expect(listSource).toContain("VCheckbox");
    expect(listSource).toContain("toggleCandidate");
  });

  it("routes the downstream entry to the operable review node", () => {
    expect(panelSource).toContain("onOpenReviewMeeting");
    expect(panelSource).toContain("hf_meeting_${reviewMeeting.roundIndex}");
    expect(panelSource).toContain("isDisabled={!canOpenReviewMeeting}");
    expect(panelSource).toContain("disabledReason");
    expect(panelSource).toContain("查看评审讨论");
    expect(panelSource).not.toContain("scrollIntoView");
    // Meeting status chip is a server projection, never a local guess.
    expect(panelSource).toContain("reviewMeeting.status");
    expect(panelSource).toContain("context.reviewMeeting");
    expect(detailPanelSource).toContain("onOpenReviewMeeting={onNavigateToNode}");
    expect(inspectorPaneSource).toContain('onNavigateToNode={(nodeId) => actions.replaceParams({ node: nodeId, panel: "node" })}');
  });

  it("submits the server-derived scope instead of a client-assembled one", () => {
    expect(listSource).toContain("...context.scope");
    expect(listSource).toContain("previousSelectionId");
    expect(listSource).toContain("selectedCandidateIds: selectedIds");
  });

  it("stays on the VUI product API surface", () => {
    expect(panelSource).toContain('from "../../../components/vui"');
    expect(panelSource).not.toContain("renderers/shadcn");
    expect(panelSource).not.toContain("@heroui");
  });

  it("is mounted inside the challenge-cup question detail panel", () => {
    expect(detailPanelSource).toContain('from "./HypothesisSelectionPanel"');
    expect(detailPanelSource).toContain("<HypothesisSelectionPanel");
    expect(detailPanelSource).toContain("hypothesis-first-selection");
  });
});
