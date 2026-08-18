import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const panelSource = readFileSync(
  new URL("./HypothesisSelectionPanel.tsx", import.meta.url),
  "utf8",
);
const detailPanelSource = readFileSync(
  new URL("./ChallengeQuestionDetailPanel.tsx", import.meta.url),
  "utf8",
);

describe("HypothesisSelectionPanel contract (HF-6)", () => {
  it("uses named hypothesisFirst API functions and never raw paths", () => {
    expect(panelSource).toContain("fetchHypothesisSelectionContext");
    expect(panelSource).toContain("recordHypothesisSelection");
    expect(panelSource).toContain("queryKeys.hypothesisFirstSelectionContext");
    expect(panelSource).not.toContain("fetch(");
    expect(panelSource).not.toMatch(/["'`]\/api\//);
    expect(panelSource).not.toContain("workflow-orchestration/hypothesis-first");
  });

  it("defaults the multi-selection from the server projection", () => {
    // Default = latest selection record; fallback = artifact selectedHypothesisIds.
    expect(panelSource).toContain("context?.latestSelection?.selectedCandidateIds");
    expect(panelSource).toContain("context?.defaultSelectedCandidateIds");
    // Multi-select with the 1–16 bounds enforced on toggle.
    expect(panelSource).toContain("HYPOTHESIS_SELECTION_MIN = 1");
    expect(panelSource).toContain("HYPOTHESIS_SELECTION_MAX = 16");
    expect(panelSource).toContain("VCheckbox");
    expect(panelSource).toContain("toggleCandidate");
  });

  it("disables the downstream entry until a review meeting exists server-side", () => {
    expect(panelSource).toContain("isDisabled={!reviewMeetingId}");
    expect(panelSource).toContain("disabledReason");
    expect(panelSource).toContain("查看评审讨论");
    // Meeting status chip is a server projection, never a local guess.
    expect(panelSource).toContain("reviewMeeting.status");
    expect(panelSource).toContain("context.reviewMeeting");
  });

  it("submits the server-derived scope instead of a client-assembled one", () => {
    expect(panelSource).toContain("...context.scope");
    expect(panelSource).toContain("previousSelectionId");
    expect(panelSource).toContain("selectedCandidateIds: selectedIds");
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
