import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../../api/hypothesisFirst", () => ({
  fetchHypothesisSelectionContext: vi.fn(),
  fetchCandidateEvidenceTrail: vi.fn(),
  openHypothesisCandidateGeneration: vi.fn(),
  recordHypothesisSelection: vi.fn(),
}));

import { queryKeys } from "../../../api/queryKeys";
import { HypothesisSelectionPanel } from "./HypothesisSelectionPanel";

function context(status: "open" | "closed") {
  const candidate = {
    mechanism: "机制",
    novelty_basis: "",
    falsifiability: "",
    predictions: [],
    supporting_evidence_refs: [],
    challenging_evidence_refs: [],
    boundary_conditions: [],
  };
  return {
    schemaVersion: 1,
    teamId: "team-1",
    questionId: "SCI-001",
    scope: {
      program: "p",
      theme: "t",
      campaign: "c",
      question: "SCI-001",
      branch: "main",
      workflow: "hypothesis_first",
    },
    mode: "dev",
    candidates: [
      { ...candidate, hypothesis_id: "candidate-a", statement: "候选 A" },
      { ...candidate, hypothesis_id: "candidate-b", statement: "候选 B" },
      { ...candidate, hypothesis_id: "candidate-c", statement: "候选 C" },
    ],
    defaultSelectedCandidateIds: ["candidate-a", "candidate-b"],
    latestSelection: null,
    reviewMeeting: { meetingRoundId: "review-1", status },
  } as never;
}

function renderPanel(status: "open" | "closed"): string {
  const client = new QueryClient();
  client.setQueryData(
    queryKeys.hypothesisFirstSelectionContext("team-1", "SCI-001"),
    context(status),
  );
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <HypothesisSelectionPanel teamId="team-1" questionId="SCI-001" />
    </QueryClientProvider>,
  );
}

describe("HypothesisSelectionPanel", () => {
  it("describes candidate total without calling it the selected count", () => {
    const markup = renderPanel("open");
    expect(markup).toContain("候选总数 3 条");
    expect(markup).toContain("需选择 2–16 条");
    expect(markup).not.toContain("已选候选 3 条");
  });

  it("labels a closed review as a final read-only selection", () => {
    const markup = renderPanel("closed");
    expect(markup).toContain("已关门");
    expect(markup).toContain("最终采用 2 条");
    expect(markup).not.toContain("记录选择并开启评审");
  });
});
