/** @vitest-environment happy-dom */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../api/hypothesisFirst", () => ({
  fetchHypothesisSelectionContext: vi.fn(),
  fetchCandidateEvidenceTrail: vi.fn(),
  recordHypothesisSelection: vi.fn(),
}));
vi.mock("../../../api/queryKeys", () => ({
  queryKeys: {
    hypothesisFirstSelectionContext: () => ["selection-context"],
    teamMeetingRound: () => ["meeting-round"],
    chatRoom: () => ["chat-room"],
  },
}));

import {
  fetchCandidateEvidenceTrail,
  fetchHypothesisSelectionContext,
} from "../../../api/hypothesisFirst";
import { HypothesisSelectionList } from "./HypothesisSelectionList";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const mockedContext = vi.mocked(fetchHypothesisSelectionContext);
const mockedTrail = vi.mocked(fetchCandidateEvidenceTrail);

function candidateContext() {
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
      {
        hypothesis_id: "sci-001-x",
        statement: "素数是整数乘法的原子单元",
        mechanism: "算术基本定理保证唯一分解",
        novelty_basis: "",
        falsifiability: "",
        predictions: [],
        supporting_evidence_refs: [],
        challenging_evidence_refs: [],
        boundary_conditions: [],
      },
    ],
    defaultSelectedCandidateIds: [],
    latestSelection: null,
  } as never;
}

describe("candidate evidence trail expansion", () => {
  let container: HTMLDivElement;
  let root: Root;
  let queryClient: QueryClient;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    mockedContext.mockResolvedValue(candidateContext());
    mockedTrail.mockResolvedValue({
      schemaVersion: 1,
      teamId: "team-1",
      questionId: "SCI-001",
      trails: [
        {
          candidateId: "sci-001-x",
          entries: [
            {
              meetingRoundId: "mr-1",
              meetingLabel: "评审 r1",
              messageId: "m-1",
              speaker: "A016",
              excerpt: "sci-001-x 的机制锚点可追溯（Hardy & Wright 第1章）",
              createdAt: "2026-08-20T01:00:00Z",
            },
          ],
        },
      ],
    } as never);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    queryClient.clear();
    vi.clearAllMocks();
  });

  it("expands a cited discussion trail from the candidate card", async () => {
    act(() => {
      root.render(
        <QueryClientProvider client={queryClient}>
          <HypothesisSelectionList teamId="team-1" questionId="SCI-001" />
        </QueryClientProvider>,
      );
    });
    await act(async () => {
      await vi.waitFor(() =>
        expect(container.textContent).toContain("素数是整数乘法的原子单元"),
      );
    });
    expect(container.textContent).not.toContain("Hardy & Wright");

    const toggle = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("查看证据轨迹"),
    );
    expect(toggle).toBeDefined();
    await act(async () => {
      toggle?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await vi.waitFor(() =>
        expect(container.textContent).toContain("Hardy & Wright"),
      );
    });
    expect(mockedTrail).toHaveBeenCalledWith("team-1", "SCI-001", expect.anything());
    expect(container.textContent).toContain("评审 r1 · A016");
  });
});
