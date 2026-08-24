import { describe, expect, it, vi } from "vitest";

import {
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisSelections,
  fetchMeetingRounds,
  fetchReviewRoundLinks,
} from "../../../api/hypothesisFirst";
import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";

vi.mock("../../../api/hypothesisFirst", () => ({
  fetchHypothesisFirstChainState: vi.fn(),
  fetchMeetingRounds: vi.fn(),
  fetchHypothesisSelections: vi.fn(),
  fetchCollectionRequests: vi.fn(),
  fetchReviewRoundLinks: vi.fn(),
}));

const mockedState = vi.mocked(fetchHypothesisFirstChainState);
const mockedMeetings = vi.mocked(fetchMeetingRounds);
const mockedSelections = vi.mocked(fetchHypothesisSelections);
const mockedRequests = vi.mocked(fetchCollectionRequests);
const mockedReviewLinks = vi.mocked(fetchReviewRoundLinks);

describe("fetchHypothesisFirstFocusNode", () => {
  it("lands on generation when a candidate-generation meeting is open", async () => {
    mockedState.mockResolvedValue({ candidateCount: 0 } as never);
    mockedMeetings.mockResolvedValue({
      meetings: [{
        question: "SCI-002",
        meetingType: "hypothesis_candidate_generation",
        status: "open",
        meetingRoundId: "gen-1",
        startedAt: "2026-08-19T00:00:00Z",
      }],
    } as never);
    mockedSelections.mockResolvedValue({ selections: [] } as never);
    mockedRequests.mockResolvedValue({ requests: [] } as never);
    mockedReviewLinks.mockResolvedValue({ links: [] } as never);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_generation");
  });

  it("lands on selection when candidates exist and none are chosen", async () => {
    mockedState.mockResolvedValue({ candidateCount: 2 } as never);
    mockedMeetings.mockResolvedValue({
      meetings: [{
        question: "SCI-002",
        meetingType: "hypothesis_candidate_generation",
        status: "closed",
        meetingRoundId: "gen-1",
        startedAt: "2026-08-19T00:00:00Z",
      }],
    } as never);
    mockedSelections.mockResolvedValue({ selections: [] } as never);
    mockedRequests.mockResolvedValue({ requests: [] } as never);
    mockedReviewLinks.mockResolvedValue({ links: [] } as never);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_selection");
  });

  it("lands on the linked current review when historical meetings lack roundIndex", async () => {
    mockedState.mockResolvedValue({ candidateCount: 2, hypothesisConverged: true } as never);
    mockedMeetings.mockResolvedValue({
      meetings: [
        {
          question: "SCI-002",
          meetingType: "hypothesis_review",
          status: "closed",
          meetingRoundId: "r1",
          startedAt: "2026-08-19T01:00:00Z",
        },
        {
          question: "SCI-002",
          meetingType: "hypothesis_review",
          status: "summarizing",
          meetingRoundId: "r5",
          startedAt: "2026-08-19T05:00:00Z",
        },
      ],
    } as never);
    mockedSelections.mockResolvedValue({ selections: [{ selectionId: "sel-1", createdAt: "2026-08-19T00:00:00Z" }] } as never);
    mockedRequests.mockResolvedValue({ requests: [] } as never);
    mockedReviewLinks.mockResolvedValue({
      links: [
        { meetingRoundId: "r1", roundIndex: 1, candidateId: "cand-r1" },
        { meetingRoundId: "r5", roundIndex: 5, candidateId: "cand-r5" },
      ],
    } as never);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_meeting_5_cand-r5");
  });

  it("falls back to generation when the chain cannot be read", async () => {
    mockedState.mockRejectedValue(new Error("offline"));
    mockedMeetings.mockRejectedValue(new Error("offline"));
    mockedSelections.mockRejectedValue(new Error("offline"));
    mockedRequests.mockRejectedValue(new Error("offline"));
    mockedReviewLinks.mockRejectedValue(new Error("offline"));
    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_generation");
  });
});
